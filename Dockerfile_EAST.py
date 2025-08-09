"""
Enhanced EAST (Enhanced Abstract Syntax Tree) Parser for Dockerfiles

This module provides functionality to parse Dockerfile content and convert it into
an enhanced abstract syntax tree representation with improved RUN instruction parsing.

Key Features:
- Multi-stage build support with dependency tracking
- Enhanced environment variable and argument parsing with variable component extraction
- Script detection and content extraction
- Port and protocol parsing
- User/group ID parsing
- File copy/add operations with source/destination mapping
- Variable metadata extraction and classification
- Enhanced RUN instruction parsing with support for complex command separators
"""

from anytree import Node
import json
from dockerfile_parse import DockerfileParser
import os
from pathlib import Path
import re

# --- Script detection integration (2.3) ---
container_to_repo_map = {}
current_build_args = {}

def _tokenize_shell_command(cmd: str):
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


def _resolve_path(workdir: str, path_str: str) -> str:
    p = Path(path_str)
    if p.is_absolute():
        return str(p)
    return str(Path(workdir or '/').joinpath(p).resolve())


def _file_has_shebang(file_path: str) -> bool:
    try:
        with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
            first = f.readline(256)
            return first.startswith('#!')
    except Exception:
        return False


def _extract_script_content(repo_path: str):
    if not repo_path or not os.path.isfile(repo_path):
        return None
    try:
        with open(repo_path, 'r', encoding='utf-8', errors='ignore') as f:
            lines = [ln for ln in f.readlines() if not ln.strip().startswith('#')]
        return ''.join(lines)
    except Exception:
        return None


def _detect_script_invocation(tokens, workdir: str, chmod_exec_paths: set):
    if not tokens:
        return None
    interpreters = {'bash', 'sh', 'zsh', 'ksh', 'dash', 'python', 'python3', 'node', 'ruby'}

    def build_node(path_str: str, args_rest):
        abs_container = _resolve_path(workdir, path_str)
        repo_path = container_to_repo_map.get(abs_container.replace('\\', '/'))
        is_known = is_script(path_str) or (repo_path and _file_has_shebang(repo_path)) or (abs_container in chmod_exec_paths)
        content = _extract_script_content(repo_path) if repo_path else None
        node = ['script', ['path', [abs_container]]]
        if args_rest:
            node.append(['args', ['text', [' '.join(args_rest)]]])
        if repo_path:
            node.append(['repo_path', [repo_path]])
        if content is not None and is_known:
            node.append(['content', [content]])
        return node

    cmd = tokens[0]
    args = tokens[1:]
    # Interpreter form
    if cmd in interpreters and args:
        return build_node(args[0], args[1:])
    # Direct execution
    if cmd.startswith('/') or cmd.startswith('./') or cmd.startswith('../') or cmd.startswith('.'+os.sep):
        return build_node(cmd, args)
    # Bare name in workdir
    if '/' not in cmd and '\\' not in cmd and (is_script(cmd) or _resolve_path(workdir, cmd) in chmod_exec_paths):
        return build_node(cmd, args)
    return None


# --- COPY/ADD enhancements (4.x) ---
def _brace_expand(pattern: str):
    # Simple one-level {a,b} expansion
    if '{' not in pattern or '}' not in pattern:
        return [pattern]
    # find first {...}
    start = pattern.find('{')
    end = pattern.find('}', start + 1)
    if end == -1:
        return [pattern]
    head = pattern[:start]
    body = pattern[start + 1:end]
    tail = pattern[end + 1:]
    parts = body.split(',')
    expanded = []
    for p in parts:
        expanded.append(head + p + tail)
    return expanded


def _determine_content_type(file_path: str):
    try:
        size = os.path.getsize(file_path)
    except Exception:
        return 'unknown', 0
    ctype = 'text'
    try:
        with open(file_path, 'rb') as fb:
            chunk = fb.read(4096)
            if b'\x00' in chunk:
                return 'binary', size
    except Exception:
        return 'unknown', size
    # text heuristics
    lower = file_path.lower()
    if lower.endswith('.json'):
        try:
            import json as _json
            with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
                _json.load(f)
            return 'json', size
        except Exception:
            return 'text', size
    if os.path.basename(lower) == '.env' or lower.endswith('.env'):
        return 'env', size
    return 'text', size


def variableExists(x):
    """
    Check if a string contains Docker environment variable syntax and extract variable information
    
    Handles complex variable syntax including:
    - $VAR (simple variable)
    - ${VAR} (braced variable)
    - ${VAR:-default} (default value)
    - ${VAR:+suffix} (substitute if set)
    - ${VAR:-${INNER:-fallback}} (nested variables)
    - ${VAR#prefix} (remove prefix)
    - ${VAR%suffix} (remove suffix)
    
    Args:
        x (str): String to check for variable syntax
        
    Returns:
        tuple: (variable_name, begin_pos, end_pos) or ('', 0, 0) if no variable found
    """
    # Quick check for dollar sign
    if '$' not in x:
        return '', 0, 0
    
    # Try to match simple variables first (e.g., $VAR)
    simple_pattern = r'\$[a-zA-Z_][a-zA-Z0-9_]*'
    match = re.search(simple_pattern, x)
    if match:
        begin = match.start()
        end = match.end()
        variable = x[begin:end]
        return variable, begin, end
    
    # Try to match braced variables with nested braces (e.g., ${VAR})
    if '${' in x:
        begin = x.find('${')
        # Find the matching closing brace, handling nested braces
        brace_count = 0
        end = begin
        for i in range(begin, len(x)):
            if x[i] == '{':
                brace_count += 1
            elif x[i] == '}':
                brace_count -= 1
                if brace_count == 0:
                    end = i + 1
                    break
        
        if end > begin:
            variable = x[begin:end]
            return variable, begin, end
    
    return '', 0, 0


