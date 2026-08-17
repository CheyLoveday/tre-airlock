"""Unit tests for aggregate-only notebook/reviewer views."""

import pandas as pd
import pytest

from ofh_feasibility import pipeline, views
from ofh_feasibility.config import Config
from ofh_feasibility.models import VariantRequest

pytestmark = pytest.mark.unit

CPRA = "10:119669928:C:G"


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


def _manifest():
    return pd.DataFrame(
        [
            {
                "cpra": CPRA,
                "chrom": "10",
                "pos": "119669928",
                "ref": "C",
                "alt": "G",
                "build": "GRCh38",
                "biallelic": "TRUE",
                "on_array": "TRUE",
                "on_imputed": "TRUE",
                "array_maf": "0.013",
                "imputed_maf": "0.014",
                "dosage_r2": "0.71",
                "annotation": "bag3",
            }
        ]
    )


def _bundle(tiny_cohort):
    return pipeline.run_pipeline(
        _cfg(),
        VariantRequest.from_dict(tiny_cohort["request"]),
        _manifest(),
        tiny_cohort["participants"],
        tiny_cohort["genotype_slice"],
        tiny_cohort["sample_qc"],
    )


def _bundle_with_manifest(tiny_cohort, manifest):
    return pipeline.run_pipeline(
        _cfg(),
        VariantRequest.from_dict(tiny_cohort["request"]),
        manifest,
        tiny_cohort["participants"],
        tiny_cohort["genotype_slice"],
        tiny_cohort["sample_qc"],
    )


def _assert_no_id_columns(df):
    assert "participant_id" not in df.columns
    assert "pseudo_id" not in df.columns


def test_view_tables_are_aggregate_only(tiny_cohort):
    bundle = _bundle(tiny_cohort)
    for table in (
        views.funnel_table(bundle),
        views.source_decision_table(bundle),
        views.qc_breakdown_table(bundle),
        views.classification_table(bundle),
        views.gate_accounting_table(bundle),
        views.sdc_table(bundle["result"], bundle["release_candidate"]),
    ):
        _assert_no_id_columns(table)


def test_funnel_uses_client_sdc_token_not_exact_client_value(tiny_cohort):
    table = views.funnel_table(_bundle(tiny_cohort))
    client = table.loc[table["step"] == "Client count"].iloc[0]
    assert client["count"] == "<10"
    assert bool(client["client_visible"]) is True


def test_governance_view_reports_single_export_and_no_participant_export(tiny_cohort):
    gv = views.governance_view(_bundle(tiny_cohort))
    assert gv["single_export"] is True
    assert gv["airlock_export_files"] == ("release.json",)
    assert gv["participant_level_outputs_exported"] is False


def test_source_view_hides_synthetic_dr2_when_imputed_resource_absent(tiny_cohort):
    manifest = _manifest()
    manifest.loc[0, "on_imputed"] = "FALSE"
    table = views.source_decision_table(_bundle_with_manifest(tiny_cohort, manifest))
    assert table.loc[table["check"] == "Imputed evidence used", "value"].iloc[0] is False
    assert table.loc[table["check"] == "Imputed DR2", "value"].iloc[0] == "not used"
