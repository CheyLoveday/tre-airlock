# Genotype-feasibility service — what it is, what you get, how to run it

A **go / no-go / go-with-caveats** assessment for a Recall-by-Genotype recontact study: *can OFH
identify a credible, eligible, governable pool of carriers of the requested variant, in time?* The
service output is a decision-ready feasibility note: source status, carrier estimate, caveats,
disclosure-control status, and next operational step.

## Problem shape
For a cohort resource, a genetic feasibility request is rarely just "run a genetics query." It asks
whether the requested subcohort can be assembled across the relevant data products with acceptable
coverage, representation, overlap, and governance.

This MVP builds the recall-by-genotype / variant-gene-disease family end to end. The same service
grammar generalises to other feasibility families:

| Family | Typical ask | Core checks | MVP coverage |
|---|---|---|---|
| Cohort sizing | "How many with phenotype X also have usable genetics?" | cross-domain overlap | partial |
| Variant / gene-centric | "How many carriers of variant/gene Y?" | typed vs imputed, QC, ancestry, kinship | built |
| PRS / ancestry-aware | "Can we stratify by PRS or ancestry?" | ancestry availability, cell sizes | framed |
| Genotype-phenotype association | "Can we test variant/gene Y against outcome X?" | outcome source, coding, timing | framed |
| Pharmacogenetic | "Can we assess gene-drug response?" | dispensed-vs-prescribed, time window | framed |
| Geography / environment | "Is there regional enrichment?" | geography provenance and coarsening | framed |
| Recall-by-genotype | "Can we identify a subgroup for recontact?" | aggregate feasibility, consent, SDC | built |

The intake grammar is: **population · genetic unit · phenotype/outcome source · stratifiers · time
model · output · access context**. The current request models cover the genetic unit at variant, gene,
and disease-panel levels; phenotype eligibility and access-scope review remain explicit downstream
handoffs.

The wider public-data-estate snapshot and suggested upstream Pydantic intake shape are captured in
`docs/reference/ofh-public-data-snapshot.md`. In practice, the broad intake object should compile into
the narrow models this MVP already runs: `VariantRequest`, `GeneRequest`, `DiseaseRequest`,
`BatchRequest`, `EpiReturn`, and `ReleaseCandidate`.

## Disposition model
The recommendation (in the INTERNAL analyst note; the released artefact carries the governed
count) is the scientific-feasibility axis of a wider access decision:

| Disposition | Meaning in the service |
|---|---|
| **GO** | identifiable, credible, eligible-enough, governable, and timely |
| **GO WITH CAVEATS** | feasible only with stated source/QC/SDC/confirmation caveats |
| **NO-GO** | currently unsupported by the requested evidence or released cell sizes |
| **Needs governance/protocol review** | scientifically possible, but access scope, recontact, or output policy needs human review |

## Turnaround
Designed for the **<5 business-day** recontact-service window. The work is deterministic and
one-command, so the remaining variability sits in governance review: disclosure-control sign-off and
airlock.

## What the client (external researcher) receives
- **An aggregate feasibility count only**, SDC-applied: a rounded approximate number (or `<min` when
  below the minimum cell size), with the subgroup/ancestry breakdown shown only when every cell
  clears disclosure control.
- Delivered as `release.json` — the canonical aggregate payload rendered by the **runtime Lean 4
  airlock**, committed under its `release.ready` receipt, the **sole airlock-export candidate**.
- The variant definition, method (carrier rule + QC thresholds), caveats, and explicit
  recommendation live in the INTERNAL analyst note (`feasibility_summary.txt`, viewed with
  `ofh-feasibility notes`); releasing any of that narrative is a separate governed decision for
  the human airlock reviewer, not an automatic client deliverable.

## Internal-only outputs
- **Participant-level evidence.** Participant IDs and the full QC/decision table stay internal in
  `internal_carrier_table.parquet` for recontact operations.
- **Pseudonymised carrier handoff.** `handoff_to_epi.csv` goes to epidemiology in-TRE for ICD-10
  phenotype eligibility.
- **QC control view.** `frequency_control_view.json` is an internal credibility check; the airlock
  manifest classifies it as non-export.

## Standard caveats (always stated)
- It is a **genotype** feasibility figure; ICD-10 phenotype eligibility is assessed downstream and
  will reduce the count.
- Imputed-only carriers are **conditional** (benefit from confirmatory genotyping); array-direct
  calls are high-confidence.