def extract_variable_components(variable):
    """
    Extract components from a Docker variable expression
    
    Args:
        variable (str): Variable expression like ${VAR:-default}
        
    Returns:
        dict: Dictionary with variable components
    """
    # Handle simple $VAR syntax
    if not variable.startswith('$'):
        return {}
    
    if not variable.startswith('${'):
        var_name = variable[1:]  # Remove $ prefix
        return {
            'name': var_name,
            'type': 'simple',
            'default': None,
            'substitute': None,
            'operation': None
        }
    
    # Handle ${VAR} syntax
    if variable.startswith('${') and variable.endswith('}'):
        content = variable[2:-1]  # Remove ${ and }
        
        # Check for default value syntax: ${VAR:-default}
        default_match = re.match(r'^([a-zA-Z_][a-zA-Z0-9_]*):-([^}]*)$', content)
        if default_match:
            return {
                'name': default_match.group(1),
                'type': 'default',
                'default': default_match.group(2),
                'substitute': None,
                'operation': None
            }
        
        # Check for substitute if set syntax: ${VAR:+suffix}
        substitute_match = re.match(r'^([a-zA-Z_][a-zA-Z0-9_]*):\+([^}]*)$', content)
        if substitute_match:
            return {
                'name': substitute_match.group(1),
                'type': 'substitute',
                'default': None,
                'substitute': substitute_match.group(2),
                'operation': None
            }
        
        # Check for prefix removal syntax: ${VAR#prefix}
        prefix_match = re.match(r'^([a-zA-Z_][a-zA-Z0-9_]*)#([^}]*)$', content)
        if prefix_match:
            return {
                'name': prefix_match.group(1),
                'type': 'operation',
                'default': None,
                'substitute': None,
                'operation': {
                    'type': 'remove_prefix',
                    'value': prefix_match.group(2)
                }
            }
        
        # Check for suffix removal syntax: ${VAR%suffix}
        suffix_match = re.match(r'^([a-zA-Z_][a-zA-Z0-9_]*)%([^}]*)$', content)
        if suffix_match:
            return {
                'name': suffix_match.group(1),
                'type': 'operation',
                'default': None,
                'substitute': None,
                'operation': {
                    'type': 'remove_suffix',
                    'value': suffix_match.group(2)
                }
            }
        
        # Simple braced variable: ${VAR}
        return {
            'name': content,
            'type': 'simple',
            'default': None,
            'substitute': None,
            'operation': None
        }
    
    return {}


def find_all_variables(x):
    """
    Find all variable expressions in a string
    
    Args:
        x (str): String to search for variables
        
    Returns:
        list: List of tuples (variable, begin_pos, end_pos)
    """
    if '$' not in x:
        return []
    
    variables = []
    
    # Find simple variables (e.g., $VAR)
    simple_pattern = r'\$[a-zA-Z_][a-zA-Z0-9_]*'
    for match in re.finditer(simple_pattern, x):
        begin = match.start()
        end = match.end()
        variable = x[begin:end]
        variables.append((variable, begin, end))
    
    # Find braced variables with nested braces (e.g., ${VAR})
    if '${' in x:
        pos = 0
        while True:
            begin = x.find('${', pos)
            if begin == -1:
                break
            
            # Find the matching closing brace, handling nested braces
            brace_count = 0
            end = begin
            for i in range(begin, len(x)):
                if x[i] == '{':
                    brace_count += 1
                elif x[i] == '}':
                    brace_count -= 1
                    if brace_count == 0:
                        end = i + 1
                        break
            
            if end > begin:
                variable = x[begin:end]
                variables.append((variable, begin, end))
                pos = end
            else:
                pos = begin + 1
    
    return variables


def parse_value_with_variables(value):
    """
    Parse a value string and extract variable information
    
    Args:
        value (str): Value string that may contain variables
        
    Returns:
        list: Structured representation with variable metadata
    """
    variables = find_all_variables(value)
    
    if not variables:
        # No variables found, return as plain text
        return ['text', [value]]
    
    # Variables found, structure them
    result = ['value_with_variables']
    
    # Split the value by variables and create structured representation
    last_end = 0
    for variable, begin, end in variables:
        # Add text before variable
        if begin > last_end:
            text_part = value[last_end:begin]
            if text_part:
                result.append(['text', [text_part]])
        
        # Add variable with metadata
        components = extract_variable_components(variable)
        var_structure = ['variable', ['name', [components.get('name', '')]]]
        
        if components.get('type'):
            var_structure.append(['type', [components['type']]])
        
        if components.get('default'):
            var_structure.append(['default', [components['default']]])
        
        if components.get('substitute'):
            var_structure.append(['substitute', [components['substitute']]])
        
        if components.get('operation'):
            op = components['operation']
            var_structure.append(['operation', [
                ['type', [op['type']]],
                ['value', [op['value']]]
            ]])
        
        result.append(var_structure)
        last_end = end
    
    # Add remaining text after last variable
    if last_end < len(value):
        text_part = value[last_end:]
        if text_part:
            result.append(['text', [text_part]])
    
    return result


