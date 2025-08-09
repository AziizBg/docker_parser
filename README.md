## Dockerfile EAST Parser

An enhanced parser that converts Dockerfiles into an EAST (Enhanced Abstract Syntax Tree) representation for deeper analysis. It focuses on structured extraction of instructions, variables, scripts, ports, users, and multi‑stage build relationships.

### Key Features
- **Multi‑stage builds**: Tracks stages and basic alias relationships
- **ENV/ARG parsing**: Extracts variables with metadata; supports complex Docker variable patterns
- **RUN parsing**: Splits commands on complex separators (e.g., `;`, `&&`, `||`, `|`, background `&`, parentheses grouping) into segments for analysis
- **Script detection**: Detects interpreter form (`bash script.sh`), direct execution (`/path/script.sh`, `./script.sh`), and chmod‑enabled scripts; optionally captures script content when available
- **COPY/ADD mapping**: Maps container paths to repository paths and summarizes copied file types/content hints
- **EXPOSE parsing**: Extracts ports and protocols
- **USER parsing**: Extracts user and group information

See `Dockerfile_EAST_Limitations.md` for detailed coverage boundaries and known gaps.

### Requirements
- Python 3.8+
- Packages: `dockerfile-parse`, `anytree`

Install packages:

```bash
pip install dockerfile-parse anytree
```

### Quick Start
- The library API entrypoint is `get_EAST()` from `Dockerfile_EAST.py`.
- Provide the Dockerfile content as a string, a temporary repository root path, and the absolute path to the Dockerfile on disk.
- Optionally pass `build_args` to resolve unassigned `ARG` values. If not provided, the parser will fall back to the `DOCKER_BUILD_ARGS_JSON` environment variable.

```python
from pathlib import Path
from anytree import RenderTree
from Dockerfile_EAST import get_EAST

repo_root = "/path/to/repo"  # absolute path to your repository root
dockerfile_path = str(Path(repo_root) / "Dockerfile")

dockerfile_content = """\
FROM ubuntu:22.04 AS base
ARG VERSION
ENV PATH=$PATH:/usr/local/bin
RUN echo "Building" && echo "VERSION=$VERSION"; echo done
COPY scripts/setup.sh /usr/local/bin/
RUN chmod +x /usr/local/bin/setup.sh && /usr/local/bin/setup.sh
"""

# Preferred: explicit build args
tree = get_EAST(
    dockerfile_content,
    repo_root,
    dockerfile_path,
    build_args={"VERSION": "1.0.0"},
)

# Visualize
for pre, _, node in RenderTree(tree):
    print(f"{pre}{node.name}")
```

### Using environment variable for build args
You may set an environment variable instead of passing `build_args`.

```python
import os
from Dockerfile_EAST import get_EAST

os.environ["DOCKER_BUILD_ARGS_JSON"] = '{"VERSION":"1.0.0","BUILD_DATE":"2025-01-01"}'
tree = get_EAST(dockerfile_content, repo_root, dockerfile_path)
```

### Parsing from an existing Dockerfile on disk
```python
from Dockerfile_EAST import get_EAST

repo_root = "/absolute/path/to/repo"
dockerfile_path = "/absolute/path/to/repo/Dockerfile"

with open(dockerfile_path, "r", encoding="utf-8") as f:
    content = f.read()

tree = get_EAST(content, repo_root, dockerfile_path)
```

### Working with the tree
The parser returns an `anytree.Node` tree. Node names encode the logical elements. Example traversal helpers:

```python
from anytree import PreOrderIter

# All RUN instruction subtrees
run_nodes = [n for n in PreOrderIter(tree) if n.name == "RUN"]

# Extract command segments from RUN nodes (if present)
def find_command_segments(run_node):
    segments = []
    for n in PreOrderIter(run_node):
        if n.name == "command_segment":
            # children may include "command", "separator", and "type"
            entry = {"command": None, "separator": None, "type": None}
            for c in n.children:
                if c.name == "command" and c.children:
                    entry["command"] = c.children[0].name
                elif c.name == "separator" and c.children:
                    entry["separator"] = c.children[0].name
                elif c.name == "type" and c.children:
                    entry["type"] = c.children[0].name
            segments.append(entry)
    return segments

for rn in run_nodes:
    print(find_command_segments(rn))
```

