"""
Enhanced EAST (Enhanced Abstract Syntax Tree) Parser for Dockerfiles — Script Detection

Adds robust script detection spanning:
- Interpreter invocations (bash/sh/zsh/etc.)
- Direct execution with arguments
- chmod +x followed by execution (extensionless scripts)
- Relative path resolution via WORKDIR
- COPY/ADD mapping to repo files and optional script content extraction

Note: This file mirrors the baseline in `Dockerfile_EAST.py` and augments RUN/CMD/ENTRYPOINT and COPY/ADD handling.
"""

from anytree import Node
from dockerfile_parse import DockerfileParser
from pathlib import Path
import json
import os
import re


def parse_value_with_variables(value: str):
    # Minimal passthrough to keep compatibility with comparisons
    return ['text', [value]] if '$' not in value else ['value_with_variables', ['text', [value]]]


def is_script_by_extension(filename: str) -> bool:
    script_extensions = {'.sh', '.bash', '.zsh', '.fish', '.csh', '.ksh', '.tcsh', '.py', '.rb'}
    return Path(filename).suffix.lower() in script_extensions


def file_has_shebang(file_path: str) -> bool:
    try:
        with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
            first_line = f.readline(256)
            return first_line.startswith('#!')
    except Exception:
        return False


def tokenize_shell_command(cmd: str):
    # Heuristic tokenization; not a full shell parser
    tokens = []
    buf = ''
    quote = None
    i = 0
    while i < len(cmd):
        ch = cmd[i]
        if ch in ('"', "'"):
            if quote is None:
                quote = ch
            elif quote == ch:
                quote = None
            buf += ch
            i += 1
            continue
        if quote is None and ch.isspace():
            if buf:
                tokens.append(buf)
                buf = ''
            i += 1
            continue
        buf += ch
        i += 1
    if buf:
        tokens.append(buf)
    return tokens


def resolve_path(workdir: str, path_str: str) -> str:
    # Handle relative paths like ./script or script
    p = Path(path_str)
    if p.is_absolute():
        return str(p)
    return str(Path(workdir or '/').joinpath(p).resolve())


class CopyMap:
    """Track COPY/ADD destination paths mapped to repo files."""

    def __init__(self, repo_root: str, dockerfile_path_local: str):
        self.repo_root = repo_root
        self.dockerfile_dir = str(Path(dockerfile_path_local).parent)
        self.container_to_repo = {}

    def record_copy(self, sources, destination: str):
        if not isinstance(sources, list):
            sources = [sources]
        for src in sources:
            src = src.strip()
            if src == '.':
                src_path = self.dockerfile_dir
                # map all files in folder lazily by name
                for dirpath, _, filenames in os.walk(src_path):
                    for filename in filenames:
                        cont_path = os.path.join(destination, filename).replace('\\', '/')
                        repo_path = os.path.join(dirpath, filename)
                        self.container_to_repo[cont_path] = repo_path.replace('\\', '/')
            else:
                repo_path = os.path.join(self.repo_root, src)
                cont_path = os.path.join(destination, os.path.basename(src)).replace('\\', '/')
                self.container_to_repo[cont_path] = repo_path.replace('\\', '/')

    def map_container_path(self, container_path: str):
        # direct match or best prefix match
        container_path = container_path.replace('\\', '/')
        if container_path in self.container_to_repo:
            return self.container_to_repo[container_path]
        # try to match directory prefix
        best = None
        best_len = -1
        for k, v in self.container_to_repo.items():
            if container_path.startswith(k) and len(k) > best_len:
                best = v
                best_len = len(k)
        return best


def extract_script_content(repo_path: str):
    if not repo_path:
        return None
    if not os.path.isfile(repo_path):
        return None
    try:
        with open(repo_path, 'r', encoding='utf-8', errors='ignore') as f:
            lines = [ln for ln in f.readlines() if not ln.strip().startswith('#')]
        return ''.join(lines)
    except Exception:
        return None


def detect_script_invocation(tokens, workdir: str, copy_map: CopyMap, chmod_made_exec_paths: set):
    if not tokens:
        return None
    interpreters = {'bash', 'sh', 'zsh', 'ksh', 'dash', 'python', 'python3', 'node', 'ruby'}
    cmd = tokens[0]
    args = tokens[1:]

    def build_node(path_str: str, args_rest):
        abs_container = resolve_path(workdir, path_str)
        repo_path = copy_map.map_container_path(abs_container)
        is_known_script = is_script_by_extension(path_str) or (repo_path and file_has_shebang(repo_path)) or (abs_container in chmod_made_exec_paths)
        if not is_known_script and os.path.splitext(path_str)[1] == '':
            # extensionless; allow if chmod in same RUN or shebang present
            pass
        content = extract_script_content(repo_path) if repo_path else None
        node = ['script', ['path', [abs_container]]]
        if args_rest:
            node.append(['args', ['text', [' '.join(args_rest)]]])
        if repo_path:
            node.append(['repo_path', [repo_path]])
        if content is not None:
            node.append(['content', [content]])
        return node

    # Interpreter form: bash /path/script.sh [args]
    if cmd in interpreters and args:
        script_path = args[0]
        return build_node(script_path, args[1:])

    # Direct execution form: /path/script.sh [args] or ./script [args]
    if cmd.startswith('/') or cmd.startswith('./') or cmd.startswith('../') or cmd.startswith('.'+os.sep):
        return build_node(cmd, args)

    # bare filename in workdir
    if '/' not in cmd and '\\' not in cmd and (is_script_by_extension(cmd) or cmd in chmod_made_exec_paths):
        return build_node(cmd, args)

    return None


