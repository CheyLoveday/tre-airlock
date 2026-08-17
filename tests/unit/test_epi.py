"""Unit tests for the Wave 8 epidemiology return loop: validate_epi_return + build_final_result."""
import pytest

from ofh_feasibility import airlock, epi
from ofh_feasibility.config import Config
from ofh_feasibility.models import EpiReturn, FeasibilityResult, VariantRequest

pytestmark = pytest.mark.unit

CPRA = "10:119669928:C:G"


def _cfg(**over):
    base = dict(
        array_call_rate_min=0.98, array_gq_min=20, imputed_info_min=0.30,
        imputed_info_high_confidence=0.80, imputed_dosage_carrier_threshold=0.5,
        imputed_max_gp_min=0.90, carrier_definition="het_and_homalt", require_consent=True,
        sdc_min_cell=10, sdc_round_to=5, data_dir="d", results_dir="r",
    )
    return Config.from_dict({**base, **over})


def _request(**over):
    base = dict(
        study_id="S1", cpra=CPRA, chrom="10", pos=119669928, ref="C", alt="G", build="GRCh38",
        carrier_definition="het_and_homalt", requested_source="array_and_imputed", purpose="t",
    )
    return VariantRequest.from_dict({**base, **over})


def _genotype_result(total=30):
    return FeasibilityResult(
        study_id="S1", cpra=CPRA, total_included=total, high_confidence=total, conditional=0,
        excluded=0, flagged=0, client_total=f"~{total}", breakdown_suppressed=False,
        assumptions=(), limitations=(),
    )


def _epi_return(**over):
    req = _request()
    base = dict(
        study_id="S1", cpra=CPRA, run_id=epi.expected_run_id(req), eligible_count=20,
        phenotype_definition_id="PD-HEART-1", icd10_codeset_label="ICD10-HD",
        icd10_codeset_version="2026-01", linked_record_scope="primary_care+hospital",
        reviewer="Dr Epi", return_timestamp="2026-06-09T10:00:00", sign_off_status="signed",
    )
    return EpiReturn.from_dict({**base, **over})


# --- validate_epi_return: fails closed on every mismatch -------------------------------------


def test_validate_epi_return_ok():
    epi.validate_epi_return(_epi_return(), _genotype_result(30), _request())  # no raise


def test_validate_epi_return_study_mismatch_fails():
    with pytest.raises(ValueError, match="study_id"):
        epi.validate_epi_return(_epi_return(study_id="OTHER"), _genotype_result(), _request())


def test_validate_epi_return_cpra_mismatch_fails():
    bad = _epi_return(cpra="10:121000000:A:T")
    with pytest.raises(ValueError, match="cpra"):
        epi.validate_epi_return(bad, _genotype_result(), _request())


def test_validate_epi_return_run_id_mismatch_fails():
    with pytest.raises(ValueError, match="run_id"):
        epi.validate_epi_return(_epi_return(run_id="RUN-WRONG"), _genotype_result(), _request())


def test_validate_epi_return_unsigned_fails():
    with pytest.raises(ValueError, match="signed"):
        epi.validate_epi_return(
            _epi_return(sign_off_status="pending_sign_off"), _genotype_result(), _request()
        )


def test_validate_epi_return_missing_phenotype_metadata_fails():
    with pytest.raises(ValueError, match="phenotype"):
        epi.validate_epi_return(
            _epi_return(phenotype_definition_id=""), _genotype_result(), _request()
        )


def test_validate_epi_return_exceeds_ceiling_fails_closed():
    # eligible (40) > genotype ceiling (30) -> must fail closed
    with pytest.raises(ValueError, match="exceeds the genotype ceiling"):
        epi.validate_epi_return(_epi_return(eligible_count=40), _genotype_result(30), _request())


def test_validate_epi_return_eligible_equal_to_ceiling_ok():
    epi.validate_epi_return(_epi_return(eligible_count=30), _genotype_result(30), _request())


def test_validate_epi_return_negative_count_rejected_by_model():
    # the model itself forbids a negative eligible count
    with pytest.raises(ValueError, match="non-negative"):
        _epi_return(eligible_count=-1)


def test_validate_epi_return_forbidden_identifier_fails():
    # a pseudo_id leaked into a caveat string must be caught (aggregate-only)
    leaky = _epi_return(caveats=("contact pseudo_id PSU-000003 for detail",))
    with pytest.raises(ValueError, match="forbidden identifier"):
        epi.validate_epi_return(leaky, _genotype_result(), _request())


@pytest.mark.parametrize(
    "caveat",
    [
        "contact PSU-000003 for detail",
        "contact psu-000003 for detail",
        "row OFH100003 needs review",
        "row ofh100003 needs review",
        "NHS-like value 1234567890 should not be here",
    ],
)
def test_validate_epi_return_bare_identifier_value_fails(caveat):
    leaky = _epi_return(caveats=(caveat,))
    with pytest.raises(ValueError, match="forbidden identifier"):
        epi.validate_epi_return(leaky, _genotype_result(), _request())


def test_epi_return_forbids_extra_participant_field():
    with pytest.raises(ValueError):  # pydantic extra="forbid"
        EpiReturn.from_dict({**_epi_return().model_dump(), "participant_id": "OFH100003"})


# --- build_final_result + the final release candidate ----------------------------------------


def test_build_final_result_carries_both_counts_sdc_applied():
    final = epi.build_final_result(_genotype_result(30), _epi_return(eligible_count=20), _cfg())
    assert final.genotype_total_included == 30 and final.post_phenotype_eligible == 20
    assert final.client_genotype_ceiling == "~30" and final.client_eligible == "~20"
    assert final.eligible_suppressed is False
    assert final.phenotype_definition_id == "PD-HEART-1"
    assert any("UPPER BOUND" in c for c in final.caveats)


def test_build_final_result_suppresses_small_eligible_count():
    final = epi.build_final_result(_genotype_result(30), _epi_return(eligible_count=8), _cfg())
    assert final.client_eligible == "<10" and final.eligible_suppressed is True


def test_final_release_candidate_uses_post_phenotype_count_and_passes_gate():
    final = epi.build_final_result(_genotype_result(30), _epi_return(eligible_count=20), _cfg())
    candidate = airlock.build_final_release_candidate(final, _cfg())
    assert candidate.client_total == "~20"  # the eligible count, NOT the genotype ceiling (~30)
    assert airlock.release_ok(candidate)  # passes the same fail-closed gate
    airlock.authorize_release(candidate)  # no raise
