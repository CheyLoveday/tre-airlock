# Feasibility note — <STUDY_ID>

> INTERNAL analyst note (the released client artefact is the Lean-adjudicated `release.json`). Aggregate only, SDC-applied. Generated from `FeasibilityResult`; this template
> mirrors the structure of `feasibility_summary.txt` (the INTERNAL analyst note).

**Request:** <client> · **Variant:** `<CPRA>` (build GRCh38); ref/alt `<R>/<A>`; carrier =
`<het_and_homalt|het_only>` · **Purpose:** <purpose> · **Turnaround:** <date>

## Recommendation
> **GO / NO-GO / GO WITH CAVEATS** — <one-line rationale>

## Eligible genotype carriers (consented, QC-passed)
| Metric | Value (SDC-applied) |
|---|---|
| Approximate count | `<~N or <min>` |
| Array-direct (high confidence) | `~<N>` or *suppressed* |
| Imputed-supported (conditional) | `~<N>` or *suppressed* |
| Ancestry breakdown | per-group `~N`, or *suppressed* |

## Method
- Carrier definition; array QC (call-rate, GQ, missingness); imputed used where DR2 ≥ floor and
  per-genotype certainty ≥ floor; **consent gate** (withdrawn excluded from any recontact set).

## Caveats
- Genotype feasibility only — ICD-10 phenotype eligibility is assessed downstream and will reduce the
  count. Imputed-only carriers are conditional. A recruitment-planning estimate, not an invitation
  list. Disclosure control (min cell + rounding + secondary suppression) applied.

_Only this aggregate is airlock-export. Participant-level data stays in the TRE._
