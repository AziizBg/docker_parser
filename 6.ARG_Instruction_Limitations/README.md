## Limitation 6 — ARG Instruction (Enhanced)

Resolves unassigned `ARG` values at parse time and annotates their source.

### What’s included
- Main parser update in `Dockerfile_EAST.py`:
  - `get_EAST(..., build_args: dict=None)` and `EAST(..., build_args: dict=None)`
  - Unassigned `ARG NAME` resolves from `build_args` and adds:
    - `resolved`: the value used
    - `source`: `build_arg` (resolved) or `default` (explicit assignment)
- Comparison suite: `COMPREHENSIVE_TEST_SUITE.py`

### How to run
```bash
python3 COMPREHENSIVE_TEST_SUITE.py | tee comprehensive_test.log
```

### Results overview
- Old parser: `ARG VERSION` and `ARG BUILD_DATE` remain unresolved (only `name`).
- Enhanced parser: the same ARGs show `resolved` values and `source=build_arg`.
- Explicit default (e.g., `ARG CHANNEL=stable`) retains `source=default`.

### End-user usage
- Prefer passing build arguments programmatically:
  ```python
  get_EAST(dockerfile, repo_root, dockerfile_path, build_args={"VERSION": "1.0", "BUILD_DATE": "2024-01-01"})
  ```
- Legacy fallback: if `build_args` is not provided, the parser attempts to read `DOCKER_BUILD_ARGS_JSON` (JSON string) from the environment.