def searchPosition(x, y):
    """
    Search for a substring in a string, accounting for Docker variable syntax
    
    This function handles cases where the search string might be inside
    a Docker environment variable (e.g., $VAR or ${VAR})
    
    Args:
        x (str): String to search in
        y (str): Substring to search for
        
    Returns:
        int: Position of substring, or -1 if not found
    """
    # Find all variables in the string
    variables = find_all_variables(x)
    pos = x.find(y)
    
    if y in x:
        # Check if the found position is inside any variable
        for variable, begin, end in variables:
            if begin <= pos < end:
                # Position is inside a variable, find next occurrence
                old = pos
                pos = x[pos + len(y):].find(y)
                if pos != -1:
                    pos += old + len(y)
                    # Check if this new position is also inside a variable
                    for var, var_begin, var_end in variables:
                        if var_begin <= pos < var_end:
                            # Still inside a variable, continue searching
                            old = pos
                            pos = x[pos + len(y):].find(y)
                            if pos != -1:
                                pos += old + len(y)
                            break
                else:
                    return -1
                break
        return pos
    return -1


def parse_image_parts(y):
    """
    Parse Docker image reference into base image and digest parts
    
    Handles image references like:
    - ubuntu:latest@sha256:abc123
    - nginx:alpine AS myapp
    
    Args:
        y (str): Image reference string
        
    Returns:
        tuple: (image_part1, image_part2) where part1 is base image and part2 is digest/alias
    """
    # Split by @ to separate base image from digest
    pos_alt = searchPosition(y, '@')
    if pos_alt != -1:
        image_part1 = y[:pos_alt]  # Base image part
        image_part2 = y[pos_alt + 1:]  # Digest part
    else:
        image_part1, image_part2 = y, None
    return image_part1, image_part2


def parse_image_name_and_tag(image_part1):
    """
    Extract image name and tag from the base image part
    
    Args:
        image_part1 (str): Base image part (e.g., "ubuntu:latest AS myapp")
        
    Returns:
        tuple: (image_name, image_tag)
    """
    # Find colon separator for tag
    pos_2points = searchPosition(image_part1, ':')
    # Find AS keyword for stage alias
    pos_as = searchPosition(image_part1, ' AS ')
    if pos_as == -1:
        pos_as = searchPosition(image_part1, ' as ')
    if pos_as != -1:
        image_part1 = image_part1[:pos_as]  # Remove the AS myapp part

    # Extract name and tag
    if pos_2points != -1 and (pos_as == -1 or pos_2points < pos_as):
        image_name = image_part1[:pos_2points]
        image_tag = image_part1[pos_2points + 1:]
    else:
        image_name = image_part1
        image_tag = None

    return image_name, image_tag


def parse_digest_and_alias(image_part2):
    """
    Parse digest and alias from the second part of image reference
    
    Args:
        image_part2 (str): Digest/alias part of image reference
        
    Returns:
        tuple: (digest, alias) where either can be None
    """
    if not image_part2:
        return None, None
    
    # Check if it's a digest (contains :)
    if ':' in image_part2:
        return image_part2, None
    else:
        # It's an alias
        return None, image_part2


def parse_alias(y):
    """
    Parse stage alias from image reference
    
    Args:
        y (str): Image reference string
        
    Returns:
        str: Stage alias or None
    """
    pos_as = searchPosition(y, ' AS ')
    if pos_as == -1:
        pos_as = searchPosition(y, ' as ')
    
    if pos_as != -1:
        return y[pos_as + 4:]  # Skip ' AS ' or ' as '
    return None


def handle_from(y, x, nb_stage):
    """
    Parse FROM instruction with enhanced variable support
    
    Args:
        y (str): FROM instruction value
        x (str): Instruction name ('FROM')
        nb_stage (int): Stage number
        
    Returns:
        list: Structured representation of FROM instruction
    """
    # Parse image parts
    image_part1, image_part2 = parse_image_parts(y)
    
    # Parse image name and tag
    image_name, image_tag = parse_image_name_and_tag(image_part1)
    
    # Parse digest and alias
    digest, alias = parse_digest_and_alias(image_part2)
    
    # Parse stage alias
    stage_alias = parse_alias(y)
    
    # Build result structure
    result = [x, ['stage', [nb_stage]]]
    
    # Add image information
    if image_name:
        result.append(['image_name', [image_name]])
    
    if image_tag:
        result.append(['image_tag', [image_tag]])
    
    if digest:
        result.append(['digest', [digest]])
    
    if stage_alias:
        result.append(['alias', [stage_alias]])
    
    return result


def handle_env(y, x):
    """
    Parse ENV with multi-line support and add value validation metadata.
    
    Supports both formats:
    - ENV KEY=value [KEY2=value2 ...]
    - ENV KEY value [KEY2 value2 ...]
    with line continuations using '\\'.
    """
    def _remove_line_continuations(text: str) -> str:
        # Replace backslash-newline (and optional following spaces) with a single space
        return re.sub(r"\\\s*\n\s*", " ", text)

    def _tokenize_env(text: str):
        # Split on whitespace but preserve quoted substrings
        tokens = []
        buf = ''
        quote = None
        i = 0
        while i < len(text):
            ch = text[i]
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

    def _strip_quotes(val: str) -> str:
        if (val.startswith('"') and val.endswith('"')) or (val.startswith("'") and val.endswith("'")):
            return val[1:-1]
        return val

    def _analyze_env_value(key: str, raw_value: str):
        meta = ['validation']
        k_up = key.upper()
        v_raw = _strip_quotes(raw_value.strip())
        # Boolean
        bool_map = {
            'true': True, 'false': False,
            '1': True, '0': False,
            'yes': True, 'no': False
        }
        v_low = v_raw.lower()
        if v_low in bool_map:
            meta.append(['type', ['boolean']])
            meta.append(['normalized', [str(bool_map[v_low])]])
        # Port
        if k_up == 'PORT' or k_up.endswith('_PORT'):
            issue = None
            try:
                port_val = int(v_raw)
                if port_val < 1 or port_val > 65535:
                    issue = 'out_of_range'
            except ValueError:
                issue = 'not_integer'
            meta.append(['type', ['port']])
            if issue:
                meta.append(['issue', [issue]])
        # Path-like
        if k_up == 'PATH' or k_up.endswith('_PATH') or ':' in v_raw:
            segments = [seg for seg in v_raw.split(':') if seg]
            meta.append(['type', ['path']])
            meta.append(['segments', [str(len(segments))]])
        # Secret-like
        secret_keywords = ['SECRET', 'KEY', 'TOKEN', 'PASSWORD', 'PASS', 'AWS_']
        looks_secret = any(word in k_up for word in secret_keywords)
        if not looks_secret:
            # long random-ish value heuristic
            if len(v_raw) >= 16 and re.fullmatch(r'[A-Za-z0-9+/=_\-]+', v_raw):
                looks_secret = True
        if looks_secret:
            meta.append(['type', ['potential_secret']])
        return meta

    content = _remove_line_continuations(y)
    tokens = _tokenize_env(content)
    key_values = []
    i = 0
    while i < len(tokens):
        token = tokens[i]
        if '=' in token:
            key, value = token.split('=', 1)
            parsed_value = parse_value_with_variables(value)
            pair = ['pair', ['key', [key]], ['value', parsed_value], _analyze_env_value(key, value)]
            key_values.append(pair)
            i += 1
            continue
        # KEY value
        key = token
        value = tokens[i + 1] if (i + 1) < len(tokens) else ''
        parsed_value = parse_value_with_variables(value)
        pair = ['pair', ['key', [key]], ['value', parsed_value], _analyze_env_value(key, value)]
        key_values.append(pair)
        i += 2
    return [x, key_values]


