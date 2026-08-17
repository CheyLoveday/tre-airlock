# CHEK2 variant verification against the real OFH CPRA resources

**Question:** are the two CHEK2 breast-cancer variants used in the demo — `22:28695868:AG:A`
(c.1100delC, the founder frameshift **indel**) and `22:28725099:A:G` (I157T, a missense SNV) —
present in the real Our Future Health public CPRA variant lists, on GRCh38?

**Short answer:**
- **c.1100delC `22:28695868:AG:A`** — **NO on the array list; YES on the imputed list.** Array-absent,
  so it cannot be genotyped directly; whether imputed evidence is usable hinges on imputation quality
  (DR2), which is a TRE summary-statistics fact, not a CPRA-list fact. → the honest demo verdict is
  **NO-GO / targeted assay** unless DR2 confirms reliable imputed calling of this indel.
- **I157T `22:28725099:A:G`** — **YES on both lists.** Array-direct, `Inaccurate Call=No`. → array-direct
  high-confidence carriers, **GO** (with the synthetic-cohort breakdown shown).

This is the demo's headline: **two variants in the same gene, one engine, opposite honest answers** —
driven entirely by real-list availability, not by clinical significance.

## Method
- Sources (identical to the BAG3 check):
  - `data/raw/our_future_health_cpra_array_variant_list_grch38_v14.csv` (Release 14 public array CPRA CSV).
  - `data/raw/our_future_health_cpra_imputed_variant_list_grch38-csv.zip` (~609 MB, ~159M rows).
- Helper: `scripts/verify_cpra.py` — **streams** each zip member line-by-line; the file is never
  extracted to disk.
- Runtime grounding: `docs/reference/variant-identifiability.csv` is the small committed artifact derived
  from these checks (with `…-provenance.json` SHA-256-pinning the two raw source files); `config.yaml`
  points `variant_identifiability_path` at it, so the pipeline overlays each variant's real-list
  membership before source resolution. The raw lists remain local-only and are not part of the clean
  snapshot.

## Findings
- **c.1100delC `22:28695868:AG:A`**
  - Array exact CPRA present: **NO** (no exact hit in the array resource).
  - Imputed exact CPRA present: **YES** — imputed resource line 151212952, `inaccurate.annotation=FALSE`.
- **I157T `22:28725099:A:G`**
  - Array exact CPRA present: **YES** — array resource line 652460, `Inaccurate Call=No`.
  - Imputed exact CPRA present: **YES** — imputed resource line 151214613, `inaccurate.annotation=FALSE`.
- **Fields the CPRA lists carry:** presence + ref/alt + an annotation-warning flag only. Imputation
  **DR2 / dosage-r² and AF live in the TRE variant summary-statistics file**, not the public CPRA list —
  so an *imputed-present* indel like c.1100delC is only as usable as its (TRE-only) DR2 allows.

## Implication for the demo (honesty)
- The opposite verdicts are **grounded in the real public lists**, not asserted: c.1100delC is genuinely
  array-absent, I157T is genuinely array-direct.
- What is **synthetic / illustrative**: the carrier counts (e.g. I157T → ~70 in the synthetic cohort),
  the DR2/quality values, and the cohort itself. For c.1100delC the array-absence is the decisive
  real-list fact; the "low-DR2 → NO-GO" reasoning uses a synthetic DR2 to stand in for the TRE
  summary-statistic an analyst would check.
- Clinical significance is **not** load-bearing in any of this: the verdicts follow allele availability
  and QC, not pathogenicity (see `docs/design-decisions.md`).

## Provenance
Derived from streaming the public Release 14 CPRA lists; line numbers and the source-file SHA-256 hashes
are recorded in `docs/reference/variant-identifiability-provenance.json`.
