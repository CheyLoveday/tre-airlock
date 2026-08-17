"""epi — pure core for the epidemiology return loop (Wave 8).

The genotype pipeline hands epidemiology a pseudonymised carrier set + an upper-bound (ceiling)
count; epidemiology owns the ICD-10 phenotype adjudication (NOT run here) and returns an AGGREGATE
eligible count. This module validates that returned aggregate against the genotype run
(fail-closed) and builds the final post-phenotype result. No IO; deterministic.

Governance: the return is aggregate-only (no participant/pseudo IDs, no linked-health rows), the
eligible count may not exceed the genotype ceiling, and the final count goes through the same SDC +
airlock release gate as the genotype count.
"""

from __future__ import annotations

import hashlib
import json
from typing import TYPE_CHECKING

from . import audit, sdc
from .models import FinalResult

if TYPE_CHECKING:
    from .config import Config
    from .models import EpiReturn, FeasibilityResult, VariantRequest


def build_run_id(request: VariantRequest, provenance: dict | None = None) -> str:
    """Stable non-identifying run/handoff id for matching an epi return to this run.

    The orchestrated path includes config + input hashes so an epi return cannot be reused silently
    against a different data/config run for the same study and CPRA. Unit-level validation can omit
    provenance and still gets a deterministic request-scoped identifier.
    """
    payload = {"study_id": request.study_id, "cpra": request.cpra}
    if provenance:
        payload["config_sha256"] = provenance.get("config_sha256", "")
        payload["input_sha256"] = provenance.get("input_sha256", {})
    digest = hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()
    return f"RUN-{digest[:12]}"


def expected_run_id(request: VariantRequest, provenance: dict | None = None) -> str:
    """Backward-compatible name for the expected non-identifying run/handoff id."""
    return build_run_id(request, provenance)


def validate_epi_return(
    epi_return: EpiReturn,
    genotype_result: FeasibilityResult,
    request: VariantRequest,
    expected_run_id: str | None = None,
) -> None:
    """Fail closed unless the epi return matches the run, is signed off, carries phenotype metadata,
    is a non-negative integer not exceeding the genotype ceiling, and carries no identifiers."""
    if epi_return.study_id != request.study_id:
        raise ValueError(
            f"epi return study_id {epi_return.study_id!r} != request {request.study_id!r}"
        )
    if epi_return.cpra != request.cpra:
        raise ValueError(f"epi return cpra {epi_return.cpra!r} != request {request.cpra!r}")
    expected = expected_run_id or build_run_id(request)
    if epi_return.run_id != expected:
        raise ValueError(
            f"epi return run_id {epi_return.run_id!r} != expected "
            f"{expected!r}"
        )
    if epi_return.sign_off_status != "signed":
        raise ValueError("epi return is not signed off — query epi (sign_off_status != 'signed')")
    if not epi_return.phenotype_definition_id or not epi_return.icd10_codeset_label:
        raise ValueError("epi return missing phenotype / ICD-10 code-set metadata — query epi")
    if epi_return.eligible_count > genotype_result.total_included:
        raise ValueError(
            f"epi return eligible_count {epi_return.eligible_count} exceeds the genotype ceiling "
            f"{genotype_result.total_included} — fails closed (post-phenotype <= ceiling)"
        )
    if audit.has_forbidden_pii(epi_return.model_dump()):
        raise ValueError("epi return contains a forbidden identifier — aggregate-only required")


def build_final_result(
    genotype_result: FeasibilityResult, epi_return: EpiReturn, cfg: Config
) -> FinalResult:
    """Assemble the final post-phenotype result: the SDC-applied genotype ceiling AND eligible.

    Caller must validate the return first (validate_epi_return). The eligible count is a single
    aggregate, so SDC is a total suppression (no breakdown); both figures use the same parameters.
    """
    ceiling = sdc.suppress_total(genotype_result.total_included, cfg)
    eligible = sdc.suppress_total(epi_return.eligible_count, cfg)
    caveats = (
        "The genotype count is an UPPER BOUND (ceiling); the post-phenotype eligible count is the "
        "figure for recruitment after ICD-10 assessment by epidemiology.",
        f"Phenotype: {epi_return.phenotype_definition_id} (ICD-10 "
        f"{epi_return.icd10_codeset_label} {epi_return.icd10_codeset_version}); "
        f"linked-record scope: {epi_return.linked_record_scope}.",
        f"Epidemiology sign-off: {epi_return.reviewer} at {epi_return.return_timestamp}.",
        *epi_return.caveats,
        f"Disclosure control (min cell {cfg.sdc_min_cell}, round to {cfg.sdc_round_to}) applied to "
        "both the genotype ceiling and the post-phenotype eligible count.",
    )
    return FinalResult(
        study_id=genotype_result.study_id,
        cpra=genotype_result.cpra,
        genotype_total_included=genotype_result.total_included,
        post_phenotype_eligible=epi_return.eligible_count,
        client_genotype_ceiling=ceiling["client_total"],
        client_eligible=eligible["client_total"],
        eligible_suppressed=eligible["suppressed"],
        phenotype_definition_id=epi_return.phenotype_definition_id,
        icd10_codeset_label=epi_return.icd10_codeset_label,
        icd10_codeset_version=epi_return.icd10_codeset_version,
        epi_reviewer=epi_return.reviewer,
        epi_timestamp=epi_return.return_timestamp,
        caveats=caveats,
    )