def handle_arg(y, x):
    """
    Parse ARG instruction with enhanced variable support
    
    Handles both formats:
    - ARG name=value
    - ARG name
    
    Args:
        y (str): ARG instruction value
        x (str): Instruction name ('ARG')
        
    Returns:
        list: Structured representation of build argument with variable metadata
    """
    # Check for equals sign to separate name and value
    pos_equal = searchPosition(y, '=')
    if (pos_equal != -1):
        name = y[:pos_equal]
        value = y[pos_equal + 1:]
        parsed_value = parse_value_with_variables(value)
        node = [x, ['name', [name]], ['value', parsed_value]]
        node.append(['source', ['default']])
        return node
    # Unassigned ARG: resolve from build-time mapping if available
    name = y.strip()
    node = [x, ['name', [name]]]
    if name in current_build_args:
        resolved = str(current_build_args[name])
        node.append(['resolved', ['text', [resolved]]])
        node.append(['source', ['build_arg']])
    return node


def handle_expose(y, x):
    """
    Parse EXPOSE instruction and extract port/protocol information
    
    Handles formats like:
    - EXPOSE 80
    - EXPOSE 80/tcp
    - EXPOSE 80 443
    
    Args:
        y (str): EXPOSE instruction value
        x (str): Instruction name ('EXPOSE')
        
    Returns:
        list: Structured representation of exposed ports
    """
    ports = y.split()
    portlist = ['port']
    nb = 0
    for port1 in ports:
        nb = nb + 1
        # Check for protocol separator
        pos_anti = searchPosition(port1, '/')
        if (pos_anti != -1):
            # Port with protocol (e.g., 80/tcp)
            port = port1[:pos_anti]
            protocol = port1[pos_anti + 1:]
            y = [nb, ['value', [port]], ['protocol', [protocol]]]
            # Validation
            issues = []
            try:
                p = int(port)
                if p < 1 or p > 65535:
                    issues.append('port_out_of_range')
            except ValueError:
                issues.append('port_not_integer')
            if protocol.lower() not in {'tcp', 'udp', 'sctp'}:
                issues.append('invalid_protocol')
            if issues:
                y.append(['validation', ['issues', [', '.join(issues)]]])
        else:
            # Port without protocol
            y = [nb, ['value', [port1]]]
            issues = []
            try:
                p = int(port1)
                if p < 1 or p > 65535:
                    issues.append('port_out_of_range')
            except ValueError:
                issues.append('port_not_integer')
            if issues:
                y.append(['validation', ['issues', [', '.join(issues)]]])
        portlist.append(y)
    return [x, portlist]


def handle_user(y, x):
    """
    Parse USER instruction with enhanced variable support
    
    Handles formats like:
    - USER username
    - USER username:group
    - USER uid:gid
    - USER username:group:uid:gid
    
    Args:
        y (str): USER instruction value
        x (str): Instruction name ('USER')
        
    Returns:
        list: Structured representation of user specification with variable metadata
    """
    # Parse value with variable support
    parsed_value = parse_value_with_variables(y)
    
    # Check for colon separators
    parts = y.split(':')
    if len(parts) == 1:
        # Just username
        node = [x, ['user', parsed_value]]
        uname = y.strip()
        validation = ['validation']
        if uname.startswith('-'):
            validation.append(['issue', ['negative_uid']])
        node.append(validation)
        return node
    elif len(parts) == 2:
        # username:group or uid:gid
        username, group = parts
        node = [x, ['user', parse_value_with_variables(username)], ['group', parse_value_with_variables(group)]]
        validation = ['validation']
        # Numeric check
        try:
            uid = int(username)
            if uid < 0:
                validation.append(['issue', ['negative_uid']])
        except ValueError:
            pass
        try:
            gid = int(group)
            if gid < 0:
                validation.append(['issue', ['negative_gid']])
        except ValueError:
            pass
        if len(validation) > 1:
            node.append(validation)
        return node
    elif len(parts) == 4:
        # username:group:uid:gid
        username, group, uid, gid = parts
        node = [x, 
                ['user', parse_value_with_variables(username)], 
                ['group', parse_value_with_variables(group)],
                ['uid', parse_value_with_variables(uid)],
                ['gid', parse_value_with_variables(gid)]]
        validation = ['validation']
        try:
            u = int(uid)
            if u < 0:
                validation.append(['issue', ['negative_uid']])
        except ValueError:
            validation.append(['issue', ['uid_not_integer']])
        try:
            g = int(gid)
            if g < 0:
                validation.append(['issue', ['negative_gid']])
        except ValueError:
            validation.append(['issue', ['gid_not_integer']])
        if len(validation) > 1:
            node.append(validation)
        return node
    else:
        # Fallback to simple user
        return [x, ['user', parsed_value]]


