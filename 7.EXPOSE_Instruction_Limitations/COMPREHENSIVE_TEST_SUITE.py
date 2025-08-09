#!/usr/bin/env python3
"""
Compares EXPOSE validation: invalid ports and protocols flagged in enhanced parser.
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
    print("\n== EXPOSE LIMITATIONS - COMPARISON ==")
    df = """FROM ubuntu:latest
EXPOSE 99999
EXPOSE 80/invalid
EXPOSE -1
EXPOSE 65536
EXPOSE 80/tcp 443/udp
"""
    print("\nTest Dockerfile:\n```dockerfile\n" + df + "\n```")
    print("Explanation: Enhanced parser annotates port/protocol issues under validation.")
    t_old = get_EAST_old(df, "/tmp", "/tmp/Dockerfile")
    show("OLD VERSION", t_old)
    t_new = get_EAST_enhanced(df, "/tmp", "/tmp/Dockerfile")
    show("ENHANCED VERSION", t_new)

if __name__ == '__main__':
    main()

