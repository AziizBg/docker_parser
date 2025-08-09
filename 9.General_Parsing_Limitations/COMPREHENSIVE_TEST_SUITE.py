#!/usr/bin/env python3
"""
Compares error recovery for malformed Dockerfile constructs (old vs enhanced).
"""
import sys
from pathlib import Path
WORKSPACE = str(Path(__file__).resolve().parents[1])
sys.path.append(WORKSPACE)
from Dockerfile_EAST_old import get_EAST as get_EAST_old
from Dockerfile_EAST import get_EAST as get_EAST_enhanced

def show(label, tree):
    print(f"\n{label}:")
    try:
        from anytree import RenderTree
        for pre, _, node in RenderTree(tree):
            print(f"  {pre}{node.name}")
    except Exception:
        pass

def main():
    print("\n== GENERAL PARSING LIMITATIONS - COMPARISON ==")
    df = """FROM ubuntu:latest
ENV KEY=
RUN 
COPY 
FROM 
"""
    print("\nTest Dockerfile:\n```dockerfile\n" + df + "\n```")
    print("Explanation: Enhanced parser emits error nodes (empty_env, empty_command, incomplete_copy_add, missing_image).")
    try:
        t_old = get_EAST_old(df, "/tmp", "/tmp/Dockerfile")
        show("OLD VERSION", t_old)
    except Exception as e:
        print(f"\nOLD VERSION: ❌ Error: {e}")
    try:
        t_new = get_EAST_enhanced(df, "/tmp", "/tmp/Dockerfile")
        show("ENHANCED VERSION", t_new)
    except Exception as e:
        print(f"\nENHANCED VERSION: ❌ Error: {e}")

if __name__ == '__main__':
    main()

