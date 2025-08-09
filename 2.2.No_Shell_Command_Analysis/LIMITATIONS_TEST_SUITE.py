#!/usr/bin/env python3
"""
Limitations Test Suite for Limitation 2.2 Enhanced Shell Parser

Demonstrates current shortcomings:
- L1: Trailing chained segments after a parsed construct are dropped
- L2: Nested constructs inside bodies are not parsed recursively
- L3: While/for constructs with redirection or uncommon formatting may not match
- L4: Mixed constructs chained (construct && construct || simple) partly parsed
"""

import sys
import os
from importlib.machinery import SourceFileLoader

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
sys.path.insert(0, ROOT)

from Dockerfile_EAST import get_EAST as get_EAST_old

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


def print_tree(node, indent=0, max_depth=8):
    spacer = '  ' * indent
    print(f"{spacer}- {node.name}")
    if indent >= max_depth:
        return
    for child in node.children:
        print_tree(child, indent + 1, max_depth)


def show(title: str, dockerfile: str):
    print(f"\n--- {title} ---")
    print("Dockerfile:\n" + dockerfile)

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

    print("\nNOTE: Observed limitation illustrated above.\n")


def main():
    print_section("Enhanced Shell Parser — Known Limitations Showcase")

    # L1: Trailing segments after construct are dropped (if ...; fi && for ... || echo ...)
    show(
        "L1: Trailing chained segments after a construct",
        """FROM ubuntu:latest
RUN if [ -f a ]; then echo A; fi && for i in 1 2; do echo $i; done || echo fail
""",
    )

    # L2: Nested constructs inside a body are not parsed (if inside for)
    show(
        "L2: Nested constructs inside for body not parsed",
        """FROM ubuntu:latest
RUN for i in 1 2; do if [ "$i" = "1" ]; then echo one; else echo other; fi; done
""",
    )

    # L3: While with redirection after done doesn't match regex
    show(
        "L3: While with input redirection",
        """FROM ubuntu:latest
RUN while read line; do echo $line; done < input.txt
""",
    )

    # L4: Multiple constructs chained
    show(
        "L4: Construct followed by construct",
        """FROM ubuntu:latest
RUN for i in a b; do echo $i; done && while grep -q a file; do echo loop; done
""",
    )

if __name__ == "__main__":
    main()