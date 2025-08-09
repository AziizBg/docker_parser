#!/usr/bin/env python3
"""
Compares ARG handling: old vs enhanced (build-time resolution via env JSON).
Set DOCKER_BUILD_ARGS_JSON='{"VERSION":"1.0","BUILD_DATE":"2024-01-01"}' before run.
"""
import os, sys
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
    print("\n== ARG LIMITATIONS - COMPARISON ==")
    df = """FROM ubuntu:latest
ARG VERSION
ARG BUILD_DATE
ARG CHANNEL=stable
"""
    print("\nTest Dockerfile:\n```dockerfile\n" + df + "\n```")
    print("Explanation: Resolves unassigned ARGs from DOCKER_BUILD_ARGS_JSON and marks sources.")
    # Old behavior
    t_old = get_EAST_old(df, "/tmp", "/tmp/Dockerfile")
    show("OLD VERSION", t_old)
    # Enhanced with explicit build_args parameter (preferred for end users)
    build_args = {"VERSION": "1.0", "BUILD_DATE": "2024-01-01"}
    t_new = get_EAST_enhanced(df, "/tmp", "/tmp/Dockerfile", build_args=build_args)
    show("ENHANCED VERSION", t_new)

if __name__ == '__main__':
    main()

