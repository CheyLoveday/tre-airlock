"""Structured data types (pydantic) + tabular schema checks.

pydantic is confirmed available in the OFH TRE (ourfuturehealth/tre-package-access). Used for the
boundary models (request, result); never imported by the @njit kernels, which take NumPy arrays.
Iterate the exact fields once the real OFH data shapes are confirmed; this is a typed start.
"""
from __future__ import annotations

import re
from typing import Literal

from pydantic import BaseModel, ConfigDict, field_validator, model_validator

_CPRA_RE = re.compile(r"^(?:\d{1,2}|X|Y|MT):\d+:[ACGT]+:[ACGT]+$")

# Valid primary-assembly contigs and their GRCh38 lengths (bp). A request POS must be 1-based and
# within the named contig: a coordinate past the contig end is impossible and signals a wrong
# build/contig rather than a real locus. These are the cheap, first-gate checks that decide whether
# the pipeline should fire at all — a malformed CPRA must fail here, not later as "not in resource".
_VALID_CHROMS = {str(i) for i in range(1, 23)} | {"X", "Y", "MT"}
_GRCH38_CONTIG_LEN = {
    "1": 248956422, "2": 242193529, "3": 198295559, "4": 190214555, "5": 181538259,
    "6": 170805979, "7": 159345973, "8": 145138636, "9": 138394717, "10": 133797422,
    "11": 135086622, "12": 133275309, "13": 114364328, "14": 107043718, "15": 101991189,
    "16": 90338345, "17": 83257441, "18": 80373285, "19": 58617616, "20": 64444167,
    "21": 46709983, "22": 50818468, "X": 156040895, "Y": 57227415, "MT": 16569,
}


