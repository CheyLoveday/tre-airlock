# Playbook — run flow, work classes, review gates

How a change gets built in this repo. Read with `docs/SOP_DEV_FLOW.md` and
`docs/AI_USAGE_POLICY.md`. Internal engineering control under OFH governance, not OFH policy.

## Run flow (per change)
human direction → A4 scope/docs seed → A1 core implementation → A2 governance gates → A3 tests +
profiling → A5 repo + PR. One focused branch → reviewed PR into protected `main` → green CI →
squash-merge. `main` stays green between PRs.

## Work classes (and their gate)
| Class | Examples | Required gate |
|---|---|---|
| Core logic | qc / classify / sdc / extract / reporting builders | unit tests; pure (no IO); reason codes |
| Kernel | numba reconciliation check | tested against a NumPy reference and the pandas count |
| Governance | consent / SDC / airlock / release gate | an **invariant test**; PR flagged; fail-closed |
| Stage / orchestration | pipeline, Snakemake, CLI | an integration test; no business logic in the shell |
| Docs / SOP | README, SOPs, templates, ADRs | consistency with code + the other docs; caveats updated |
| Dependency | new package | on the OFH `tre-package-access` allowlist (or dev/CI-only); reason logged |

## Review gates (definition of done)
ruff clean · pytest green · deterministic outputs (seed 42) · the wave's acceptance criteria met ·
governance invariants hold (withdrawn excluded; secondary suppression; one human-readable export) ·
docs/CHANGELOG updated · no `data/`/`results/`/secrets committed · no perf claim without a saved
profile · substantial AI-assisted changes get an append-only project-note entry before handoff.

## Honesty (non-negotiable)
Do not claim OFH uses Snakemake / Nextflow / WDL / Lean or an org-wide OFH Git policy. These are our
choices mirroring OFH public signals + standard reproducible-research practice. Comparator standards
(e.g. UK Biobank cell-size floors) are labelled as comparators, never as OFH-confirmed policy.