def is_script(filename):
    """
    Check if a file is a script based on its extension
    
    Args:
        filename (str): Filename to check
        
    Returns:
        bool: True if file is a script
    """
    script_extensions = {'.sh', '.bash', '.zsh', '.fish', '.csh', '.ksh', '.tcsh'}
    return Path(filename).suffix.lower() in script_extensions


def split_run_commands(command_string):
    """
    Enhanced RUN command splitting that handles complex shell syntax
    
    Handles separators:
    - && (AND operator)
    - || (OR operator) 
    - ; (semicolon separator)
    - | (pipe)
    - & (background execution)
    - Parentheses grouping
    
    Args:
        command_string (str): RUN command string
        
    Returns:
        list: List of command segments with their separators
    """
    if not command_string:
        return []
    
    # Handle JSON array format
    if command_string.startswith('[') and command_string.endswith(']'):
        try:
            commands = json.loads(command_string)
            if isinstance(commands, list):
                return [{'command': str(cmd), 'separator': None, 'type': 'json_array'} for cmd in commands]
        except json.JSONDecodeError:
            pass
    
    # Handle shell command format
    segments = []
    current_command = ""
    current_separator = None
    paren_depth = 0
    quote_char = None
    i = 0
    
    while i < len(command_string):
        char = command_string[i]
        
        # Handle quotes
        if char in ['"', "'"]:
            if quote_char is None:
                quote_char = char
            elif quote_char == char:
                quote_char = None
            current_command += char
            i += 1
            continue
        
        # Skip processing separators inside quotes
        if quote_char is not None:
            current_command += char
            i += 1
            continue
        
        # Handle parentheses
        if char == '(':
            paren_depth += 1
            current_command += char
            i += 1
            continue
        elif char == ')':
            paren_depth -= 1
            current_command += char
            i += 1
            continue
        
        # Skip processing separators inside parentheses
        if paren_depth > 0:
            current_command += char
            i += 1
            continue
        
        # Check for separators
        separator_found = False
        
        # Check for && (AND operator)
        if i + 1 < len(command_string) and command_string[i:i+2] == '&&':
            if current_command.strip():
                segments.append({
                    'command': current_command.strip(),
                    'separator': '&&',
                    'type': 'and_operator'
                })
            current_command = ""
            current_separator = '&&'
            i += 2
            separator_found = True
        
        # Check for || (OR operator)
        elif i + 1 < len(command_string) and command_string[i:i+2] == '||':
            if current_command.strip():
                segments.append({
                    'command': current_command.strip(),
                    'separator': '||',
                    'type': 'or_operator'
                })
            current_command = ""
            current_separator = '||'
            i += 2
            separator_found = True
        
        # Check for ; (semicolon)
        elif char == ';':
            if current_command.strip():
                segments.append({
                    'command': current_command.strip(),
                    'separator': ';',
                    'type': 'semicolon'
                })
            current_command = ""
            current_separator = ';'
            i += 1
            separator_found = True
        
        # Check for | (pipe)
        elif char == '|':
            if current_command.strip():
                segments.append({
                    'command': current_command.strip(),
                    'separator': '|',
                    'type': 'pipe'
                })
            current_command = ""
            current_separator = '|'
            i += 1
            separator_found = True
        
        # Check for & (background)
        elif char == '&':
            if current_command.strip():
                segments.append({
                    'command': current_command.strip(),
                    'separator': '&',
                    'type': 'background'
                })
            current_command = ""
            current_separator = '&'
            i += 1
            separator_found = True
        
        if not separator_found:
            current_command += char
            i += 1
    
    # Add the last command if there is one
    if current_command.strip():
        segments.append({
            'command': current_command.strip(),
            'separator': None,
            'type': 'final'
        })
    
    return segments


def split_run_commands_logical(command_string: str):
    """
    Split only on top-level logical operators (&&, ||), preserving semicolons inside shell constructs.
    """
    if not command_string:
        return []
    # JSON array passthrough
    if command_string.startswith('[') and command_string.endswith(']'):
        try:
            commands = json.loads(command_string)
            if isinstance(commands, list):
                return [{'command': str(cmd), 'separator': None, 'type': 'json_array'} for cmd in commands]
        except json.JSONDecodeError:
            pass
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
            paren -= 1 if paren > 0 else 0
            current += ch
            i += 1
            continue
        if paren == 0:
            if command_string.startswith('&&', i):
                if current.strip():
                    segments.append({'command': current.strip(), 'separator': '&&', 'type': 'and_operator'})
                current = ''
                i += 2
                continue
            if command_string.startswith('||', i):
                if current.strip():
                    segments.append({'command': current.strip(), 'separator': '||', 'type': 'or_operator'})
                current = ''
                i += 2
                continue
        current += ch
        i += 1
    if current.strip():
        segments.append({'command': current.strip(), 'separator': None, 'type': 'final'})
    return segments


# -------- Shell construct parsers (heuristic) --------

def _strip_outer_whitespace(text: str) -> str:
    return text.strip() if text is not None else text


