## Limitation 4 — COPY/ADD Instruction (Enhanced)

Adds support for common path patterns and basic content analysis:
- Glob patterns: `*`, `?`, character classes (via Python glob)
- Single-level brace expansion: `{a,b}`
- Directory copies (maps contained files)
- File content type/size summary: `text`, `json`, `env`, `binary`

### What’s included
- Main parser updated: `Dockerfile_EAST.py`
- Comparison suite: `COMPREHENSIVE_TEST_SUITE.py`

### Run
```bash
python3 COMPREHENSIVE_TEST_SUITE.py | tee comprehensive_test.log
```

### Scenarios covered
- `COPY *.txt /dest/` (glob)
- `COPY src/*.py /dest/` (dir glob)
- `COPY src/{file1,file2}.txt /dest/` (brace expansion)
- `COPY src/?.txt /dest/` and `COPY src/[a-z]*.txt /dest/` (wildcards/classes)
- `COPY config.json /app/` and `COPY .env /app/` (content summary)

### Notes
- Brace expansion is single-level only.
- Complex shell expansions are not evaluated.