- The count supports **recruitment planning**; invitation eligibility and contactability are downstream
  operational steps.
- Disclosure control (minimum cell size + rounding + **secondary suppression**) is applied to every
  released number.

## How to run
```bash
uv sync --extra dev
uv run python scripts/generate_synthetic.py            # synthetic inputs (seed 42)
make airlock                                           # build the Lean adjudicator (once)
uv run ofh-feasibility run                             # single variant -> committed release receipt
uv run ofh-feasibility notes                           # INTERNAL analyst note (diagnostics)
uv run ofh-feasibility batch --template composite_profile   # multi-variant (union) recall set
uv run ofh-feasibility run --request data/synthetic/requests/chek2_i157t.csv \
    --results-dir results/chek2_i157t                  # expanded CHEK2 variant case
uv run ofh-feasibility gene --symbol CHEK2 --results-dir results/chek2_gene
uv run ofh-feasibility disease --panel breast_cancer --results-dir results/breast_cancer
```
Reproducible path: `uv run snakemake --cores 1 -s workflow/Snakefile`. Every run writes
`provenance.json` (config + input hashes + versions).

Snakemake can target a specific request without editing `variant_request.csv`:
```bash
uv run snakemake --cores 1 -s workflow/Snakefile \
  --config request_path=data/synthetic/requests/chek2_i157t.csv results_dir=results/chek2_i157t_smk
```

OFH-format pVCF/tabix stand-ins use the same Snakefile with config overrides:
```bash
uv sync --extra dev --extra workflow --extra ofhgen
uv run python scripts/generate_synthetic.py
uv run python scripts/generate_ofh_files.py --in data/synthetic --out data/synthetic/ofh_tre
uv run snakemake --cores 1 -s workflow/Snakefile \
  --config source_format=ofh_tre data_dir=data/synthetic/ofh_tre \
  request_path=data/synthetic/requests/chek2_i157t.csv results_dir=results/ofh_tre_smk
```

## Adding a new request type
Drop a template into `templates/` (e.g. another single-variant JSON or a composite-profile CSV) and
run `ofh-feasibility run --template <name>` — no core code change.

Gene and disease requests are catalogue-driven: `config.yaml` points `variant_catalog_path` at
`configs/catalogs/demo_variant_catalog.yaml`. Replacing that YAML can change demo genes, panels, or variant
metadata without changing the governed counting, SDC, audit, or airlock code.

## Epidemiology return loop (Wave 8) — two governed states
The genotype run produces an **upper-bound (ceiling)** count and a pseudonymised handoff for
epidemiology. Epidemiology owns the downstream ICD-10 phenotype adjudication and returns an
**aggregate** eligible count; the pipeline validates it and releases the **final** post-phenotype
figure:

```bash
# 1. genotype run -> the ceiling + the pseudonymised handoff (feasibility_summary.txt is preliminary)
uv run ofh-feasibility run
# 2. epidemiology fills docs/templates/epi-return-template.json -> epi_return.json
#    using the run_id from results/epi_notification.json
# 3. finalize: validate the return, SDC + airlock the eligible count, write the FINAL summary
uv run ofh-feasibility finalize-eligible --epi-return epi_return.json
```

Pass `--checkpoints <path/to/human_review_checkpoints.jsonl>` only when a real signed checkpoint
ledger exists. A `query` or `block` entry fails closed; omitted checkpoint files are treated as
caller-supplied inputs.

The return is **aggregate-only**; participant or pseudo IDs are rejected fail-closed. `eligible_count`
must be **≤ the genotype ceiling**, must be signed off, and goes through the **same** release gate. The
final release (`release.json`, the sole airlock export; the internal
`final_feasibility_summary.txt` note) labels the genotype
count as the ceiling and the epi-returned count as the post-phenotype eligible figure. Named human
visual-review checkpoints (`intake`, `pre_epi_handoff`, `epi_return`, `pre_airlock`) gate the release —
a `query`/`block` decision halts it. See `docs/templates/human-review-checklist.md` and
`docs/templates/epi-handoff-sheet.md` (return contract).

## Scope basis
This mirrors OFH's documented public workflow shape: TRE, recontact service, airlock, and Five Safes.
Snakemake is the repo's single active local pipeline for the MVP; archived port sketches are reference
material only. See
`docs/reference/BAG3_VERIFICATION.md` and `docs/reference/missing-data.md` for what is synthetic vs
verified.
