# TRE package & tool cross-check

Every dependency, tool, and external binary this project touches, cross-checked against the live OFH
allowlist (`ourfuturehealth/tre-package-access`, **verified June 2026**). The goal: prove that
everything which runs **inside the TRE runtime** is approved, and be explicit and honest about the
handful of items that are not on the list — separating *"would clear for TRE use"* from
*"never runs in the TRE."*

## Legend
- ✅ **Available in the TRE today** — on the allowlist, Python stdlib, or the platform workbench itself.
- 🔶 **Would clear for TRE use** — part of the intended TRE workflow, not yet allowlisted; request via
  OFH's documented package process (or map to a platform-native equivalent). Nice-to-have.
- 🧪 **Demo / local scaffolding** — never a TRE runtime step; no clearance needed.
- 🛠 **Dev / CI / build tooling** — runs locally or in CI, not in the restricted project; allowlist-exempt
  by the dependency policy.

## Bottom line
- **All 7 runtime dependencies are allowlisted.** The `numba` kernel is a reconciliation oracle for
  the array-direct carrier count, not the only implementation of the hot path; it remains a normal
  runtime dependency because `pipeline.py` imports the kernel module on every run and the pipeline
  fails closed if the kernel and readable pandas classification diverge.
- **Nothing un-cleared runs inside the TRE runtime.**
- The only not-on-allowlist items are (a) intended-workflow tools we would clear — **Snakemake** and
  **Lean** — and (b) **demo / CI / build** tooling that never enters the TRE runtime.
- The only external binary on the runtime path is **git** (provenance), and it degrades gracefully if
  absent.

---

## 1. Runtime dependencies — `[project.dependencies]` (must be TRE-available)
These run inside the TRE on every feasibility request. All approved.

| Package | Allowlist status | Project floor |
|---|---|---|
| numpy | ✅ allowlisted (`>=1.17.3`) | `>=1.26` |
| pandas | ✅ allowlisted (`>=1.0.0`) | `>=2.0` |
| pyarrow | ✅ allowlisted (`>=22.0.0`) | `>=22.0.0` |
| pyyaml | ✅ allowlisted (`>=6.0.3`) | `>=6.0.3` |
| psutil | ✅ allowlisted (`>=7.2.2`) | `>=7.2.2` |
| pydantic | ✅ allowlisted (`>=2.12.5`) | `>=2.12.5` |
| numba | ✅ allowlisted (`>=0.63.1`) | `>=0.63.1` |

Floors mirror the allowlist minimums (numpy/pandas are higher by project need); `uv.lock` pins exact
resolved versions.

## 2. Python standard library (always available, no allowlist entry needed)
Used throughout the core and shell. Notably: the **Merkle audit ledger** is pure `hashlib` + `json`;
the **CLI** is `argparse`; **provenance** hashing is `hashlib`.

`argparse · collections · csv · dataclasses · datetime · hashlib · importlib.metadata · json ·
logging · os · pathlib · random · re · subprocess · sys · tempfile · time · typing`

## 3. Optional extras
| Extra | Package | Status | Role |
|---|---|---|---|
| `notebook` (planned, Wave 10) | matplotlib | ✅ allowlisted (`>=3.10.8`) | Notebook charts; imported lazily with a pandas-Styler fallback |
| `notebook` (planned, Wave 10) | jupyterlab | ✅ the workbench itself | OFH runs JupyterLab; it is the platform environment, **not** a pip allowlist entry. `jupyterlab` in the extra is **local-only** (run the notebook on a laptop) |

## 4. 🔶 Would clear for TRE use — intended workflow, not yet allowlisted
| Tool | Status | Role in the TRE workflow | Path to TRE |
|---|---|---|---|
| **Snakemake** (`workflow` extra) | 🔶 not on the allowlist | Orchestrates the staged in-TRE pipeline (extract → qc → classify → report → airlock) | Request clearance, or map to the DNAnexus-native execution model (the Nextflow/WDL port doc shows the wiring is the only thing that changes) |
| **Lean 4** (`leanprover/lean4:v4.30.0`, `lake`) | 🔶 non-Python; **proposed platform-level component**, not an analyst package | The **runtime release authority**: the `airlock` executable adjudicates every release (proof-carrying export unconstructable without a `ReleaseOK` witness), and there is **no Python fallback** | Deployed by the PLATFORM (read-only path + pinned digest per `platform/release_policy.json`), not via the analyst package allowlist; the Python predicates remain reference/preflight + differential-conformance only |

Both are **nice-to-have assurance/reproducibility layers** — supplementary to the core go/no-go
verdict, not load-bearing for it.

## 5. 🧪 Demo / local scaffolding — never a TRE runtime step
| Tool | Status | Why it never needs clearance |
|---|---|---|
| **pysam** (`ofhgen` extra) | 🧪 not on the allowlist | Generates synthetic OFH-format fixtures **offline** (valid bgzip/tabix via bundled htslib). In the real TRE the files already exist and are read with platform `tabix`/`bcftools`; you never *generate* genotypes inside the TRE. Lazy-imported; the simplified path needs nothing |
| **graphviz / `dot`** | 🧪 not on the allowlist | Renders the Snakemake DAG to `docs/reference/dag.png` — a documentation step, local only |

## 6. 🛠 Dev / CI / build tooling — allowlist-exempt by policy
Runs locally or in CI, not in the restricted project.

| Tool | Status | Use |
|---|---|---|
| ruff (`dev`) | 🛠 not on the allowlist | Lint / format; local + CI |
| pytest (`dev`) | 🛠 *happens to be* allowlisted (`>=9.0.1`), but used as dev/CI only | Test suite |
| line_profiler (`profile`) | 🛠 not on the allowlist | Profiling; local only |
| hatchling (build backend) | 🛠 not on the allowlist | Build-time only (produces the wheel). `setuptools`/`wheel` *are* allowlisted if a rebuild were ever needed in-environment |
| uv | 🛠 not on the allowlist | Package/venv manager; local + CI. The TRE manages its own environment |

## 7. External binaries (not Python packages)
| Binary | On the runtime path? | Notes |
|---|---|---|
| **git** | Yes — but optional | `pipeline.py` calls `git rev-parse HEAD` for provenance, wrapped in `try/except` → returns `"unknown"` if git is absent. The pipeline runs without it. The **only** external-binary call on the runtime path |
| tabix / bcftools | No (platform-provided) | Real genomics tools provided by the TRE platform; referenced conceptually. htslib is bundled by `pysam` for the offline demo only |
| plink2 / qctool | No (referenced only) | Named in the file-format reference docs as the real BGEN-producing tools; not invoked by this repo |

## 8. CI infrastructure (GitHub Actions — irrelevant to the TRE)
`actions/checkout`, `astral-sh/setup-uv`, and `softprops/action-gh-release` run only in GitHub
CI. The Lean CI job (`lean.yml`) proves the formal project in CI; the built `airlock` executable
itself is the RUNTIME release authority, deployed as a platform-level component in a TRE.

---

### How to re-verify
The allowlist is a **real-time, request-driven** list (`tre-package-access` points to "instructions on
how to request and download additional packages"). Re-check against the live README before any
TRE-runtime addition, and record the verdict in the development decision log.
