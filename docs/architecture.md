# Architecture

Two views of one system. **Panel A** is the static *package structure* — how the code is layered.
**Panel B** is the dynamic *process structure* — how a request flows to a governed result. They share
one pure core: A shows *where* the logic lives, B shows *when* it runs. A rendered two-panel figure is
in [`figure1-architecture.html`](figure1-architecture.html).

---

## Panel A — package structure

### A · Level 1 — four layers
A strict four-layer stack; every layer depends **downward only**.

```
ORCHESTRATION    workflow DAG · CLI · notebook · in-memory entry    ← wires stages, no logic
IMPERATIVE SHELL io · pipeline · config-loader · format adapter     ← all IO, paths, config
FUNCTIONAL CORE  extract · qc · classify · sdc · reporting ·        ← pure, deterministic, no IO
                 airlock · epi · resolve · views
NUMERIC KERNEL   carrier loop (@njit) + NumPy reference oracle      ← arrays only
TYPED BOUNDARY   models · config schema   (cross-cuts every layer)
```

**The one rule:** *the core never imports the shell.* Logic is pure and unit-testable; IO is quarantined.

### A · Level 2 — layers, contents, dependency direction
| Layer | Modules | Responsibility | May import |
|---|---|---|---|
| **Typed boundary** | `models`, `config` (schema) | Validated request / result / release objects + tabular schemas; fail-fast at the edge | nothing internal |
| **Numeric kernel** | `kernels` | `@njit` carrier-count loop over arrays; each has a NumPy reference oracle | — |
| **Functional core** | `extract` `qc` `classify` `sdc` `reporting` `airlock` `epi` `resolve` `views` | Pure logic: slice, mask, carrier decision, disclosure control, output builders, release predicate | boundary, kernel |
| **Imperative shell** | `io` `pipeline` `cli` `config` (loader) `format adapter` `notebook` | Read inputs → call core → write outputs; the only place with a filesystem | core, boundary |
| **Orchestration** | workflow DAG, in-memory entry | Wires stages into a DAG / a quick path; controls reruns + provenance | shell only |

### A · Level 3 — module map (~5k LOC)
**Core (pure):**
- `extract` — metadata-first dataset slice; variant pre-flight (build / strand / normalize); source decision; candidate-table builder.
- `qc` — per-row QC mask functions (call rate, genotype quality, imputation DR2, max-GP).
- `classify` — carrier logic: consent gate, array-vs-imputed evidence combination, confidence tier, decision.
- `sdc` — statistical disclosure control: minimum-cell suppression, rounding, secondary suppression.
- `reporting` — output builders: internal carrier table, pseudonymised handoff, client summary, audience skins, internal frequency-control view.
- `airlock` — the release predicate (the sole internal→exportable transition) + the transfer manifest builder.
- `epi` — epidemiology return validation + the final post-phenotype result.
- `resolve` — gene / disease request → a curated variant set (the governed batch/union path), catalogue-driven.
- `views` — aggregate-only display tables for notebooks and review.

**Kernel:** `kernels` — the compiled carrier-count loop + its NumPy reference (used as a correctness oracle in tests).

**Shell:** `io` (readers/writers: parquet / csv / tsv / json / text) · `pipeline` (stage orchestrators + the two run modes) · `cli` (one command per request type) · `config` (validator + loader) · *format adapter* (real pVCF/tabix → core schema; optional) · `notebook` (display helpers).

**Boundary:** `models` — `Request` / `BatchRequest` / `Result` / `ReleaseCandidate` / `EpiReturn` / `FinalResult` + tabular schemas. Release objects are frozen + extra-forbidden, so a participant-level field cannot be constructed.

**Outside the package:** workflow DAG (one rule per stage) · a machine-checked release-gate proof · the test pyramid (unit · kernel-vs-reference · integration · e2e · conformance) · setup scripts (synthetic-data generator, format transcoder, profiler) · config thresholds + catalogs · deliverable templates.

---

## Panel B — process structure

### B · Level 1 — the governed flow
`Request → pre-flight → slice + QC → classify (+consent) → SDC → airlock → client aggregate`, with an
internal branch `pseudonymised handoff → epidemiology → final return`.

### B · Level 2 — each stage: core module, gate, artefact
| # | Stage | Core module(s) | Gate | Artefact (tier) |
|---|---|---|---|---|
| 1 | Request | `models` | typed validation | `Request` |
| 2 | Pre-flight | `extract` | request-integrity (fail-closed / caveat) | preflight + availability (array / imputed) |
| 3 | Slice + QC | `extract` · `qc` | QC masks | candidate table (internal) |
| 4 | Classify | `classify` (+ `kernels` reconciliation) | **consent gate** 🔒 | annotated carrier table (internal) |
| 5 | SDC | `sdc` | **disclosure control** 🔒 (min-cell · round · secondary) | suppressed counts |
| 6 | Airlock | `airlock` | **fail-closed release gate** 🔒 | `ReleaseCandidate` + transfer manifest |
| 7 | Release | `bridge` → Lean airlock | **runtime adjudication** 🔒 (exact bytes + receipt) | `release.json` + `release.ready` (export); analyst note stays internal |
| — | Handoff → Epi → Final | `reporting` · `epi` | pseudonymisation | handoff (internal) → `EpiReturn` → `FinalResult` (export) |

### B · Level 3 — two modes over one core, and the typed objects that flow
- **Same core, two runners.** An **in-memory quick path** chains stages with no intermediate files; a
  **file-staged DAG** runs one rule per stage with staged artefacts and per-run provenance, rerun-aware.
  Both call identical pure functions — only the shell differs.
- **Typed objects flowing through:** `Request` → candidate table → annotated table → `Result` →
  `ReleaseCandidate` → transfer manifest; the branch: pseudonymised handoff → `EpiReturn` → `FinalResult`.
- **Artefact tiers.** *Internal-only* (participant-level candidate / annotated tables, pseudonymised
  handoff) vs *export-eligible* (exactly one aggregate summary). The release gate is the **sole**
  internal→exportable transition and it fails closed.
- **Reconciliation.** The readable classifier (stage 4) and the compiled kernel count the same
  post-consent carriers; a divergence raises rather than silently passing — the kernel is a correctness
  oracle, not a separate path.

---

## Why it scales
Functional core / imperative shell keeps logic pure and testable; typed boundaries fail malformed input
at the first gate; the genotype resource is queried by coordinate (index-scoped), never loaded whole; the
hot path is vectorised with the numeric loop isolated as a compiled kernel; large reference lists are
scanned once and cached. Execution is deterministic and staged as a DAG with provenance, and a
scaling-slope regression test guards against a reintroduced O(n²).
