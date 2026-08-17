"""Unit tests for reporting builders (result, internal table, epi handoff, client summary)."""

import numpy as np
import pandas as pd
import pytest

from ofh_feasibility import classify, reporting, sdc
from ofh_feasibility.config import Config
from ofh_feasibility.models import VariantRequest

pytestmark = pytest.mark.unit


def _cfg():
    return Config.from_dict(
        dict(
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
    )


def _request():
    return VariantRequest.from_dict(
        dict(
            study_id="OFH-DEMO",
            cpra="10:119669928:C:G",
            chrom="10",
            pos=119669928,
            ref="C",
            alt="G",
            build="GRCh38",
            carrier_definition="het_and_homalt",
            requested_source="array_and_imputed",
            purpose="recontact feasibility",
        )
    )


def _classified():
    return pd.DataFrame(
        {
            "participant_id": ["C0", "C1", "C2"],
            "pseudo_id": ["PSU-0", "PSU-1", "PSU-2"],
            "consent_status": ["consented", "consented", "withdrawn"],
            "source": ["array+imputed", "imputed", "array+imputed"],
            "array_gt_code": [1.0, np.nan, 1.0],
            "array_gq": [40.0, np.nan, 40.0],
            "array_call_rate": [0.99, np.nan, 0.99],
            "imputed_dosage": [1.0, 1.0, 1.0],
            "imputed_max_gp": [0.95, 0.95, 0.95],
            "confidence": ["high", "conditional", "NA"],
            "evidence_priority": ["array_direct", "imputed_conditional", "NA"],
            "decision": ["included", "included", "excluded"],
            "reason": ["", "", "consent_withdrawn"],
            "flags": ["", "related_pair", ""],
            "variant_info": [0.71, 0.71, 0.71],
        }
    )


def test_build_result_fields():
    cl = _classified()
    cells = classify.count_cells(cl)
    out = sdc.apply_sdc(cells, _cfg())
    result = reporting.build_result(_request(), cells, out, 0.71, _cfg())
    assert result.total_included == 2 and result.high_confidence == 1 and result.conditional == 1
    assert result.excluded == 1 and result.client_total == "<10" and result.breakdown_suppressed
    assert isinstance(result.assumptions, tuple) and result.limitations  # caveats populated


def test_internal_table_keeps_ids_and_provenance():
    t = reporting.build_internal_table(_classified())
    assert "participant_id" in t.columns and "reason" in t.columns
    assert len(t) == 3  # all candidates incl. the excluded withdrawn carrier (auditable)


def test_epi_handoff_is_pseudonymised_included_only():
    h = reporting.build_epi_handoff(_classified())
    assert "participant_id" not in h.columns  # least privilege: no IDs in the handoff
    assert list(h["pseudo_id"]) == ["PSU-0", "PSU-1"]  # included only (C2 withdrawn dropped)
    assert "imputed-supported" in h.loc[1, "caveat"] and "related_pair" in h.loc[1, "caveat"]
    # the named evidence tier travels with the handoff (Wave 3): typed-direct vs imputed
    assert list(h["evidence_priority"]) == ["array_direct", "imputed_conditional"]


def test_final_summary_distinguishes_ceiling_from_eligible():
    from ofh_feasibility import epi
    from ofh_feasibility.models import EpiReturn

    geno = reporting.build_result(
        _request(), {"total": 30, "high_confidence": 30, "conditional": 0, "excluded": 0,
                     "flagged": 0}, sdc.apply_sdc(
            {"total": 30, "high_confidence": 30, "conditional": 0, "excluded": 0, "flagged": 0},
            _cfg()), 0.71, _cfg(),
    )
    epi_return = EpiReturn.from_dict(dict(
        study_id=geno.study_id, cpra=geno.cpra, run_id=epi.expected_run_id(_request()),
        eligible_count=20,
        phenotype_definition_id="PD-1", icd10_codeset_label="ICD10-HD", icd10_codeset_version="v1",
        linked_record_scope="primary_care", reviewer="Dr Epi",
        return_timestamp="2026-06-09T10:00:00", sign_off_status="signed",
    ))
    final = epi.build_final_result(geno, epi_return, _cfg())
    text = reporting.build_final_summary(final, _request(), _cfg())
    assert "GENOTYPE FEASIBILITY (upper bound / ceiling)" in text
    assert "POST-PHENOTYPE ELIGIBLE CARRIERS (the FINAL figure)" in text
    assert "ICD10-HD" in text and "Dr Epi" in text
    assert "RECOMMENDATION: GO" in text


def test_summary_suppressed_does_not_leak_ids_and_recommends():
    cl = _classified()
    cells = classify.count_cells(cl)
    result = reporting.build_result(_request(), cells, sdc.apply_sdc(cells, _cfg()), 0.71, _cfg())
    text = reporting.build_feasibility_summary(result, _request(), _cfg())
    assert "SUPPRESSED" in text and "<10" in text
    assert "RECOMMENDATION: GO WITH CAVEATS" in text
    for pid in ("C0", "C1", "C2", "PSU-0"):
        assert pid not in text  # only aggregates in the client note


def test_summary_shows_breakdown_when_large():
    cells = {"high_confidence": 25, "conditional": 15, "total": 40, "excluded": 3, "flagged": 2}
    result = reporting.build_result(_request(), cells, sdc.apply_sdc(cells, _cfg()), 0.71, _cfg())
    text = reporting.build_feasibility_summary(result, _request(), _cfg())
    assert "~40" in text and "~25" in text and "~15" in text and "SUPPRESSED" not in text


def test_summary_shows_ancestry_when_groups_large():
    cells = {"high_confidence": 25, "conditional": 15, "total": 40, "excluded": 3, "flagged": 2}
    ancestry = sdc.apply_sdc_strata({"EUR": 25, "SAS": 15}, _cfg())
    result = reporting.build_result(
        _request(), cells, sdc.apply_sdc(cells, _cfg()), 0.71, _cfg(), ancestry
    )
    text = reporting.build_feasibility_summary(result, _request(), _cfg())
    assert "Ancestry breakdown" in text and "EUR: ~25" in text and "SAS: ~15" in text


def test_summary_suppresses_ancestry_when_a_group_is_small():
    cells = {"high_confidence": 25, "conditional": 15, "total": 40, "excluded": 0, "flagged": 0}
    ancestry = sdc.apply_sdc_strata({"EUR": 38, "SAS": 2}, _cfg())  # SAS below min
    result = reporting.build_result(
        _request(), cells, sdc.apply_sdc(cells, _cfg()), 0.71, _cfg(), ancestry
    )
    assert "Ancestry breakdown: SUPPRESSED" in reporting.build_feasibility_summary(
        result, _request(), _cfg()
    )


def test_indel_array_absent_caveat_reaches_summary():
    request = VariantRequest.from_dict({
        **_request().model_dump(),
        "cpra": "22:28695868:AG:A",
        "chrom": "22",
        "pos": 28695868,
        "ref": "AG",
        "alt": "A",
    })
    cells = {"high_confidence": 0, "conditional": 0, "total": 0, "excluded": 0, "flagged": 0}
    result = reporting.build_result(
        request,
        cells,
        sdc.apply_sdc(cells, _cfg()),
        0.18,
        _cfg(),
        variant_on_array=False,
    )
    text = reporting.build_feasibility_summary(result, request, _cfg())
    assert "indel not directly typed on the array" in text
    assert "below configured floor 0.3" in text


def test_summary_distinguishes_imputed_absent_from_low_dr2():
    cells = {"high_confidence": 12, "conditional": 0, "total": 12, "excluded": 0, "flagged": 0}
    result = reporting.build_result(
        _request(),
        cells,
        sdc.apply_sdc(cells, _cfg()),
        0.71,
        _cfg(),
        variant_on_array=True,
        variant_on_imputed=False,
    )
    text = reporting.build_feasibility_summary(result, _request(), _cfg())
    assert "variant in OFH imputed resource: no" in text
    assert "absent from the imputed public variant list" in text
    assert "DR2) = 0.71" not in text


def test_frequency_control_kinship_string_false_is_not_truthy():
    candidate = pd.DataFrame(
        {
            "participant_id": [f"P{i}" for i in range(10)],
                "sex": ["F"] * 10,
                "ancestry_stub": ["EUR"] * 10,
                "array_gt_code": [0, 1] * 5,
                "imputed_dosage": [np.nan] * 10,
                "kinship_flag": ["FALSE"] * 10,
            }
        )
    out = reporting.build_frequency_control(
        candidate, np.ones(len(candidate), dtype=bool), _request(), _cfg()
    )
    assert out["kinship_stability"]["n_related_excluded"] == 0


def test_render_markdown_report():
    cl = _classified()
    cells = classify.count_cells(cl)
    result = reporting.build_result(_request(), cells, sdc.apply_sdc(cells, _cfg()), 0.71, _cfg())
    md = reporting.render_markdown_report(result, _request(), _cfg())
    assert md.startswith("# Genotype feasibility — OFH-DEMO")
    assert "## Recommendation" in md and "## Caveats" in md
    assert result.client_total in md                  # the SDC-applied client figure
    for pid in ("C0", "C1", "C2", "PSU-0"):
        assert pid not in md                          # no participant IDs in the report


def test_summary_no_go_when_zero_included():
    cells = {"high_confidence": 0, "conditional": 0, "total": 0, "excluded": 5, "flagged": 0}
    result = reporting.build_result(_request(), cells, sdc.apply_sdc(cells, _cfg()), 0.71, _cfg())
    assert "RECOMMENDATION: NO-GO" in reporting.build_feasibility_summary(
        result, _request(), _cfg()
    )


def test_summary_surfaces_configured_quality_cutoffs():
    cells = {"high_confidence": 25, "conditional": 15, "total": 40, "excluded": 3, "flagged": 2}
    result = reporting.build_result(_request(), cells, sdc.apply_sdc(cells, _cfg()), 0.71, _cfg())
    text = reporting.build_feasibility_summary(result, _request(), _cfg())
    assert "QUALITY CUT-OFFS" in text
    assert "Array call rate >= 0.98" in text
    assert "Imputed variant DR2 >= 0.3" in text


def test_quality_sensitivity_suppresses_sub_minimum_movements():
    cl = _classified()
    out = reporting.build_quality_sensitivity(cl, _cfg(), variant_info=0.71)
    assert out["suppressed"] is True
    assert out["rows"] == ()


def test_quality_sensitivity_reports_sdc_tokens_when_movements_are_safe():
    cl = pd.concat([_classified()] * 20, ignore_index=True)
    out = reporting.build_quality_sensitivity(cl, _cfg(), variant_info=0.91)
    assert out["suppressed"] is False
    assert {row["client_total"] for row in out["rows"]} == {"~40"}
