"""Unit tests for qc masks (pure, per-row booleans)."""
import numpy as np
import pandas as pd
import pytest

from ofh_feasibility import qc
from ofh_feasibility.config import Config

pytestmark = pytest.mark.unit


def _cfg(**over):
    base = dict(
        array_call_rate_min=0.98, array_gq_min=20, imputed_info_min=0.30,
        imputed_info_high_confidence=0.80, imputed_dosage_carrier_threshold=0.5,
        imputed_max_gp_min=0.90, carrier_definition="het_and_homalt", require_consent=True,
        sdc_min_cell=10, sdc_round_to=5, data_dir="d", results_dir="r",
    )
    return Config.from_dict({**base, **over})


def _cand():
    # P0 clean array+imputed; P1 low array call-rate; P2 low GQ; P3 imputed-only (no array)
    return pd.DataFrame({
        "participant_id": ["P0", "P1", "P2", "P3"],
        "consent_status": ["consented", "consented", "withdrawn", "consented"],
        "array_gt_code": [1.0, 1.0, 1.0, np.nan],
        "array_gq": [40.0, 40.0, 15.0, np.nan],
        "array_call_rate": [0.99, 0.90, 0.99, np.nan],
        "imputed_dosage": [1.0, 1.0, 1.0, 1.0],
        "imputed_max_gp": [0.95, 0.95, 0.95, 0.62],
        "sex_check_pass": [True, True, True, False],
        "kinship_flag": [False, True, False, False],
    })


def test_array_qc_mask_thresholds():
    m = qc.array_qc_mask(_cand(), _cfg())
    assert list(m) == [True, False, False, False]  # P1 low call-rate, P2 low GQ, P3 no array


def test_imputed_qc_mask_passes_above_floor():
    m = qc.imputed_qc_mask(_cand(), _cfg(), variant_info=0.71)
    assert list(m) == [True, True, True, False]  # P3 low max_gp (0.62 < 0.90)


def test_imputed_qc_mask_below_info_floor_all_false():
    assert not qc.imputed_qc_mask(_cand(), _cfg(), variant_info=0.10).any()
    assert not qc.imputed_qc_mask(_cand(), _cfg(), variant_info=None).any()


def test_consent_mask_gate():
    assert list(qc.consent_mask(_cand(), _cfg())) == [True, True, False, True]  # P2 withdrawn


def test_consent_gate_is_unconditional():
    # the gate ignores any require_consent flag: a withdrawn carrier is always excluded
    from types import SimpleNamespace

    fake_cfg = SimpleNamespace(require_consent=False)
    assert list(qc.consent_mask(_cand(), fake_cfg)) == [True, True, False, True]


def test_sample_flag_series():
    flags = qc.sample_flag_series(_cand())
    assert flags.tolist() == ["", "related_pair", "", "sample_sex_check_fail"]


def test_sample_flag_series_handles_string_booleans():
    # a sex-check fail stored as the string "FALSE" must NOT be read as truthy (a passing check)
    cand = _cand().copy()
    cand["sex_check_pass"] = ["TRUE", "TRUE", "TRUE", "FALSE"]
    cand["kinship_flag"] = ["FALSE", "TRUE", "FALSE", "FALSE"]
    flags = qc.sample_flag_series(cand)
    assert flags.tolist() == ["", "related_pair", "", "sample_sex_check_fail"]


def test_sample_flag_series_unknown_values_flag_for_review():
    cand = _cand().copy()
    cand["sex_check_pass"] = ["TRUE", "unknown", "TRUE", ""]
    cand["kinship_flag"] = ["FALSE", "", "maybe", "FALSE"]
    flags = qc.sample_flag_series(cand)
    assert flags.tolist() == [
        "",
        "sample_sex_check_fail;related_pair",
        "related_pair",
        "sample_sex_check_fail",
    ]


def test_gate_accounting_surfaces_each_boolean_gate():
    out = qc.gate_accounting(
        _cand(),
        _cfg(),
        variant_info=0.71,
        sources={
            "variant_on_array": True,
            "variant_on_imputed": True,
            "annotation_reliable": True,
            "use_array": True,
            "use_imputed": True,
        },
    )
    assert {
        "on_array",
        "on_imputed",
        "annotation_reliable",
        "array_source_allowed",
        "imputed_source_allowed",
        "call_rate_ok",
        "gq_ok",
        "dr2_ok",
        "max_gp_ok",
        "dosage_ok",
        "consent_ok",
        "array_credible",
        "imputed_credible",
        "included_by_configured_gates",
    }.issubset(out.columns)
    assert out["array_credible"].tolist() == [True, False, False, False]
    assert out["imputed_credible"].tolist() == [True, True, True, False]
    assert out["included_by_configured_gates"].tolist() == [True, True, False, False]
