"""Unit tests for WAVE_12 audience-tailored governed outputs."""

import pandas as pd
import pytest

from ofh_feasibility import airlock, audit, reporting, sdc
from ofh_feasibility.config import Config
from ofh_feasibility.models import BatchRequest, VariantRequest

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


def _result(total=20):
    cells = {
        "high_confidence": total,
        "conditional": 0,
        "total": total,
        "excluded": 2,
        "flagged": 0,
    }
    return reporting.build_result(_request(), cells, sdc.apply_sdc(cells, _cfg()), 0.91, _cfg())


def _candidate(result):
    cells = {
        "high_confidence": result.high_confidence,
        "conditional": result.conditional,
        "total": result.total_included,
        "excluded": result.excluded,
        "flagged": result.flagged,
    }
    return airlock.build_release_candidate(result, sdc.apply_sdc(cells, _cfg()), _cfg())


@pytest.mark.parametrize("audience", ["neutral", "research", "commercial"])
def test_audience_summaries_do_not_leak_identifier_shaped_values(audience):
    result = _result()
    text = reporting.build_audience_summary(
        audience, result, _request(), _cfg(), _candidate(result)
    )
    assert not audit.has_forbidden_pii({"summary": text})
    assert "participant_id" not in text
    assert "pseudo_id" not in text
    assert result.client_total in text


def test_commercial_funnel_suppresses_derived_sub_minimum_estimate():
    rows = reporting.build_recruitability_funnel(_result(total=20), _cfg())
    by_step = {row["step"]: row["value"] for row in rows}
    assert by_step["Genotype carrier ceiling"] == "~20"
    assert by_step["Illustrative response at 25%"] == "<10"
    assert by_step["Illustrative response at 50%"] == "~10"


def test_dr2_sensitivity_thresholds_derive_from_config():
    cfg = Config.from_dict(
        {
            **_cfg().model_dump(),
            "imputed_dr2_min": 0.60,
            "imputed_dr2_high_confidence": 0.90,
        }
    )

    sensitivity = reporting.build_quality_sensitivity(pd.DataFrame(), cfg, variant_info=0.91)

    assert [row["threshold"] for row in sensitivity["rows"]] == [
        "DR2 >= 0.60",
        "DR2 >= 0.75",
        "DR2 >= 0.90",
    ]


def test_data_factsheet_uses_release_candidate_reported_cells_only():
    result = _result(total=30)
    candidate = _candidate(result)
    facts = reporting.build_data_factsheet(result, _request(), _cfg(), candidate)
    assert facts["client_total"] == candidate.client_total
    assert facts["reported_cells"] == tuple(candidate.reported_cells)
    assert not audit.has_forbidden_pii(facts)


def test_batch_audience_summary_withholds_per_variant_and_overlap_counts():
    rows = [
        {**_request().model_dump(), "study_id": "PANEL"},
        {
            **_request().model_dump(),
            "study_id": "PANEL",
            "cpra": "22:28725099:A:G",
            "chrom": "22",
            "pos": 28725099,
            "ref": "A",
            "alt": "G",
        },
    ]
    batch = BatchRequest.from_rows(rows)
    combined = {
        "combined_client_total": "~20",
        "breakdown_suppressed": True,
        "per_variant": {"10:119669928:C:G": {"client": "<10"}},
    }
    text = reporting.build_batch_summary_for_audience("commercial", batch, combined, _cfg())
    assert "Released union carrier ceiling: ~20" in text
    assert "Per-variant and overlap counts are withheld" in text
    assert "10:119669928:C:G: <10" not in text