def parse_for_loop(command: str):
    m = re.match(r"^\s*for\s+([A-Za-z_][A-Za-z0-9_]*)\s+in\s+(.*?)\s*;\s*do\s+(.*?)\s*;\s*done\s*$", command, re.DOTALL)
    if not m:
        return None
    var_name = m.group(1)
    iterable = m.group(2)
    body = m.group(3)
    nested = parse_shell_construct(_strip_outer_whitespace(body))
    if nested:
        body_node = nested
    else:
        body_node = parse_value_with_variables(_strip_outer_whitespace(body))
    return ['shell_for',
            ['variable', [var_name]],
            ['in', parse_value_with_variables(_strip_outer_whitespace(iterable))],
            ['body', body_node]]


def parse_while_loop(command: str):
    m = re.match(r"^\s*while\s+(.*?)\s*;\s*do\s+(.*?)\s*;\s*done\s*$", command, re.DOTALL)
    if not m:
        return None
    condition = m.group(1)
    body = m.group(2)
    nested = parse_shell_construct(_strip_outer_whitespace(body))
    if nested:
        body_node = nested
    else:
        body_node = parse_value_with_variables(_strip_outer_whitespace(body))
    return ['shell_while',
            ['condition', parse_value_with_variables(_strip_outer_whitespace(condition))],
            ['body', body_node]]


def parse_if_block(command: str):
    text = command.strip()
    if not text.startswith('if '):
        return None
    def find_token(src, token):
        quote = None
        i = 0
        while i <= len(src) - len(token):
            ch = src[i]
            if ch in ('"', "'"):
                if quote is None:
                    quote = ch
                elif quote == ch:
                    quote = None
                i += 1
                continue
            if quote is None and src.startswith(token, i):
                return i
            i += 1
        return -1
    pos_then = find_token(text, ' then')
    if pos_then == -1:
        pos_then = find_token(text, '; then')
        if pos_then == -1:
            return None
    cond = text[3:pos_then].strip(' ;')
    after_then = text[pos_then:]
    if after_then.startswith(' then'):
        after_then = after_then[len(' then'):]
    elif after_then.startswith('; then'):
        after_then = after_then[len('; then'):]
    i = 0
    quote = None
    tokens = []
    while i < len(after_then):
        ch = after_then[i]
        if ch in ('"', "'"):
            if quote is None:
                quote = ch
            elif quote == ch:
                quote = None
            i += 1
            continue
        if quote is None:
            if after_then.startswith('; elif ', i):
                tokens.append(('elif', i))
                i += len('; elif ')
                continue
            if after_then.startswith('; else', i):
                tokens.append(('else', i))
                i += len('; else')
                continue
            if after_then.startswith('; fi', i) or after_then.startswith(' fi', i) or after_then.startswith('fi', i):
                tokens.append(('fi', i))
                break
        i += 1
    cursor = 0
    result = ['shell_if', ['condition', parse_value_with_variables(cond)]]
    def clean(s):
        return _strip_outer_whitespace(s.strip(' ;'))
    def nested_or_value(label: str, content: str):
        node = parse_shell_construct(clean(content))
        if node:
            return [label, node]
        return [label, parse_value_with_variables(clean(content))]
    if tokens:
        kind, pos = tokens[0]
        then_body = clean(after_then[cursor:pos])
        result.append(nested_or_value('then', then_body))
        cursor = pos
        idx = 0
        while idx < len(tokens):
            kind, pos = tokens[idx]
            if kind == 'elif':
                rem = after_then[pos:]
                m = re.match(r"^;\s*elif\s+(.*?)\s*;\s*then\s+", rem, re.DOTALL)
                if not m:
                    break
                elif_cond = clean(m.group(1))
                body_start = pos + m.end()
                next_pos = tokens[idx + 1][1] if (idx + 1) < len(tokens) else len(after_then)
                elif_body = clean(after_then[body_start:next_pos])
                body_entry = nested_or_value('body', elif_body)
                result.append(['elif', ['condition', parse_value_with_variables(elif_cond)], body_entry])
                idx += 1
                cursor = next_pos
            elif kind == 'else':
                next_pos = tokens[idx + 1][1] if (idx + 1) < len(tokens) else len(after_then)
                else_body = clean(after_then[pos + len('; else'):next_pos])
                result.append(nested_or_value('else', else_body))
                idx += 1
                cursor = next_pos
            elif kind == 'fi':
                break
            else:
                idx += 1
    else:
        if after_then.endswith(' fi'):
            then_body = clean(after_then[:-3])
            result.append(nested_or_value('then', then_body))
        elif after_then.endswith('; fi'):
            then_body = clean(after_then[:-4])
            result.append(nested_or_value('then', then_body))
        else:
            return None
    return result


def parse_case_block(command: str):
    m = re.match(r"^\s*case\s+(.*?)\s+in\s+(.*)\s+esac\s*$", command, re.DOTALL)
    if not m:
        return None
    value = m.group(1)
    body = m.group(2).strip()
    clauses_raw = re.split(r";;\s*", body)
    clauses = []
    for raw in clauses_raw:
        raw = raw.strip()
        if not raw:
            continue
        m2 = re.match(r"^(.*?)\)\s*(.*)$", raw, re.DOTALL)
        if not m2:
            continue
        pattern = m2.group(1).strip()
        cmd = m2.group(2).strip()
        clauses.append(['case_when', ['pattern', parse_value_with_variables(pattern)], ['body', parse_value_with_variables(cmd)]])
    return ['shell_case', ['value', parse_value_with_variables(value)]] + clauses


def parse_shell_construct(command: str):
    node = parse_if_block(command)
    if node:
        return node
    node = parse_for_loop(command)
    if node:
        return node
    node = parse_while_loop(command)
    if node:
        return node
    node = parse_case_block(command)
    if node:
        return node
    return None


