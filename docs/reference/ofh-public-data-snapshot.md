# OFH public data snapshot and intake implications

Captured: 2026-06-16. Purpose: one concise reference for the public OFH data estate, the recruitment
feasibility workflow shape, and how that should inform this repo's Pydantic intake boundary.

This page separates three categories:

- **Documented public facts**: stated on OFH public researcher pages or public GitBook pages.
- **Repo implementation**: what this MVP currently runs end to end.
- **Suggested intake shape**: an operational schema inferred from the documented workflow and data
  domains, intended to compile into the existing concrete request models.

## Public data estate snapshot

The current public researcher pages describe OFH as a DNAnexus-hosted TRE with participant,
questionnaire, geography, clinic, genetic, ancestry, kinship, and linked-record assets. The release
numbers are asset-specific, so counts should be quoted with the asset name attached.

| Asset / domain | Public snapshot | Intake implication |
|---|---:|---|
| Baseline questionnaire | 2,021,810 participants | Eligibility logic may begin from self-reported baseline data. |
| Participant geographies | 1,983,038 participants | Geography filters should be explicit and coarsened for disclosure control. |
| NHS-number linkage | 1,690,704 linked participants | Linked-record phenotype requests need linkage availability as a separate gate. |
| At least one secondary-care / medication / death record | 1,666,336 participants | Phenotype feasibility should separate "linked" from "has relevant record type". |
| Clinic measurements | 1,518,202 participants | Clinic thresholds belong in a phenotype spec with units and time basis. |
| POCT lipid profile | 1,159,273 participants | Lipid requests should name POCT availability and historical collection window. |
| Genotype array | 686,416 variants across 755,000 participants | Variant feasibility must distinguish typed array evidence from imputed evidence. |
| Imputed genetics | 159,587,100 variants across the same 755,000 genetic participants | Imputed requests need DR2 / posterior-confidence thresholds and source caveats. |
| Genetic ancestry | 755,000 participants | Ancestry stratifiers require SDC and missing/unknown-stratum handling. |
| Genetic kinship | 755,000 genetic participants | Kinship filtering or stability checks are internal credibility controls. |

Notes:

- One public cohort summary line currently says 775,000 successfully genotyped/imputed participants,
  while the detailed genetic sections and the public researcher landing page state 755,000 for genotype
  array, imputed, and ancestry data. Share-facing docs should quote the asset-specific 755,000 genetic
  figure unless the Release 14 dictionary is rechecked and the discrepancy resolved.
- Public pages / snippets have also shown a questionnaire-version count discrepancy (`286` vs `288`
  questions for version 2). Treat exact questionnaire-item counts as dictionary-verified fields, not
  generic prose.
- ClinVar was not found in this public-source pass as a documented built-in OFH TRE dataset, package,
  or native Genomic Variant Browser annotation field. If a request depends on ClinVar, treat it as an
  external annotation dependency requiring explicit provenance and import/export review.

## Data domains to expose at intake

The public data estate implies an intake object with these field groups:

| Field group | Why it matters |
|---|---|
| Study metadata | Stable title, sponsor/contact, turnaround, and study summary for audit and service triage. |
| Access context | Recruitment feasibility, TRE data-access feasibility, or both; determines the governance path. |
| Target population | Plain-language inclusion/exclusion boundary before technical filters are added. |
| Phenotype logic | Questionnaire, clinic, lipid, linked-record, medication, cancer, death, and geography domains each need source and timing. |
| Genetic logic | Variant, gene, region, disease panel, PRS, ancestry, typed-vs-imputed acceptability, and inheritance/carrier model. |
| Operational filters | Age, sex, ethnicity, geography, ancestry, kinship/unrelatedness, contact/recontact constraints. |
| Time model | Baseline, prevalent, incident, lookback, follow-up, medication-window, or event-index rules. |
| Output request | Total count, overlap count, carrier count, stratified count, recontact estimate, or go/no-go assessment. |
| Governance flags | Recontact, small-cell risk, external collaborators, special approvals, likely Access Board escalation. |

## Pydantic use in this repo

Pydantic should sit at **boundaries**, not in inner loops:

1. Validate intake/config/release/return objects with `extra="forbid"`.
2. Normalise and fail early on malformed requests before data is read.
3. Compile broad intake into the narrow concrete models the pipeline already executes.
4. Keep pandas/NumPy transformations schema-checked at the IO edge, not per-row via Pydantic.

Current runtime boundary models live in `src/ofh_feasibility/models.py`:

