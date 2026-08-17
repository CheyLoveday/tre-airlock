# Epidemiology handoff sheet — <STUDY_ID>

> INTERNAL-TRE-ONLY. Pseudonymised; stays in the TRE. Accompanies `handoff_to_epi.csv` for ICD-10
> phenotype-eligibility assessment. Never leaves via the airlock.

**Variant:** `<CPRA>` (GRCh38) · **Carrier definition:** `<...>` · **Evidence used:** array-direct
`<yes/no>`; imputed evidence `<used/not used>`; imputed-resource membership `<present/absent>`; DR2
`<value or n/a>`

## What you are receiving
- `handoff_to_epi.csv` — one row per included carrier: `pseudo_id, carrier_status, source,
  confidence, caveat`. **No participant IDs, no names, no NHS numbers** (the mapping stays in the TRE).
- Confidence: `high` (array-direct or high-DR2 imputed) vs `conditional` (moderate-DR2 imputed-only —
  benefits from confirmatory genotyping).

## What we ask
- Intersect the pseudonymised carrier set with the **ICD-10 heart-disease** phenotype codes to
  determine eligibility; return the eligible count (the genotype count is an upper bound).

## QC notes
- Array QC: call-rate / GQ / missingness applied. Imputed gated on variant DR2 + per-genotype
  certainty. Sample-level flags (sex-check, relatedness) are recorded in the internal table — kept,
  not silently dropped. See `frequency_control_view.json` for per-stratum AF + intervals (internal).

## Return contract (Wave 8 — what you send back)
Return an **aggregate** result only (a JSON file matching `epi-return-template.json` / the `EpiReturn`
schema). **No participant IDs, no pseudo-ids, no row-level health data** — the pipeline rejects any
identifier and fails closed. Fields:

| Field | Meaning |
|---|---|
| `study_id`, `cpra`, `run_id` | must match this handoff's run; copy the provenance-bound `run_id` from `epi_notification.json` (mismatch fails closed) |
| `eligible_count` | integer ≥ 0, **and ≤ the genotype carrier count** above (the ceiling) |
| `phenotype_definition_id` | your ICD-10 phenotype definition identifier |
| `icd10_codeset_label`, `icd10_codeset_version` | the code-set you used |
| `linked_record_scope` | e.g. `primary_care+hospital` (the denominator you checked) |
| `reviewer`, `return_timestamp` | your name + when |
| `sign_off_status` | must be `signed` to be accepted (else the pipeline holds / queries epi) |
| `caveats` | optional list of free-text caveats |

The pipeline then runs `eligible_count` through SDC + the airlock release gate to a **final**
released figure (with an internal final note labelling it distinctly from the genotype ceiling).

**Deadline / ETA:** ____________ (see the rapid-turnaround notification for the requested turnaround).

Prepared by: ____________  Date: ____________
