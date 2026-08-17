"""Unit tests for classify: consent gate, evidence combination, confidence, reasons."""

import numpy as np
import pandas as pd
import pytest

from ofh_feasibility import classify, qc, sdc
from ofh_feasibility.config import Config

pytestmark = pytest.mark.unit


def _cfg(**over):
    base = dict(
        array_call_rate_min=0.98,
        array_gq_min=20,
        imputed_info_min=0.30,
        imputed_info_high_confidence=0.80,
        imputed_dosage_carrier_threshold=0.5,
        imputed_max_gp_min=0.90,
        carrier_definition="het_and_homalt",
        require_consent=True,
        sdc_min_cell=10,
        sdc_round_to=5,
        data_dir="d",
        results_dir="r",
    )
    return Config.from_dict({**base, **over})


def _cohort():
    # P0 clean array carrier (+kinship flag); P1 withdrawn carrier; P2 imputed-only conditional;
    # P3 borderline imputed (low max_gp); P4 low-array-call rescued by imputed; P5 non-carrier
    return pd.DataFrame(
        {
            "participant_id": ["P0", "P1", "P2", "P3", "P4", "P5"],
            "pseudo_id": ["a", "b", "c", "d", "e", "f"],
            "consent_status": [
                "consented",
                "withdrawn",
                "consented",
                "consented",
                "consented",
                "consented",
            ],
            "array_gt_code": [1.0, 1.0, np.nan, np.nan, 1.0, 0.0],
            "array_gq": [40.0, 40.0, np.nan, np.nan, 40.0, 40.0],
            "array_call_rate": [0.99, 0.99, np.nan, np.nan, 0.90, 0.99],
            "imputed_dosage": [1.0, 1.0, 1.0, 0.60, 1.0, 0.01],
            "imputed_max_gp": [0.95, 0.95, 0.95, 0.62, 0.95, 0.985],
            "sex_check_pass": [True, True, True, True, True, True],
            "kinship_flag": [True, False, False, False, False, False],
        }
    )


def _classify(cand, info=0.71, **cfg_over):
    cfg = _cfg(**cfg_over)
    return classify.classify_carriers(
        cand,
        qc.array_qc_mask(cand, cfg),
        qc.imputed_qc_mask(cand, cfg, info),
        qc.consent_mask(cand, cfg),
        qc.sample_flag_series(cand),
        cfg,
        info,
    )


def _row(df, pid):
    return df[df["participant_id"] == pid].iloc[0]


def test_non_carrier_dropped_from_candidates():
    out = _classify(_cohort())
    assert "P5" not in out["participant_id"].tolist()  # no alt evidence -> not a candidate
    assert len(out) == 5


def test_clean_array_carrier_is_included_high():
    r = _row(_classify(_cohort()), "P0")
    assert r["decision"] == "included" and r["confidence"] == "high"
    assert r["source"] == "array+imputed" and r["reason"] == ""
    assert r["flags"] == "related_pair"


def test_withdrawn_carrier_excluded_with_reason():
    out = _classify(_cohort())
    r = _row(out, "P1")
    assert r["decision"] == "excluded" and r["reason"] == "consent_withdrawn"
    # governance invariant: the withdrawn carrier is never in the included set
    assert "P1" not in out[out["decision"] == "included"]["participant_id"].tolist()
    assert r["source"] == "array+imputed"  # evidence recorded; governance still excludes


def test_imputed_only_is_conditional_under_moderate_info():
    r = _row(_classify(_cohort(), info=0.71), "P2")
    assert r["decision"] == "included" and r["confidence"] == "conditional"
    assert r["source"] == "imputed"


def test_imputed_only_high_info_is_high_confidence():
    r = _row(_classify(_cohort(), info=0.95), "P2")  # >= high-confidence cutoff 0.80
    assert r["confidence"] == "high"