- `VariantRequest`: exact CPRA request, build, source preference, carrier definition.
- `GeneRequest`: gene symbol request resolved through the catalogue.
- `DiseaseRequest`: disease/panel request resolved through the catalogue.
- `BatchRequest`: one or more concrete `VariantRequest` objects counted as a union carrier set.
- `EpiReturn`: aggregate-only downstream phenotype return.
- `ReleaseCandidate`: aggregate-only airlock release object.
- `HumanReviewCheckpoint`: named human-review decisions for intake / handoff / release gates.

The broad intake model below is a **suggested upstream schema**. It should compile into the concrete
models above rather than replacing them.

```python
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

RequestKind = Literal[
    "recruitment_feasibility",
    "data_access_feasibility",
    "variant_feasibility",
    "gene_region_feasibility",
    "prs_feasibility",
    "recall_by_genotype",
    "recall_by_phenotype",
    "linked_record_cohort_sizing",
]

GeneticBasis = Literal["typed_array", "imputed", "either", "none"]
OutputType = Literal[
    "total_count",
    "stratified_count",
    "overlap_count",
    "carrier_count",
    "recontact_estimate",
    "go_no_go_assessment",
]


class GeneticSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")

    feature_type: Literal["variant", "gene", "region", "panel", "prs", "ancestry", "none"] = "none"
    identifier: str | None = None
    typed_vs_imputed: GeneticBasis = "either"
    inheritance_model: Literal["carrier", "heterozygous", "homozygous", "additive", "any"] = "any"
    ancestry_restriction: tuple[str, ...] = ()


class PhenotypeSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source_domains: tuple[
        Literal[
            "questionnaire",
            "clinic_measurements",
            "poct_lipid_profile",
            "linked_primary_care_meds",
            "linked_hes_apc",
            "linked_hes_ed",
            "linked_hes_ecds",
            "linked_hes_outpatient",
            "linked_cancer",
            "linked_deaths",
            "geography",
        ],
        ...,
    ] = ()
    inclusion_logic: tuple[str, ...] = ()
    exclusion_logic: tuple[str, ...] = ()
    index_date_rule: str | None = None
    follow_up_rule: str | None = None


class FeasibilityIntake(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str
    request_kind: RequestKind
    study_summary: str
    recruitment_or_data_access: Literal["recruitment", "data_access", "both"]
    target_population: str
    phenotype: PhenotypeSpec = Field(default_factory=PhenotypeSpec)
    genetics: GeneticSpec = Field(default_factory=GeneticSpec)
    demographics: tuple[str, ...] = ()
    geography: tuple[str, ...] = ()
    stratifiers: tuple[str, ...] = ()
    minimum_cell_size: int | None = None
    output_type: OutputType
    needs_recontact: bool = False
    governance_notes: tuple[str, ...] = ()

    @model_validator(mode="after")
    def _genetic_request_has_identifier(self) -> "FeasibilityIntake":
        genetic_kinds = {
            "variant_feasibility",
            "gene_region_feasibility",
            "prs_feasibility",
            "recall_by_genotype",
        }
        if self.request_kind in genetic_kinds and not self.genetics.identifier:
            raise ValueError("genetic feasibility requests require genetics.identifier")
        return self
```

## Compile path into the MVP

The MVP should use broad intake only as a front door. The governed counting path stays narrow:

| Intake request | Compile target | Runtime path |
|---|---|---|
| Exact variant / CPRA | `VariantRequest` | `ofh-feasibility run` / Snakemake `extract -> qc -> classify -> report -> airlock`. |
| Gene | `GeneRequest` -> catalogue variants -> `BatchRequest` | `ofh-feasibility gene`, then the same governed batch/union path. |
| Disease/panel | `DiseaseRequest` -> catalogue variants -> `BatchRequest` | `ofh-feasibility disease`, then the same governed batch/union path. |
| Phenotype / linked-record eligibility | `EpiNotification` + `EpiReturn` | Genotype ceiling first; downstream aggregate return through `finalize-eligible`. |
| Release request | `ReleaseCandidate` | `authorize_release` and airlock manifest. |

That keeps the public-data-estate understanding visible without widening the executed MVP. The intake
model states the whole request shape; the current implementation executes the recall-by-genotype
variant/gene/panel family with governed outputs.

## Source links

- OFH data and cohort: https://research.ourfuturehealth.org.uk/data-and-cohort/
- OFH Clinical Research Recruitment Service: https://research.ourfuturehealth.org.uk/clinical-research-recruitment/
- OFH documentation hub: https://ourfuturehealth.gitbook.io/our-future-health
- DNAnexus OFH TRE docs: https://dnanexus.gitbook.io/ofh
