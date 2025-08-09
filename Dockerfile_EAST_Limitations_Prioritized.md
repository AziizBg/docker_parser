## Dockerfile EAST Parser - Prioritized Limitations (for High-Level Design Antipattern Detection)

This list orders limitations by their impact on detecting high-level design antipatterns in Dockerfiles. Use this to focus engineering effort where it increases antipattern coverage the most.

### Prioritization scale
- P0: Blocks detection of critical antipatterns across many repos
- P1: Significantly reduces precision/recall of common antipatterns
- P2: Useful for depth and accuracy, not blocking
- P3: Nice-to-have; low impact on antipattern detection

### P0 (Must address first)
- **Shell/RUN segmentation and logic understanding**
  - **Limitation**: RUN commands are not fully segmented; limited support for separators and control flow (for, if, case, while)
  - **Impact**: Blocks detection of core antipatterns:
    - Unpinned package installs, missing `apt-get update`/`clean` hygiene
    - Chained installs without error checks
    - Long-running background processes (`&`) in build layers
    - Complex branching that hides unsafe flows
  - **Status**: `&&`, `;`, `||`, pipes, grouping improved in enhanced parser; still missing shell constructs (for/if/while/case)
  - **Action**: Add minimal POSIX shell AST or heuristic segmentation for `for/if/while/case/do/done` blocks

- **Multi-stage dependency resolution (COPY --from graph)**
  - **Limitation**: Incomplete understanding of artifact flow between stages and alias chains
  - **Impact**: Misses antipatterns:
    - Shipping build-time artifacts/tools in final image
    - Unnecessary stage dependencies and bloated final images
    - Ambiguous or broken alias resolution (`FROM base AS a`, `FROM a AS b`)
  - **Action**: Build explicit stage DAG with alias resolution; map `COPY --from=<stage|index>` sources to producers

- **Variable/ARG/ENV propagation and resolution across stages**
  - **Limitation**: Variables parsed but not resolved or tracked across instructions/stages
  - **Impact**: Hides:
    - Secrets via `ARG`/`ENV` passed to `RUN` (e.g., `curl -H "Authorization: $TOKEN"`)
    - Conditional logic based on args (build toggles)
    - Misconfigured users/paths built from variables
  - **Action**: Track symbol table per stage with inheritance; propagate values when statically known; mark tainted/unknown when not

- **COPY/ADD path semantics and globbing**
  - **Limitation**: No glob/brace expansion or pattern matching
  - **Impact**: Misses:
    - Copying entire source trees into final image (bloat)
    - Inclusion of sensitive files (e.g., `.env`, `id_rsa`, `.*`)
    - Hidden multi-copy patterns causing layer duplication
  - **Action**: Implement best-effort matcher with `.dockerignore` awareness; simulate common globs; flag risky patterns

### P1 (High impact)
- **Script invocation detection (beyond extensions)**
  - **Limitation**: Only detects `.sh`-like extensions; misses `bash -c`, `source`, shebang-only scripts, relative paths
  - **Impact**: Hides antipatterns in external scripts:
    - Package hygiene, secret exfiltration, downloading unsigned binaries
  - **Action**: Detect script execution forms: `bash -c`, `sh -c`, `./script`, shebang scanning when file content available

- **Pinned versions and determinism checks**
  - **Limitation**: No semantic checks that packages/images are pinned (tags/digests/versions)
  - **Impact**: Cannot flag non-reproducible builds (e.g., `FROM ubuntu:latest`, `apt-get install -y curl`)
  - **Action**: Lint rules over tokenized RUN/CMD and FROM: require digest or version; suggest `--no-install-recommends`

- **USER/privilege model analysis**
  - **Limitation**: No validation that non-root is used in final stage; weak mapping of UID/GID
  - **Impact**: Misses core antipattern: running as root; mixed user switches mid-build
  - **Action**: Track effective user per stage; require non-root in final stage unless justified

- **HEALTHCHECK presence and robustness**
  - **Limitation**: Parsed but not validated
  - **Impact**: Misses lack of health checks or fragile checks
  - **Action**: Require HEALTHCHECK in final stage; basic validation (timeouts, failure behavior)

### P2 (Medium impact)
- **Network and remote download analysis**
  - **Limitation**: No detection of `curl/wget` without verification, insecure protocols
  - **Impact**: Misses supply-chain antipatterns
  - **Action**: Heuristics for `curl|wget` plus `sha256sum`, `gpg --verify`, `https` enforcement

- **Layer hygiene and caching**
  - **Limitation**: No checks for cache-busting or layer bloat (e.g., `apt-get update` in a separate layer)
  - **Impact**: Misses performance/size antipatterns
  - **Action**: Cross-instruction reasoning: enforce update+install in one RUN; ensure cleanup in same layer

- **EXPOSE and port policy**
  - **Limitation**: No validation of exposed ports or protocols; no policy rules
  - **Impact**: Misses design issues (unnecessary open ports)
  - **Action**: Add policy checks (allowed ports, protocols)

- **LABEL and metadata completeness**
  - **Limitation**: Labels parsed but not validated
  - **Impact**: Misses governance/compliance antipatterns
  - **Action**: Validate required labels (maintainer, source, revision, license)

### P3 (Lower impact)
- **Error recovery and malformed syntax tolerance**
  - Improves coverage but less critical for antipatterns

- **Performance/streaming parsing**
  - Helps scale to large monorepos; not directly tied to detection accuracy

- **Comment preservation**
  - Can improve intent inference; low direct impact on antipattern flags

---

### Crosswalk: Limitation → Antipatterns missed (non-exhaustive)
- **RUN segmentation / shell logic (P0)**: package hygiene, missing cleanups, unchecked errors, background jobs, hidden branches
- **Multi-stage dependency graph (P0)**: shipping build tools, unused artifacts, stage alias confusion
- **Variable propagation (P0)**: leaked secrets, dangerous toggles, misconfigured user/paths
- **COPY/ADD patterns (P0)**: bloat, sensitive file inclusion, layer duplication
- **Script detection (P1)**: hidden risky behavior in external scripts
- **Pinned versions (P1)**: non-reproducible builds
- **Privilege model (P1)**: running as root in final image
- **Healthcheck (P1)**: missing or weak health checks
- **Network downloads (P2)**: unverified binaries, insecure protocols
- **Layer hygiene/caching (P2)**: cache busting, large images
- **EXPOSE policy (P2)**: unnecessary ports
- **LABEL governance (P2)**: missing metadata

### Immediate roadmap (practical next steps)
1. Extend enhanced RUN parser with minimal shell control-flow recognition (for/if/while/case blocks)
2. Implement stage DAG with alias chain resolution and `COPY --from` source mapping
3. Add symbol tables for ARG/ENV with per-stage propagation and taint tracking
4. Introduce COPY/ADD glob simulation with `.dockerignore` support and sensitive file heuristics
5. Build initial lint rules for pinning, privilege, healthchecks, network downloads, and layer hygiene