def split_run_commands_logical(command_string: str):
    if not command_string:
        return []
    segments = []
    current = ''
    quote = None
    paren = 0
    i = 0
    while i < len(command_string):
        ch = command_string[i]
        if ch in ('"', "'"):
            if quote is None:
                quote = ch
            elif quote == ch:
                quote = None
            current += ch
            i += 1
            continue
        if quote is not None:
            current += ch
            i += 1
            continue
        if ch == '(':
            paren += 1
            current += ch
            i += 1
            continue
        if ch == ')':
            paren = max(0, paren - 1)
            current += ch
            i += 1
            continue
        if paren == 0 and command_string.startswith('&&', i):
            if current.strip():
                segments.append({'command': current.strip(), 'separator': '&&'})
            current = ''
            i += 2
            continue
        if paren == 0 and command_string.startswith('||', i):
            if current.strip():
                segments.append({'command': current.strip(), 'separator': '||'})
            current = ''
            i += 2
            continue
        current += ch
        i += 1
    if current.strip():
        segments.append({'command': current.strip(), 'separator': None})
    return segments


def handle_run_like(y, instr_name, workdir: str, copy_map: CopyMap):
    # Track chmod +x … within the same RUN; record the paths it marks executable
    segments = split_run_commands_logical(y)
    chmod_exec_paths = set()
    for seg in segments:
        toks = tokenize_shell_command(seg['command'])
        if toks and toks[0] == 'chmod' and len(toks) >= 3 and ('+x' in toks[1] or 'a+x' in toks[1]):
            # collect all following tokens that look like paths
            for path_tok in toks[2:]:
                if path_tok.startswith('-'):
                    continue
                abs_path = resolve_path(workdir, path_tok)
                chmod_exec_paths.add(abs_path)

    result = [instr_name]
    for seg in segments:
        toks = tokenize_shell_command(seg['command'])
        node = detect_script_invocation(toks, workdir, copy_map, chmod_exec_paths)
        if node:
            segment = ['command_segment', node]
        else:
            segment = ['command_segment', ['command', parse_value_with_variables(seg['command'])]]
        if seg['separator']:
            segment.append(['separator', [seg['separator']]])
        result.append(segment)
    return result


def handle_copy_add(y, x, workdir: str, copy_map: CopyMap):
    # Very lightweight parsing (no flags support here beyond basic split)
    parts = y.split()
    if len(parts) < 2:
        return [x, ['error', ['Invalid COPY/ADD format']]]
    source = parts[0]
    destination = parts[1]
    copy_map.record_copy([source], destination)
    return [x, ['source', parse_value_with_variables(source)], ['destination', parse_value_with_variables(destination)]]


def EAST(dockerfile_content: str, temp_repo_path: str, dockerfile_path_local: str):
    parser = DockerfileParser()
    parser.content = dockerfile_content

    copy_map = CopyMap(temp_repo_path, dockerfile_path_local)
    workdir = '/'
    result = ['stage']
    stage_number = 0

    for instruction in parser.structure:
        instr = instruction['instruction']
        val = instruction['value']
        if instr == 'FROM':
            stage_number += 1
            result.append(['FROM', ['stage', [stage_number]]])
        elif instr == 'WORKDIR':
            workdir = val.strip() or '/'
            result.append(['WORKDIR', ['path', parse_value_with_variables(val)]])
        elif instr in ('COPY', 'ADD'):
            result.append(handle_copy_add(val, instr, workdir, copy_map))
        elif instr in ('RUN', 'CMD', 'ENTRYPOINT'):
            result.append(handle_run_like(val, instr, workdir, copy_map))
        else:
            result.append([instr, ['value', parse_value_with_variables(val)]])
    return result


def create_node(data):
    if isinstance(data, list) and data:
        name = str(data[0])
        children = []
        for child in data[1:]:
            if isinstance(child, list):
                children.append(create_node(child))
        return Node(name, children=children)
    return Node(str(data))


def json_to_tree(json_list):
    return create_node(json_list)


def get_EAST(dockerfile_content, temp_repo_path, dockerfile_path_local):
    east_data = EAST(dockerfile_content, temp_repo_path, dockerfile_path_local)
    return json_to_tree(east_data)

