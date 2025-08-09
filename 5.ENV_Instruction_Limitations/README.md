## Limitation 5 — ENV Instruction (Enhanced)

Adds multi-line support and basic value validation/insight:
- Continuations with `\` across lines
- Mixed formats: `ENV KEY=value KEY2=value2` and `ENV KEY value`
- Validation metadata per pair:
  - `boolean` type detection with normalized value
  - `port` range check (1..65535) with issue when invalid
  - `path` segmentation count (colon-separated)
  - `potential_secret` heuristic flag

### What’s included
- Main parser updated: `Dockerfile_EAST.py`
- Comparison suite: `COMPREHENSIVE_TEST_SUITE.py`

### Run
```bash
python3 COMPREHENSIVE_TEST_SUITE.py | tee comprehensive_test.log
```

### Results overview
- Single-line values
  - Old: three separate `ENV` nodes with plain `key/value`.
  - Enhanced: one `ENV` node with three `pair` entries plus validation:
    - `DEBUG=true` → type=boolean, normalized=True
    - `PORT=8080` → type=port, in-range
    - `PATH=/usr/bin:/usr/local/bin` → type=path, segments=2

- Multi-line continuation
  - Old: split into three separate `ENV` nodes.
  - Enhanced: one `ENV` node containing three `pair`s (correctly merges backslash-continued lines).

- Mixed formats
  - Old: plain `key/value`.
  - Enhanced: `pair`s with validation; `SECRET_KEY` and `AWS_TOKEN` flagged as `potential_secret`.

- Validation checks
  - Old: plain `ENABLED=YES` and `PORT=70000`.
  - Enhanced: `ENABLED=YES` → boolean normalized=True; `PORT=70000` → port with `issue=out_of_range`.

See `comprehensive_test.log` for full EAST trees (old vs enhanced) per test.