def handle_run(y, x, workdir: str):
    """
    Enhanced RUN/CMD/ENTRYPOINT parser with shell construct analysis and script detection.
    """
    logical_segments = split_run_commands_logical(y)
    # Pass 1: collect chmod +x targets within this instruction
    chmod_exec_paths = set()
    for seg in logical_segments or [{'command': y, 'separator': None}]:
        toks = _tokenize_shell_command(seg['command'])
        if toks and toks[0] == 'chmod' and len(toks) >= 3 and ('+x' in toks[1] or 'a+x' in toks[1]):
            for path_tok in toks[2:]:
                if path_tok.startswith('-'):
                    continue
                abs_path = _resolve_path(workdir, path_tok)
                chmod_exec_paths.add(abs_path)

    if not logical_segments:
        node = parse_shell_construct(y.strip())
        if node:
            return [x, node]
        # Attempt script detection on single segment
        toks = _tokenize_shell_command(y.strip())
        script_node = _detect_script_invocation(toks, workdir, chmod_exec_paths)
        if script_node:
            return [x, ['command_segment', script_node]]
        parsed_command = parse_value_with_variables(y)
        return [x, ['command', parsed_command]]

    result = [x]
    for seg in logical_segments:
        seg_text = seg['command']
        node = parse_shell_construct(seg_text)
        if not node:
            # Try script detection per segment
            toks = _tokenize_shell_command(seg_text)
            script_node = _detect_script_invocation(toks, workdir, chmod_exec_paths)
            if script_node:
                segment = ['command_segment', script_node]
            else:
                inner_segments = split_run_commands(seg_text)
                if len(inner_segments) <= 1:
                    segment = ['command_segment', ['command', parse_value_with_variables(seg_text)]]
                else:
                    for inner in inner_segments:
                        inner_node = ['command_segment', ['command', parse_value_with_variables(inner['command'])]]
                        if inner['separator']:
                            inner_node.append(['separator', [inner['separator']]])
                            inner_node.append(['type', [inner['type']]])
                        result.append(inner_node)
                    if seg['separator']:
                        result[-1].append(['separator', [seg['separator']]])
                        result[-1].append(['type', [seg['type']]])
                    continue
        else:
            segment = ['command_segment', node]
        if seg['separator']:
            segment.append(['separator', [seg['separator']]])
            segment.append(['type', [seg['type']]])
        result.append(segment)
    return result


def normalize_path(path):
    """
    Normalize a file path
    
    Args:
        path (str): Path to normalize
        
    Returns:
        str: Normalized path
    """
    return str(Path(path).resolve())


def handle_copy_add(y, x, stage_aliases, current_stage_number, repo_path, dockerfile_path_local):
    """
    Parse COPY/ADD instruction with enhanced variable support
    
    Handles formats like:
    - COPY source dest
    - COPY ["source", "dest"]
    - ADD source dest
    
    Args:
        y (str): COPY/ADD instruction value
        x (str): Instruction name ('COPY' or 'ADD')
        stage_aliases (dict): Mapping of stage aliases to numbers
        current_stage_number (int): Current stage number
        repo_path (str): Repository path
        dockerfile_path_local (str): Local Dockerfile path
        
    Returns:
        list: Structured representation of copy/add operation with variable metadata
    """
    # Check if it's JSON array format
    if y.startswith('[') and y.endswith(']'):
        try:
            # Parse JSON array
            import json
            parts = json.loads(y)
            if isinstance(parts, list) and len(parts) >= 2:
                source = parts[0]
                destination = parts[1]
                # Parse with variable support
                parsed_source = parse_value_with_variables(str(source))
                parsed_destination = parse_value_with_variables(str(destination))
                return [x, ['source', parsed_source], ['destination', parsed_destination]]
        except json.JSONDecodeError:
            pass
    
    # Shell format - split by whitespace
    parts = y.split()
    if len(parts) >= 2:
        source_raw = parts[0]
        destination = parts[1]

        # Expand brace patterns first
        brace_expanded = []
        for pat in _brace_expand(source_raw):
            brace_expanded.append(pat)

        # Resolve repo paths for each expanded source
        resolved_sources = []
        base_dir = str(Path(dockerfile_path_local).parent)
        for src in brace_expanded:
            if src == '.':
                resolved_sources.append(src)
                continue
            # If absolute path-like, keep as is relative to repo root
            resolved_sources.append(src)

        # Glob expansion
        matched_files = []
        import glob as _glob
        for src in resolved_sources:
            if src == '.':
                # include all files under base_dir
                for dirpath, _, filenames in os.walk(base_dir):
                    for fn in filenames:
                        matched_files.append(os.path.join(dirpath, fn))
            else:
                pattern = os.path.join(repo_path, src)
                hits = _glob.glob(pattern)
                if hits:
                    matched_files.extend(hits)
                else:
                    # treat as literal if no match
                    matched_files.append(os.path.join(repo_path, src))

        # Build mapping and content summary
        files_summary = []
        for fpath in matched_files:
            if os.path.isdir(fpath):
                # copy directory: map contained files one level deep (heuristic)
                for dirpath, _, filenames in os.walk(fpath):
                    for fn in filenames:
                        repo_abs = os.path.join(dirpath, fn).replace('\\', '/')
                        cont_abs = os.path.join(destination, fn).replace('\\', '/')
                        container_to_repo_map[cont_abs] = repo_abs
                        ftype, fsize = _determine_content_type(repo_abs)
                        files_summary.append(['file', ['container_path', [cont_abs]], ['repo_path', [repo_abs]], ['type', [ftype]], ['size', [fsize]]])
            else:
                repo_abs = fpath.replace('\\', '/')
                cont_abs = os.path.join(destination, os.path.basename(fpath)).replace('\\', '/')
                container_to_repo_map[cont_abs] = repo_abs
                ftype, fsize = _determine_content_type(repo_abs)
                files_summary.append(['file', ['container_path', [cont_abs]], ['repo_path', [repo_abs]], ['type', [ftype]], ['size', [fsize]]])

        # Parse with variable support
        parsed_source = parse_value_with_variables(source_raw)
        parsed_destination = parse_value_with_variables(destination)

        node = [x, ['source', parsed_source], ['destination', parsed_destination]]
        if files_summary:
            files_node = ['files']
            files_node.extend(files_summary)
            node.append(files_node)
        return node
    
    return [x, ['error', ['Invalid COPY/ADD format']]]


