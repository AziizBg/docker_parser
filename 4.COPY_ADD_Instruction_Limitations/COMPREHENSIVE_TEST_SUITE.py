#!/usr/bin/env python3
"""
Comprehensive Test Suite for COPY/ADD Instruction Limitations (4.x)

Compares original vs enhanced behavior for glob/brace patterns and content analysis.
"""

import sys
import os
from pathlib import Path

WORKSPACE = str(Path(__file__).resolve().parents[1])
sys.path.append(WORKSPACE)

from Dockerfile_EAST_old import get_EAST as get_EAST_old
from Dockerfile_EAST import get_EAST as get_EAST_enhanced
import tempfile
import shutil


def print_separator(title):
    print("\n" + "=" * 80)
    print(f" {title}")
    print("=" * 80)


def print_test_case(title, dockerfile_content):
    print(f"\n--- Test Case: {title} ---")
    print("Dockerfile Content:")
    print(f"```dockerfile\n{dockerfile_content}\n```")


def summarize_copy_nodes(tree, label):
    print(f"\n{label} Analysis:")
    def dfs(node, path=""):
        found = []
        if hasattr(node, 'name'):
            cur = f"{path}/{node.name}" if path else node.name
            if node.name in ('COPY', 'ADD'):
                found.append(node)
            for ch in node.children:
                found.extend(dfs(ch, cur))
        return found
    nodes = dfs(tree)
    if not nodes:
        print("  ❌ No COPY/ADD nodes found")
        return
    for idx, n in enumerate(nodes, 1):
        print(f"  Node {idx}:")
        # list files summaries if present
        def find_files(nn):
            if nn.name == 'files':
                return nn
            for c in nn.children:
                res = find_files(c)
                if res:
                    return res
            return None
        files_node = find_files(n)
        if not files_node:
            print("    files: (none)")
        else:
            cnt = 0
            listings = []
            for f in files_node.children:
                if getattr(f, 'name', '') == 'file':
                    cnt += 1
                    info = {"container_path": None, "type": None}
                    for ch in f.children:
                        if getattr(ch, 'name', '') == 'container_path' and ch.children:
                            info['container_path'] = ch.children[0].name
                        if getattr(ch, 'name', '') == 'type' and ch.children:
                            info['type'] = ch.children[0].name
                    listings.append(info)
            print(f"    files: {cnt}")
            for i, it in enumerate(listings[:5], 1):
                print(f"      {i}. {it['container_path']} ({it['type']})")


def print_full_tree(label, tree):
    print(f"\n{label} Full Tree:")
    try:
        from anytree import RenderTree
        for pre, _, node in RenderTree(tree):
            print(f"  {pre}{node.name}")
    except Exception:
        # Fallback simple DFS
        def dfs(n, indent=2):
            if hasattr(n, 'name'):
                print(" " * indent + str(n.name))
                for ch in getattr(n, 'children', []):
                    dfs(ch, indent + 2)
        dfs(tree)


def compare(title, dockerfile_content, repo_root, dockerfile_path):
    print_test_case(title, dockerfile_content)
    try:
        t_old = get_EAST_old(dockerfile_content, repo_root, dockerfile_path)
        summarize_copy_nodes(t_old, "OLD VERSION")
        print_full_tree("OLD VERSION", t_old)
        t_new = get_EAST_enhanced(dockerfile_content, repo_root, dockerfile_path)
        summarize_copy_nodes(t_new, "ENHANCED VERSION")
        print_full_tree("ENHANCED VERSION", t_new)
    except Exception as e:
        print(f"❌ Error: {e}")


def main():
    print_separator("COPY/ADD LIMITATIONS - COMPREHENSIVE TEST SUITE")
    # Create a temporary repo with files to match patterns
    tmpdir = tempfile.mkdtemp(prefix='copy_add_demo_')
    try:
        # Layout
        os.makedirs(os.path.join(tmpdir, 'src'), exist_ok=True)
        # Text files
        for name in ['a.txt', 'b.txt', 'file1.txt', 'file2.txt', 'c.txt']:
            with open(os.path.join(tmpdir, 'src', name), 'w') as f:
                f.write(f"content {name}\n")
        # Python files
        for name in ['x.py', 'y.py']:
            with open(os.path.join(tmpdir, 'src', name), 'w') as f:
                f.write("print('ok')\n")
        # Root text files for *.txt at repo root
        with open(os.path.join(tmpdir, 'root1.txt'), 'w') as f:
            f.write("root1\n")
        with open(os.path.join(tmpdir, 'root2.txt'), 'w') as f:
            f.write("root2\n")
        # JSON and .env
        with open(os.path.join(tmpdir, 'config.json'), 'w') as f:
            f.write('{"key": "value"}')
        with open(os.path.join(tmpdir, '.env'), 'w') as f:
            f.write('SECRET=1\n')

        dockerfile_path = os.path.join(tmpdir, 'Dockerfile')

        compare("Glob patterns (*.txt)", """FROM ubuntu:latest
COPY *.txt /dest/
""", tmpdir, dockerfile_path)

        compare("Dir glob (src/*.py)", """FROM ubuntu:latest
COPY src/*.py /dest/
""", tmpdir, dockerfile_path)

        compare("Brace expansion", """FROM ubuntu:latest
COPY src/{file1,file2}.txt /dest/
""", tmpdir, dockerfile_path)

        compare("Single char wildcard and class", """FROM ubuntu:latest
COPY src/?.txt /dest/
COPY src/[a-z]*.txt /dest/
""", tmpdir, dockerfile_path)

        compare("Content summary (json, env)", """FROM ubuntu:latest
COPY config.json /app/
COPY .env /app/
""", tmpdir, dockerfile_path)
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


if __name__ == '__main__':
    main()

