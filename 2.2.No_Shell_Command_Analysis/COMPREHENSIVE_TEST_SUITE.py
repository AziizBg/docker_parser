#!/usr/bin/env python3
"""
Comprehensive Test Suite for Limitation 2.2: No Shell Command Analysis

Compares original parser vs enhanced shell-aware parser for RUN constructs:
- for, if/elif/else, while, case
- mixed with separators and variables
"""

import sys
import os
from importlib.machinery import SourceFileLoader
from anytree import RenderTree

# Add repo root to path
ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
sys.path.insert(0, ROOT)

from Dockerfile_EAST import get_EAST as get_EAST_old

# Dynamically load enhanced module by file path (directory isn't a valid package name)
ENHANCED_PATH = os.path.join(ROOT, '2.2.No_Shell_Command_Analysis', 'Dockerfile_EAST_enhanced_shell.py')
enhanced_mod = SourceFileLoader('enhanced_shell', ENHANCED_PATH).load_module()
get_EAST_enhanced = enhanced_mod.get_EAST


def print_section(title: str):
    print("\n" + "=" * 80)
    print(f" {title}")
    print("=" * 80)


def find_run_nodes(root):
    results = []
    def dfs(node):
        if getattr(node, 'name', '') == 'RUN':
            results.append(node)
        for child in getattr(node, 'children', []):
            dfs(child)
    dfs(root)
    return results


def print_tree(node, indent=0, max_depth=6):
    # Bounded pretty tree print
    spacer = '  ' * indent
    print(f"{spacer}- {node.name}")
    if indent >= max_depth:
        return
    for child in node.children:
        print_tree(child, indent + 1, max_depth)


def run_case(title: str, dockerfile: str):
    print(f"\n--- {title} ---")
    print("Dockerfile:\n" + dockerfile)

    print("\nOLD VERSION:")
    try:
        t1 = get_EAST_old(dockerfile, "/tmp", "/tmp/Dockerfile")
        runs = find_run_nodes(t1)
        if not runs:
            print("  (no RUN nodes found)")
        for idx, rn in enumerate(runs, 1):
            print(f"  RUN {idx} structure:")
            print_tree(rn)
    except Exception as e:
        print(f"Old parser error: {e}")

    print("\nENHANCED VERSION:")
    try:
        t2 = get_EAST_enhanced(dockerfile, "/tmp", "/tmp/Dockerfile")
        runs2 = find_run_nodes(t2)
        if not runs2:
            print("  (no RUN nodes found)")
        for idx, rn in enumerate(runs2, 1):
            print(f"  RUN {idx} structure:")
            print_tree(rn)
    except Exception as e:
        print(f"Enhanced parser error: {e}")


def main():
    print_section("Limitation 2.2 - Shell Command Analysis")

    run_case(
        "for loop",
        """FROM ubuntu:latest
RUN for i in 1 2 3; do echo $i; done
""",
    )

    run_case(
        "if/elif/else",
        """FROM ubuntu:latest
RUN if [ -f file.txt ]; then echo exists; elif [ -d /tmp ]; then echo tmp; else echo none; fi
""",
    )

    run_case(
        "while loop",
        """FROM ubuntu:latest
RUN while grep -q foo file.txt; do echo loop; done
""",
    )

    run_case(
        "case statement",
        """FROM ubuntu:latest
RUN case $VAR in "a") echo A ;; "b") echo B ;; *) echo other ;; esac
""",
    )

    run_case(
        "mixed with separators",
        """FROM ubuntu:latest
RUN if [ -f a ]; then echo A; fi && for i in 1 2; do echo $i; done || echo fail
""",
    )

    run_case(
        "variables inside constructs",
        """FROM ubuntu:latest
ARG NAME=world
RUN if [ -n "$NAME" ]; then echo "Hi $NAME"; else echo none; fi
""",
    )


if __name__ == "__main__":
    main()