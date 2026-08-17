# Documentation — start here

This project is a synthetic, governed **recall-by-genotype feasibility service**. It answers one governed
question: *can OFH identify a credible, eligible, governable pool of carriers of a requested variant
for a recall-by-genotype study — in time?* The data are synthetic; the controls, failure modes, and
governance are the point.

Read in the order below. Each tier answers the next natural question. These are the canonical,
shareable pipeline docs.

## What Counts As Pipeline Documentation

Use these files when you want the proper documentation for the MVP pipeline:

- [for-reviewers.md](for-reviewers.md) — fastest technical orientation and code map.
- [service.md](service.md) — service contract, request families, artefacts, and turnaround.
- [sop-feasibility-analysis.md](sop-feasibility-analysis.md) — operational run flow.
- [sop-output-checks.md](sop-output-checks.md) — governance checks before release.
- [data-contracts.md](data-contracts.md) — typed request / output boundary models.
- [client-outputs.md](client-outputs.md) — what leaves the airlock vs what stays internal.
- [reference/](reference/) — evidence, file-format, preflight, profile, and provenance references.
- [templates/](templates/) — deliverable artefact templates, such as handoff and review checklists.

Internal planning and development material is kept outside this shared documentation set.

## 1 · Understand the service — *what is this?* (~10 min)
| Doc | What it answers |
|---|---|
| [for-reviewers.md](for-reviewers.md) | **Start here** — the 5-minute path, the module-by-module code map, and what to look for |
| [service.md](service.md) | What the client asks, what they receive, what they don't, the turnaround |
| [feasibility-definition.md](feasibility-definition.md) | What "feasibility" means — the five checks |
| [design-decisions.md](design-decisions.md) | The judgment calls and **why** — proportionality, governance, CI-gates-the-critical, the deliberately-lean stance |

## 2 · See how a run works — *the pipeline, end to end*
| Doc | What it answers |
|---|---|
| [../README.md#demo-data-setup](../README.md#demo-data-setup) | How synthetic setup differs from running the pipeline; what imputed stand-ins do and do not cover |
| [sop-feasibility-analysis.md](sop-feasibility-analysis.md) | Intake → run → artefacts → output checks → handoff |
| [sop-output-checks.md](sop-output-checks.md) | The governance gates (SDC, least-privilege, airlock) before any release |
| [client-outputs.md](client-outputs.md) | The client export, internal artefacts, and audience-output skins |
| [notebook-companion.md](notebook-companion.md) | The aggregate-only notebook walkthrough over the same pipeline |
| [../README.md](../README.md) — Architecture + [DAG](reference/dag.png) | The four layers, and the staged Snakemake DAG |

## 3 · Is it real? — *evidence & honesty*
| Doc | What it answers |
|---|---|
| [reference/missing-data.md](reference/missing-data.md) | Every assumption: what is synthetic vs the real OFH resources |
| [reference/BAG3_VERIFICATION.md](reference/BAG3_VERIFICATION.md) | BAG3 verified against the real OFH CPRA lists (array-present, imputed-absent) |
| [reference/CHEK2_VERIFICATION.md](reference/CHEK2_VERIFICATION.md) | The two CHEK2 variants verified against the real lists — the headline opposite verdicts |
| [reference/variant-identifiability.csv](reference/variant-identifiability.csv) | Small public-list-derived availability artifact used by the runtime |
| [tre-package-crosscheck.md](tre-package-crosscheck.md) | Every dependency and tool vs the live TRE allowlist |
| [data-contracts.md](data-contracts.md) | The typed schemas / boundary contracts |

## 4 · Deep reference — *optional, for the curious*
| Doc | What it covers |
|---|---|
| [reference/ofh_tre_genetic_file_formats.md](reference/ofh_tre_genetic_file_formats.md) | The real OFH TRE genetic file formats (deep dive) |
| [reference/variant_preflight.md](reference/variant_preflight.md) | Build match, normalization, palindromic-strand resolution |
| [reference/orchestration_port.md](reference/orchestration_port.md) | Snakemake → Nextflow / WDL → DNAnexus mapping |
| [reference/profile-summary.md](reference/profile-summary.md) | Saved MVP profile evidence and bottleneck interpretation |
| [templates/](templates/) | The actual deliverable artefacts (feasibility note, epi handoff, checklists) |
| [../CHANGELOG.md](../CHANGELOG.md) | What was built, wave by wave |

## Process & governance (appendix)
[playbook.md](playbook.md) · [AI_USAGE_POLICY.md](AI_USAGE_POLICY.md) · [SOP_DEV_FLOW.md](SOP_DEV_FLOW.md) —
the operating model (run flow, work classes, review gates) and how the work itself is governed and
developed.

---
This index covers the shareable service documentation. Internal planning docs are intentionally outside
the review surface.