def test_evidence_priority_tiers_typed_over_imputed():
    # Wave 3: the OFH evidence tier is finer than `confidence` (which merges array + high-DR2).
    out = _classify(_cohort(), info=0.71)
    assert _row(out, "P0")["evidence_priority"] == "array_direct"  # directly typed
    assert _row(out, "P2")["evidence_priority"] == "imputed_conditional"  # imputed, moderate DR2
    assert _row(out, "P1")["evidence_priority"] == "NA"  # excluded (withdrawn)
    # at high DR2 the same imputed-only carrier is imputed_high, NOT conflated with array_direct
    hi = _classify(_cohort(), info=0.95)
    assert _row(hi, "P2")["evidence_priority"] == "imputed_high"


def test_borderline_imputed_excluded_for_low_certainty():
    r = _row(_classify(_cohort()), "P3")
    assert r["decision"] == "excluded" and r["reason"] == "imputed_max_gp<0.9"
    assert r["source"] == "none"


def test_low_call_array_carrier_rescued_by_imputed_keeps_qc_reason():
    r = _row(_classify(_cohort()), "P4")
    assert r["decision"] == "included" and r["confidence"] == "conditional"
    assert r["source"] == "imputed" and r["reason"] == "array_call_rate<0.98"


def test_project_cells_matches_configured_classification():
    cfg = _cfg()
    out = _classify(_cohort())
    assert classify.project_cells(out, cfg, variant_info=0.71) == classify.count_cells(out)


def test_project_cells_recomputes_when_quality_cutoff_moves():
    cfg = _cfg()
    out = _classify(_cohort())
    assert classify.project_cells(out, cfg, variant_info=0.71)["total"] == 3
    relaxed = classify.project_cells(out, cfg, variant_info=0.71, imputed_max_gp_min=0.60)
    assert relaxed["total"] == 4
    assert relaxed["excluded"] == 1


def test_het_only_excludes_homalt_on_imputed_dosage():
    cand = pd.DataFrame({
        "participant_id": ["HET", "HOM"], "pseudo_id": ["h", "a"],
        "consent_status": ["consented", "consented"],
        "array_gt_code": [np.nan, np.nan], "array_gq": [np.nan, np.nan],
        "array_call_rate": [np.nan, np.nan], "imputed_dosage": [1.0, 2.0],
        "imputed_max_gp": [0.95, 0.95], "sex_check_pass": [True, True],
        "kinship_flag": [False, False],
    })
    out = _classify(cand, info=0.71, carrier_definition="het_only")
    assert "HET" in out["participant_id"].tolist()      # dosage ~1.0 -> het
    assert "HOM" not in out["participant_id"].tolist()   # dosage ~2.0 -> hom-alt, not het_only


def test_missing_array_genotype_recorded_in_reason():
    cand = pd.DataFrame({
        "participant_id": ["M"], "pseudo_id": ["m"], "consent_status": ["consented"],
        "array_gt_code": [-1.0], "array_gq": [0.0], "array_call_rate": [0.92],
        "imputed_dosage": [1.0], "imputed_max_gp": [0.95],
        "sex_check_pass": [True], "kinship_flag": [False],
    })
    r = _row(_classify(cand), "M")  # rescued by imputed, but the missing array call is recorded
    assert "array_genotype_missing" in r["reason"] and r["decision"] == "included"


def test_count_by_ancestry_included_only():
    classified = pd.DataFrame({
        "decision": ["included", "included", "included", "excluded"],
        "ancestry_stub": ["EUR", "EUR", "SAS", "AFR"],
    })
    # excluded AFR not counted
    assert classify.count_by_ancestry(classified) == {"EUR": 2, "SAS": 1}


def test_missing_ancestry_is_counted_as_sdc_stratum_and_suppresses():
    classified = pd.DataFrame({
        "decision": ["included"] * 11,
        "ancestry_stub": ["EUR"] * 10 + [np.nan],
    })
    counts = classify.count_by_ancestry(classified)
    assert counts == {"EUR": 10, "UNKNOWN": 1}

    out = sdc.apply_sdc_strata(counts, _cfg(), expected_total=11)
    assert out["suppressed"] is True
    assert out["reported"] == {}
    assert out["small_strata"] == ["UNKNOWN"]


def test_count_cells():
    cells = classify.count_cells(_classify(_cohort()))
    assert cells == {
        "high_confidence": 1,
        "conditional": 2,
        "total": 3,
        "excluded": 2,
        "flagged": 1,
    }
