#!/usr/bin/env python3
"""
Comprehensive Test Suite for Script Detection (Limitation 2.3)

Compares the original parser vs the enhanced script-detection parser.

Scenarios covered:
1. COPY of extensionless script + chmod + execute
2. Explicit interpreter invocation (bash /path/script.sh)
3. Direct execution with arguments (/path/script.sh arg1 arg2)
4. Relative path execution with WORKDIR (./script.sh)
5. Non-script command fallback
"""

import sys
import os
from pathlib import Path

# Allow importing from workspace root
WORKSPACE = str(Path(__file__).resolve().parents[1])
sys.path.append(WORKSPACE)
sys.path.append(str(Path(__file__).resolve().parent))

from Dockerfile_EAST_old import get_EAST as get_EAST_old
from Dockerfile_EAST import get_EAST as get_EAST_enhanced


def print_separator(title):
    print("\n" + "=" * 80)
    print(f" {title}")
    print("=" * 80)


def print_test_case(title, content):
    print(f"\n--- Test Case: {title} ---")
    print("Dockerfile Content:")
    print(f"```dockerfile\n{content}\n```")


def summarize_scripts(tree, label):
    print(f"\n{label} Analysis:")
    def dfs(node, path=""):
        paths = []
        if hasattr(node, 'name'):
            cur = f"{path}/{node.name}" if path else node.name
            if node.name == 'script':
                info = {"path": None, "args": None}
                for ch in node.children:
                    if getattr(ch, 'name', None) == 'path' and ch.children:
                        info["path"] = getattr(ch.children[0], 'name', '')
                    if getattr(ch, 'name', None) == 'args' and ch.children:
                        info["args"] = getattr(ch.children[0], 'children', [None])[0].name if ch.children[0].children else None
                paths.append((cur, info))
            for ch in node.children:
                paths.extend(dfs(ch, cur))
        return paths
    scripts = dfs(tree)
    if not scripts:
        print("  ❌ No script nodes detected")
    for i, (p, info) in enumerate(scripts, 1):
        print(f"  Script {i}: path={info['path']} args={info['args']}")


def compare(title, dockerfile_content):
    print_test_case(title, dockerfile_content)
    try:
        t_old = get_EAST_old(dockerfile_content, "/tmp", "/tmp/Dockerfile")
        summarize_scripts(t_old, "OLD VERSION")
        t_new = get_EAST_enhanced(dockerfile_content, "/tmp", "/tmp/Dockerfile")
        summarize_scripts(t_new, "ENHANCED VERSION")
    except Exception as e:
        print(f"❌ Error: {e}")


def main():
    print_separator("SCRIPT DETECTION LIMITATIONS - COMPREHENSIVE TEST SUITE")

    compare(
        "Extensionless script via chmod + execute",
        """FROM ubuntu:latest
COPY setup /tmp/
RUN chmod +x /tmp/setup && /tmp/setup
"""
    )

    compare(
        "Explicit interpreter invocation",
        """FROM ubuntu:latest
RUN bash /tmp/script.sh
"""
    )

    compare(
        "Direct execution with args",
        """FROM ubuntu:latest
RUN /tmp/script.sh arg1 arg2
"""
    )

    compare(
        "Relative path script with WORKDIR",
        """FROM ubuntu:latest
WORKDIR /app
RUN ./script.sh
"""
    )

    compare(
        "Non-script fallback",
        """FROM ubuntu:latest
RUN echo "hello"
"""
    )


if __name__ == '__main__':
    main()

