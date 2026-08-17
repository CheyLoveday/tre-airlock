# Data contracts

Nothing crosses a stage boundary untyped or unchecked. Boundary objects are **pydantic** models;
tabular inputs are pandas DataFrames validated against declared column schemas at the IO edge
(`require_columns`). The source of truth is the code: `src/ofh_feasibility/models.py`.

## Boundary models (`models.py`)
- `VariantRequest` (frozen, `extra="forbid"`) + `from_dict` — validates CPRA format/consistency,
  build, carrier-definition and source enums.
- `GeneRequest` and `DiseaseRequest` — catalogue-backed upstream genetic requests that resolve to the
  same governed batch/union path as explicit CPRAs.
- `BatchRequest` — a composite (multi-CPRA) request.
- `FeasibilityResult` (frozen) — the structured result (counts + SDC client figure + caveats +
  ancestry breakdown).
- `ReleaseCandidate` (frozen, `extra="forbid"`) — the **aggregate-only** release object; a
  participant-level field is structurally impossible. Mirrored by the Lean `ReleaseCandidate`.
- `Config` (`config.py`) — thresholds + paths; validators pin the consent gate hard and require
  `sdc_min_cell % sdc_round_to == 0`. DR2 thresholds use `imputed_dr2_*` names; historical
  `imputed_info_*` keys load as backward-compatible aliases.

## Upstream intake shape
`docs/reference/ofh-public-data-snapshot.md` captures the broader OFH public data-estate snapshot and a
suggested `FeasibilityIntake` Pydantic shape for the front door. That upstream model should remain a
triage/compilation boundary: validate the request, label documented-vs-suggested assumptions, then
compile to `VariantRequest`, `GeneRequest`, `DiseaseRequest`, `BatchRequest`, `EpiReturn`, and
`ReleaseCandidate`. The executed MVP stays on the narrower models so release logic remains simple and
testable.

## Tabular schemas (declared column tuples)
- `PARTICIPANT_COLUMNS`, `GENOTYPE_SLICE_COLUMNS`, `SAMPLE_QC_COLUMNS`, `VARIANT_MANIFEST_COLUMNS`.
- The manifest carries `dosage_r2` (OFH's imputation-quality metric — DR2, not a traditional INFO
  score), MAFs, annotation, and `on_array`/`on_imputed` resource-membership booleans. Those booleans
  mean "exact CPRA present in that resource"; they do not mean evidence was used after QC, and they do
  not encode DR2 quality.

## Metadata-first dictionaries
`entity_dictionary.csv`, `data_dictionary.csv`, `coding_dictionary.csv` — shaped to the real OFH
`v14` columns (`name`, `coding_name`, `primary_key_type`, `title`, `units`) and coding conventions
(`-999=Suppressed`, `-1/-3`). Simplifications are recorded in `docs/reference/missing-data.md`.

The full architecture rationale lives in the internal design notes; the committed record of decisions
is in `CHANGELOG.md`.
