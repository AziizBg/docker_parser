#!/usr/bin/env python3
"""
Comprehensive Test Suite for ENV Instruction Limitations (5.x)

Compares old vs enhanced parser for multi-line ENV and value validation.
"""

import sys
import os
from pathlib import Path

WORKSPACE = str(Path(__file__).resolve().parents[1])
sys.path.append(WORKSPACE)

from Dockerfile_EAST_old import get_EAST as get_EAST_old
from Dockerfile_EAST import get_EAST as get_EAST_enhanced


def print_separator(title):
    print("\n" + "=" * 80)
    print(f" {title}")
    print("=" * 80)


def print_test_case(title, dockerfile_content):
    print(f"\n--- Test Case: {title} ---")
    print("Dockerfile Content:")
    print(f"```dockerfile\n{dockerfile_content}\n```")


def summarize_env(tree, label):
    print(f"\n{label} Analysis:")
    def dfs(node):
        out = []
        if hasattr(node, 'name') and node.name == 'ENV':
            out.append(node)
        for ch in getattr(node, 'children', []):
            out.extend(dfs(ch))
        return out
    env_nodes = dfs(tree)
    if not env_nodes:
        print("  ❌ No ENV nodes found")
        return
    for idx, env in enumerate(env_nodes, 1):
        print(f"  ENV Node {idx}:")
        # Print pairs and validation metadata
        def walk(n, depth=4):
            if hasattr(n, 'name'):
                print(" " * depth + f"- {n.name}")
                for c in getattr(n, 'children', []):
                    walk(c, depth + 2)
        walk(env)


def print_full_tree(label, tree):
    print(f"\n{label} Full Tree:")
    try:
        from anytree import RenderTree
        for pre, _, node in RenderTree(tree):
            print(f"  {pre}{node.name}")
    except Exception:
        def dfs(n, indent=2):
            if hasattr(n, 'name'):
                print(" " * indent + str(n.name))
                for ch in getattr(n, 'children', []):
                    dfs(ch, indent + 2)
        dfs(tree)


EXPLANATIONS = {
    "Single-line values": "Checks boolean normalization, port typing, and path segmentation on a single line.",
    "Multi-line continuation": "Ensures backslash-continued ENV lines are merged and parsed into separate pairs.",
    "Mixed formats": "Handles both KEY value and KEY=value formats; flags potential secrets.",
    "Validation checks": "Detects YES as boolean true and flags invalid port range."
}


def compare(title, dockerfile_content):
    print_test_case(title, dockerfile_content)
    explanation = EXPLANATIONS.get(title)
    if explanation:
        print(f"Explanation: {explanation}")
    try:
        t_old = get_EAST_old(dockerfile_content, "/tmp", "/tmp/Dockerfile")
        summarize_env(t_old, "OLD VERSION")
        print_full_tree("OLD VERSION", t_old)
        t_new = get_EAST_enhanced(dockerfile_content, "/tmp", "/tmp/Dockerfile")
        summarize_env(t_new, "ENHANCED VERSION")
        print_full_tree("ENHANCED VERSION", t_new)
    except Exception as e:
        print(f"❌ Error: {e}")


def main():
    print_separator("ENV LIMITATIONS - COMPREHENSIVE TEST SUITE")

    # 1. Simple single-line values
    compare("Single-line values", """FROM ubuntu:latest
ENV DEBUG=true PORT=8080 PATH=/usr/bin:/usr/local/bin
""")

    # 2. Multi-line continuation
    compare("Multi-line continuation", """FROM ubuntu:latest
ENV VAR1=value1 \
    VAR2=value2 \
    VAR3=value3
""")

    # 3. Mixed format
    compare("Mixed formats", """FROM ubuntu:latest
ENV NAME value
ENV SECRET_KEY=mysecret123
ENV AWS_TOKEN=AbCDefGh1234567
""")

    # 4. Invalid port and boolean normalization
    compare("Validation checks", """FROM ubuntu:latest
ENV ENABLED=YES PORT=70000
""")


if __name__ == '__main__':
    main()

