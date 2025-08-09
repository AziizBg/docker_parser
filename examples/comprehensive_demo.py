#!/usr/bin/env python3
"""
Comprehensive demo for Dockerfile EAST parser.

This script:
- Prepares a temporary repository with files to exercise COPY/ADD mapping,
  file-type detection, and script content extraction.
- Defines a multi-stage Dockerfile covering ARG/ENV, complex RUN separators,
  shell constructs, JSON-array RUN, COPY/ADD, EXPOSE, USER, WORKDIR, CMD.
- Runs the parser and prints both the rendered anytree and the JSON EAST.
"""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path

from anytree import RenderTree

# Ensure repo root is importable
WORKSPACE_ROOT = str(Path(__file__).resolve().parents[1])
import sys

if WORKSPACE_ROOT not in sys.path:
    sys.path.insert(0, WORKSPACE_ROOT)

from Dockerfile_EAST import get_EAST, EAST  # type: ignore


DOCKERFILE_CONTENT = """\
FROM node:18 AS builder
ARG NODE_ENV
ARG BUILD_DATE
WORKDIR /app
COPY package.json package-lock.json /app/
# Mixed separators and grouping
RUN npm ci && npm run build || (echo "build failed" && exit 1)
COPY scripts/init.sh /usr/local/bin/init.sh
COPY scripts/run.py /usr/local/bin/run.py
RUN chmod +x /usr/local/bin/init.sh && /usr/local/bin/init.sh arg1 & echo background
ENV PATH=${PATH}:/app/node_modules/.bin \
    DEBUG=${DEBUG:-false} \
    PREFIX=${PREFIX:+/opt} \
    NESTED=${OUTER:-${INNER:-fallback}}
EXPOSE 3000/tcp 9229
RUN ["bash", "-lc", "echo json form"]

FROM nginx:alpine AS runtime
COPY --from=builder /app/dist /usr/share/nginx/html
USER 1001:1001
RUN echo "starting"; for i in 1 2 3; do echo $i; done; if [ -f /etc/alpine-release ]; then echo alpine; fi
EXPOSE 80
ARG CHANNEL=stable
ENV VERSION=${VERSION:-1.0.0}
WORKDIR /srv
COPY configs/nginx.conf /etc/nginx/nginx.conf
COPY src/{a,b}.txt /data/
ADD assets/data.bin /opt/data.bin
RUN python /usr/local/bin/run.py | tee /tmp/out.txt
CMD ["nginx", "-g", "daemon off;"]
"""


def prepare_demo_repository(temporary_repo_path: Path) -> None:
    scripts_path = temporary_repo_path / "scripts"
    configs_path = temporary_repo_path / "configs"
    src_path = temporary_repo_path / "src"
    assets_path = temporary_repo_path / "assets"

    scripts_path.mkdir(parents=True, exist_ok=True)
    configs_path.mkdir(parents=True, exist_ok=True)
    src_path.mkdir(parents=True, exist_ok=True)
    assets_path.mkdir(parents=True, exist_ok=True)

    (temporary_repo_path / "package.json").write_text("{}\n", encoding="utf-8")
    (temporary_repo_path / "package-lock.json").write_text("{}\n", encoding="utf-8")

    (scripts_path / "init.sh").write_text(
        """#!/usr/bin/env bash
set -euo pipefail
echo "init running: $@"
""",
        encoding="utf-8",
    )

    (scripts_path / "run.py").write_text(
        """#!/usr/bin/env python3
import sys
print("run.py executed", " ".join(sys.argv[1:]))
""",
        encoding="utf-8",
    )

    (configs_path / "nginx.conf").write_text("events {} http {}\n", encoding="utf-8")
    (src_path / "a.txt").write_text("A\n", encoding="utf-8")
    (src_path / "b.txt").write_text("B\n", encoding="utf-8")

    # Binary file for ADD to exercise binary detection
    (assets_path / "data.bin").write_bytes(b"\x00\x01\x02\x03\x04\x05\x00\x00")


def main() -> None:
    # Prefer explicit build args rather than env for reproducibility
    build_args = {
        "NODE_ENV": "production",
        "BUILD_DATE": "2025-01-01",
        "VERSION": "2.0.0",
    }

    with tempfile.TemporaryDirectory() as temporary_directory:
        repo_root_path = Path(temporary_directory)
        prepare_demo_repository(repo_root_path)
        dockerfile_path = str(repo_root_path / "Dockerfile")

        # Render anytree.Node for human inspection
        tree = get_EAST(
            DOCKERFILE_CONTENT,
            str(repo_root_path),
            dockerfile_path,
            build_args=build_args,
        )

        print("\n=== Rendered Tree ===")
        rendered_lines = []
        for prefix, _, node in RenderTree(tree):
            rendered_lines.append(f"{prefix}{node.name}")
        print("\n".join(rendered_lines))

        # Save outputs to files under examples/output
        output_dir = Path(__file__).resolve().parent / "output"
        output_dir.mkdir(parents=True, exist_ok=True)
        tree_out = output_dir / "rendered_tree.txt"
        tree_out.write_text("\n".join(rendered_lines) + "\n", encoding="utf-8")

        # Obtain EAST list for JSON serialization
        east_list = EAST(
            DOCKERFILE_CONTENT,
            str(repo_root_path),
            dockerfile_path,
            build_args=build_args,
        )

        print("\n=== JSON EAST ===")
        json_text = json.dumps(east_list, indent=2)
        print(json_text)

        json_out = output_dir / "east.json"
        json_out.write_text(json_text + "\n", encoding="utf-8")

        print(f"\nSaved rendered tree to: {tree_out}")
        print(f"Saved JSON EAST to:      {json_out}")


if __name__ == "__main__":
    main()

