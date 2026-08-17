# SOP — running a feasibility analysis

The standard procedure for a single feasibility request, intake to airlock. Deterministic (seed 42);
every run is reproducible and audited.

## 1. Intake
- Receive the request: study id, CPRA (`chrom:pos:ref:alt`, GRCh38), build, carrier definition
  (`het_and_homalt` | `het_only`), requested source (`array` | `imputed` | `array_and_imputed`),
  purpose, turnaround. Capture it as a request file (or a `templates/` template).
- Confirm the request is a carrier **count for recontact** with a feasible downstream phenotype-review
  handoff.

## 2. Run
```bash
uv sync --extra dev
uv run python scripts/generate_synthetic.py          # synthetic inputs (this repo is synthetic-only)
uv run ofh-feasibility run                           # or: snakemake --cores 1 -s workflow/Snakefile
```
The pipeline executes the governed stages: validate variant (identifiable) → source decision → slice
→ QC (call-rate / GQ / missingness / DR2 floor / per-genotype certainty) → classify (consent gate +
confidence + reason codes) → SDC (suppress + **secondary** suppress + round) → reporting →
release gate → airlock manifest.

## 3. Artefacts produced
| Artefact | Tier | Leaves the TRE? |
|---|---|---|
| `internal_carrier_table.parquet` | participant IDs + full provenance | No |
| `handoff_to_epi.csv` | pseudonymised carriers (→ ICD-10 eligibility) | No |
| `frequency_control_view.json` | internal QC/credibility control | No |
| `airlock_pending/release.json` | aggregate, SDC-applied, Lean-rendered | **Yes**, via airlock |
| `feasibility_summary.txt` | analyst note (aggregate, SDC-applied) | No |
| `airlock_manifest.json`, `provenance.json`, `audit_ledger.jsonl` | governance evidence | No |

## 4. Output checks (before any release)
Run the **output-checks SOP** (`docs/sop-output-checks.md`): confirm the release gate passed, the SDC
behaviour is correct, no participant-level data is in the export, and the airlock manifest marks
exactly one human-readable export candidate. Disclosure-control sign-off is a human gate.

## 5. Handoff
- **Epidemiology:** the pseudonymised handoff + method + QC notes (for ICD-10 eligibility).
- **Governance:** the airlock manifest + provenance + audit root.
- **Client:** the committed `release.json` generation (Lean-adjudicated aggregate); the
  feasibility note + recommendation are INTERNAL analyst material unless separately cleared.

## Reproducibility
Same inputs → identical artefacts (golden-tested). Every run writes `provenance.json` (config + input
hashes + versions) and a Merkle `audit_ledger.jsonl` (`ofh-feasibility audit verify`).