def EAST(x, temp_repo_path, dockerfile_path_local, build_args: dict = None):
    """
    Enhanced EAST parser that uses improved variable detection and interpretation
    
    Args:
        x (str): Dockerfile content
        temp_repo_path (str): Temporary repository path
        dockerfile_path_local (str): Local Dockerfile path
        
    Returns:
        list: Enhanced abstract syntax tree with variable metadata
    """
    # Parse using dockerfile-parse library
    parser = DockerfileParser()
    parser.content = x
    
    # Get all instructions
    instructions = parser.structure
    
    # Initialize result structure
    result = ['stage']
    stage_number = 0
    stage_aliases = {}
    workdir_current = '/'
    
    global current_build_args
    current_build_args = {}
    if build_args and isinstance(build_args, dict):
        current_build_args.update(build_args)
    else:
        # Backward-compatible env fallback
        build_args_env = os.environ.get('DOCKER_BUILD_ARGS_JSON')
        if build_args_env:
            try:
                current_build_args.update(json.loads(build_args_env))
            except Exception:
                pass

    for instruction in instructions:
        instruction_type = instruction['instruction']
        instruction_value = instruction['value']
        
        if instruction_type == 'FROM':
            stage_number += 1
            result.append(handle_from(instruction_value, instruction_type, stage_number))
            
            # Track stage aliases
            alias = parse_alias(instruction_value)
            if alias:
                stage_aliases[alias] = stage_number
                
        elif instruction_type == 'ENV':
            result.append(handle_env(instruction_value, instruction_type))
            
        elif instruction_type == 'ARG':
            result.append(handle_arg(instruction_value, instruction_type))
            
        elif instruction_type == 'EXPOSE':
            result.append(handle_expose(instruction_value, instruction_type))
            
        elif instruction_type == 'USER':
            result.append(handle_user(instruction_value, instruction_type))
            
        elif instruction_type in ['RUN', 'CMD', 'ENTRYPOINT']:
            result.append(handle_run(instruction_value, instruction_type, workdir_current))
            
        elif instruction_type in ['COPY', 'ADD']:
            result.append(handle_copy_add(instruction_value, instruction_type, 
                                       stage_aliases, stage_number, temp_repo_path, dockerfile_path_local))
            
        elif instruction_type == 'WORKDIR':
            # Parse workdir with variable support and update current
            parsed_workdir = parse_value_with_variables(instruction_value)
            result.append([instruction_type, ['path', parsed_workdir]])
            workdir_current = instruction_value.strip() or '/'
            
        elif instruction_type == 'VOLUME':
            # Parse volume with variable support
            parsed_volume = parse_value_with_variables(instruction_value)
            result.append([instruction_type, ['path', parsed_volume]])
            
        elif instruction_type == 'LABEL':
            # Parse label with variable support
            parsed_label = parse_value_with_variables(instruction_value)
            result.append([instruction_type, ['label', parsed_label]])
            
        elif instruction_type == 'STOPSIGNAL':
            # Parse signal with variable support
            parsed_signal = parse_value_with_variables(instruction_value)
            result.append([instruction_type, ['signal', parsed_signal]])
            
        elif instruction_type == 'SHELL':
            # Parse shell with variable support
            parsed_shell = parse_value_with_variables(instruction_value)
            result.append([instruction_type, ['shell', parsed_shell]])
            
        elif instruction_type == 'HEALTHCHECK':
            # Parse healthcheck with variable support
            parsed_healthcheck = parse_value_with_variables(instruction_value)
            result.append([instruction_type, ['healthcheck', parsed_healthcheck]])
            
        else:
            # Unknown instruction - parse with variable support
            parsed_value = parse_value_with_variables(instruction_value)
            result.append([instruction_type, ['value', parsed_value]])
    
    return result


def create_node(data):
    """
    Create a tree node from data
    
    Args:
        data: Node data
        
    Returns:
        Node: Tree node
    """
    if isinstance(data, list) and len(data) > 0:
        name = str(data[0])
        children = []
        for child in data[1:]:
            if isinstance(child, list):
                children.append(create_node(child))
        return Node(name, children=children)
    else:
        return Node(str(data))


def json_to_tree(json_list):
    """
    Convert JSON list to tree structure
    
    Args:
        json_list (list): JSON list representation
        
    Returns:
        Node: Root node of the tree
    """
    return create_node(json_list)


def get_EAST(dockerfile_content, temp_repo_path, dockerfile_path_local, build_args: dict = None):
    """
    Get enhanced EAST tree from Dockerfile content
    
    Args:
        dockerfile_content (str): Dockerfile content
        temp_repo_path (str): Temporary repository path
        dockerfile_path_local (str): Local Dockerfile path
        
    Returns:
        Node: Enhanced abstract syntax tree with variable metadata
    """
    east_data = EAST(dockerfile_content, temp_repo_path, dockerfile_path_local, build_args=build_args)
    return json_to_tree(east_data) 