### Script detection and content extraction
When `COPY`/`ADD` map a repository file into the image, the parser maintains a mapping from container paths to repository paths. If an invoked script is identifiable (via interpreter, shebang, or `chmod +x`), the parser may attach a `content` child holding the script text.

Notes:
- Provide a correct `repo_root` and `dockerfile_path` so the COPY/ADD mapping can resolve repository files.
- If a script is invoked but the source file is not found under `repo_root`, only minimal script info is included.

### API Reference (selected)
- **`get_EAST(dockerfile_content: str, temp_repo_path: str, dockerfile_path_local: str, build_args: dict | None = None) -> anytree.Node`**
  - High‑level entrypoint. Returns an `anytree` tree built from the internal EAST list representation.
- `EAST(...) -> list` (internal): Returns the list‑of‑lists EAST structure.
- `json_to_tree(json_list) -> anytree.Node` (internal): Converts EAST list to an `anytree` tree.

### Project Layout
- `Dockerfile_EAST.py`: Main enhanced parser (library entrypoint: `get_EAST()`)
- `Dockerfile_EAST_old.py`: Legacy parser kept for comparison
- `Dockerfile_EAST_Limitations.md`: Detailed limitations analysis
- `1.Incomplete_Variable_Syntax_Support/`: Analysis, tests, and docs around variable parsing
- `2.1.RUN_Instruction_Parsing_Limitations/`: RUN parsing comparison suite
- `2.2.No_Shell_Command_Analysis/`: Shell construct limitations suite
- `2.3.Script_Detection_Limitations/`: Script detection limitations suite
- `4.COPY_ADD_Instruction_Limitations/`: COPY/ADD limitations suite
- `5.ENV_Instruction_Limitations/`: ENV limitations suite
- `6.ARG_Instruction_Limitations/`: ARG limitations suite
- `7.EXPOSE_Instruction_Limitations/`: EXPOSE limitations suite
- `8.USER_Instruction_Limitations/`: USER limitations suite
- `9.General_Parsing_Limitations/`: General/holistic limitations suite

### Running the test suites
Each limitations directory contains a self‑contained `COMPREHENSIVE_TEST_SUITE.py` and a `comprehensive_test.log` with example outputs.

```bash
# Example: run RUN parsing suite
python3 2.1.RUN_Instruction_Parsing_Limitations/COMPREHENSIVE_TEST_SUITE.py

# Example: run ARG handling suite
python3 6.ARG_Instruction_Limitations/COMPREHENSIVE_TEST_SUITE.py
```

### Known Limitations (high‑level)
- **Variable resolution graph**: The parser does not perform global variable propagation across instructions beyond metadata extraction
- **RUN shell semantics**: It segments commands but does not fully parse or execute shell flow control constructs
- **Script detection**: Requires detectable patterns (interpreter, path, chmod); relative/ambiguous invocations may be missed
- **COPY/ADD patterns**: Limited glob/brace expansion; no full shell‑style globbing
- **File content analysis**: Heuristics only; no deep content inspection
- **Stage aliasing**: Basic alias handling; complex alias chains may not be fully resolved

See `Dockerfile_EAST_Limitations.md` for concrete examples and edge cases.

### Tips and Best Practices
- **Always pass absolute paths** for `temp_repo_path` (repository root) and `dockerfile_path_local` to maximize COPY/ADD mapping fidelity
- **Prefer explicit `build_args`** over relying on `DOCKER_BUILD_ARGS_JSON` for clarity and reproducibility
- **Use `anytree.RenderTree`** during development to understand the resulting structure quickly

### Demo and saved outputs
- **Demo script**: `examples/comprehensive_demo.py`
  - Runs the parser on a comprehensive, programmatically generated scenario (multi‑stage, ARG/ENV with complex variables, RUN with various separators and JSON array form, COPY/ADD with mapping and binary detection, EXPOSE/USER/WORKDIR/CMD).
  - Prints both the rendered tree and full JSON EAST.
- **Saved outputs** (generated by the demo):
  - Rendered tree: `examples/output/rendered_tree.txt`
  - JSON EAST: `examples/output/east.json`

Regenerate the outputs:

```bash
python3 examples/comprehensive_demo.py
```