class VariantRequest(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    study_id: str
    cpra: str
    chrom: str
    pos: int
    ref: str
    alt: str
    build: Literal["GRCh38"]
    carrier_definition: Literal["het_and_homalt", "het_only"]
    requested_source: Literal["array", "imputed", "array_and_imputed"]
    purpose: str

    @field_validator("cpra")
    @classmethod
    def _cpra_format(cls, v: str) -> str:
        if not _CPRA_RE.match(v):
            raise ValueError(f"bad CPRA format: {v!r}")
        return v

    @field_validator("chrom")
    @classmethod
    def _chrom_is_contig(cls, v: str) -> str:
        if v not in _VALID_CHROMS:
            raise ValueError(f"invalid chromosome {v!r}; expected one of 1-22, X, Y, MT")
        return v

    @field_validator("pos")
    @classmethod
    def _pos_is_positive(cls, v: int) -> int:
        if v < 1:
            raise ValueError(f"POS must be a 1-based positive integer, got {v}")
        return v

    @model_validator(mode="after")
    def _cpra_consistent(self) -> VariantRequest:
        expected = f"{self.chrom}:{self.pos}:{self.ref}:{self.alt}"
        if self.cpra != expected:
            msg = f"CPRA {self.cpra!r} inconsistent with chrom/pos/ref/alt ({expected!r})"
            raise ValueError(msg)
        return self

    @model_validator(mode="after")
    def _alleles_describe_a_change(self) -> VariantRequest:
        # REF == ALT is a monomorphic site, not a variant — it can never be in a variant resource,
        # so it must fail at the boundary, not later as a misleading "not in resource".
        if self.ref == self.alt:
            raise ValueError(
                f"REF == ALT ({self.ref!r}): a request must describe an allele change, "
                f"not a monomorphic site"
            )
        return self

    @model_validator(mode="after")
    def _pos_within_contig(self) -> VariantRequest:
        contig_len = _GRCH38_CONTIG_LEN.get(self.chrom)
        if contig_len is not None and self.pos > contig_len:
            raise ValueError(
                f"POS {self.pos} exceeds the GRCh38 {self.chrom} length ({contig_len}); "
                f"coordinate out of range — check the build/contig"
            )
        return self

    @classmethod
    def from_dict(cls, data: dict) -> VariantRequest:
        return cls.model_validate(data)


class BatchRequest(BaseModel):
    """A multi-variant (composite risk-profile) request: several CPRAs assessed together."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    study_id: str
    purpose: str
    variants: tuple[VariantRequest, ...]

    @field_validator("variants")
    @classmethod
    def _variants_non_empty(cls, v: tuple[VariantRequest, ...]) -> tuple[VariantRequest, ...]:
        if not v:
            raise ValueError("batch request has no variants")
        return v

    @classmethod
    def from_rows(cls, rows: list[dict]) -> BatchRequest:
        if not rows:
            raise ValueError("batch request has no variants")
        variants = tuple(VariantRequest.from_dict(r) for r in rows)
        return cls(
            study_id=rows[0]["study_id"], purpose=rows[0].get("purpose", ""), variants=variants
        )


class GeneRequest(BaseModel):
    """A gene-level feasibility request resolved to a curated set of variant CPRAs."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    study_id: str
    symbol: str
    build: Literal["GRCh38"] = "GRCh38"
    requested_source: Literal["array", "imputed", "array_and_imputed"] = "array_and_imputed"
    purpose: str

    @field_validator("symbol")
    @classmethod
    def _normalise_symbol(cls, v: str) -> str:
        return v.strip().upper()


class DiseaseRequest(BaseModel):
    """A disease/panel-level feasibility request resolved to a curated demo gene panel."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    study_id: str
    panel: str
    build: Literal["GRCh38"] = "GRCh38"
    requested_source: Literal["array", "imputed", "array_and_imputed"] = "array_and_imputed"
    purpose: str

    @field_validator("panel")
    @classmethod
    def _normalise_panel(cls, v: str) -> str:
        return v.strip().lower()


class FeasibilityResult(BaseModel):
    model_config = ConfigDict(frozen=True)

    study_id: str
    cpra: str
    total_included: int
    high_confidence: int
    conditional: int
    excluded: int
    flagged: int
    client_total: str
    breakdown_suppressed: bool
    assumptions: tuple[str, ...]
    limitations: tuple[str, ...]
    # ancestry stratification (Wave 3): per-group rounded counts, or suppressed under SDC
    ancestry_suppressed: bool = False
    ancestry_breakdown: tuple[tuple[str, int], ...] = ()
    # evidence split (Wave 3): is the variant directly typed on the array (top evidence tier)?
    variant_on_array: bool = False
    # public-list resource membership for imputed evidence; separate from DR2 quality.
    variant_on_imputed: bool = False


class ReleaseCandidate(BaseModel):
    """The SOLE serializable release object (Wave 5 release gate).

    Aggregate only: it has NO participant-level fields, and `extra="forbid"` makes it structurally
    impossible to add any. `airlock.release_ok` enforces the disclosure-control predicates over it;
    the airlock export refuses any candidate that does not pass.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    study_id: str
    cpra: str
    client_total: str
    breakdown_suppressed: bool
    reported_cells: tuple[tuple[str, int], ...] = ()
    min_cell: int
    round_to: int


class EpiReturn(BaseModel):
    """The aggregate-only contract epidemiology returns after ICD-10 phenotype assessment (Wave 8).

    extra="forbid" makes it structurally impossible to inject a participant-level field; a deep
    identifier scan + the genotype-ceiling bound are enforced in epi.validate_epi_return.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    study_id: str
    cpra: str
    run_id: str
    eligible_count: int
    phenotype_definition_id: str
    icd10_codeset_label: str
    icd10_codeset_version: str
    linked_record_scope: str
    reviewer: str
    return_timestamp: str
    sign_off_status: Literal["signed", "pending_sign_off"]
    caveats: tuple[str, ...] = ()

    @field_validator("eligible_count")
    @classmethod
    def _non_negative(cls, v: int) -> int:
        if v < 0:
            raise ValueError("eligible_count must be non-negative")
        return v

    @classmethod
    def from_dict(cls, data: dict) -> EpiReturn:
        return cls.model_validate(data)


class FinalResult(BaseModel):
    """The post-phenotype final result (Wave 8): the genotype ceiling AND the epi eligible count,
    both SDC-applied, with the phenotype provenance. Internal; the airlock export is the
    Lean-authorised release payload."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    study_id: str
    cpra: str
    genotype_total_included: int
    post_phenotype_eligible: int
    client_genotype_ceiling: str
    client_eligible: str
    eligible_suppressed: bool
    phenotype_definition_id: str
    icd10_codeset_label: str
    icd10_codeset_version: str
    epi_reviewer: str
    epi_timestamp: str
    caveats: tuple[str, ...] = ()


class HumanReviewCheckpoint(BaseModel):
    """A named human visual-review decision at a governed pause point (Wave 8). A query/block
    decision halts the final release until resolved (enforced in the finalize orchestrator)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    checkpoint: Literal["intake", "pre_epi_handoff", "epi_return", "pre_airlock", "escalation"]
    reviewer: str
    timestamp: str
    artefacts_checked: tuple[str, ...]
    decision: Literal["pass", "query", "block"]
    notes: str = ""
    follow_up_owner: str | None = None

    @classmethod
    def from_dict(cls, data: dict) -> HumanReviewCheckpoint:
        return cls.model_validate(data)


class EpiNotification(BaseModel):
    """Internal-only rapid-turnaround intake/notification note (Wave 8): when the request was
    received, the ETA, the owner, and the current workflow state. Never client-exported."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    study_id: str
    cpra: str
    run_id: str
    received_timestamp: str
    workflow_state: Literal[
        "received", "genotype_running", "sent_to_epi", "awaiting_epi_return",
        "final_governance_review", "airlock_pending", "released",
    ]
    owner: str = "OFH recontact service"
    due_date: str = ""  # the requested turnaround / SLA date; supplied by the intake system
    eta: str = ""  # estimated genotype-feasibility delivery time; supplied by the intake system
    escalation_reason: str | None = None

    @classmethod
    def from_dict(cls, data: dict) -> EpiNotification:
        return cls.model_validate(data)


# Declared DataFrame column schemas (structured types for tabular data).
PARTICIPANT_COLUMNS = (
    "participant_id", "pseudo_id", "sex", "ancestry_stub", "consent_status", "baseline_qc_pass",
)
GENOTYPE_SLICE_COLUMNS = (
    "participant_id", "cpra", "source", "gt_code", "gq", "call_rate", "dosage", "max_gp",
)
SAMPLE_QC_COLUMNS = (
    "participant_id", "array_call_rate", "het_rate", "sex_check_pass",
    "ancestry_pc1", "ancestry_pc2", "kinship_flag",
)
# Variant summary-statistics manifest: availability + per-variant DR2/AF fields.
VARIANT_MANIFEST_COLUMNS = (
    "cpra", "chrom", "pos", "ref", "alt", "build", "biallelic", "on_array", "on_imputed",
    "array_maf", "imputed_maf", "dosage_r2", "annotation",
    # CPRA-list intake flags (Wave 7): an unreliable annotation or a multiallelic locus is a
    # fail-closed no-go at intake — see extract.validate_variant.
    "inaccurate_annotation", "multiallelic_variant",
)
VARIANT_IDENTIFIABILITY_COLUMNS = (
    "cpra", "on_array", "on_imputed", "annotation_reliable", "source_release", "evidence",
)


def require_columns(columns_present, columns_required, name: str) -> None:
    """Fail-fast schema check for a tabular input."""
    missing = [c for c in columns_required if c not in columns_present]
    if missing:
        raise ValueError(f"{name} missing columns: {missing}")
