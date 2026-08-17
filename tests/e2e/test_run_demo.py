"""End-to-end: write the tiny_cohort to disk, run orchestrate through io, assert the 4 artefacts
plus the governance behaviours (consent exclusion, SDC suppression, single airlock export)."""

import json

import pandas as pd
import pytest

from ofh_feasibility import pipeline
from ofh_feasibility.config import Config
from ofh_feasibility.models import VariantRequest

pytestmark = pytest.mark.e2e

CPRA = "10:119669928:C:G"


def _write_dataset(d, tiny_cohort):
    tiny_cohort["participants"].to_parquet(d / "participant_table.parquet", index=False)
    tiny_cohort["genotype_slice"].to_parquet(d / "genotype_slice.parquet", index=False)
    tiny_cohort["sample_qc"].to_csv(d / "sample_qc_metrics.tsv", sep="\t", index=False)
    pd.DataFrame([tiny_cohort["request"]]).to_csv(d / "variant_request.csv", index=False)
    pd.DataFrame(
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
                "inaccurate_annotation": "FALSE",
                "multiallelic_variant": "FALSE",
            }
        ]
    ).to_csv(d / "variant_manifest.csv", index=False)


@pytest.fixture
def run_dirs(tmp_path, tiny_cohort):
    data = tmp_path / "synthetic"
    data.mkdir()
    _write_dataset(data, tiny_cohort)
    cfg = Config.from_dict(
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
            data_dir=str(data),
            results_dir=str(tmp_path / "results"),
        )
    )
    request = VariantRequest.from_dict(tiny_cohort["request"])
    bundle = pipeline.orchestrate(cfg, request)
    return tmp_path, bundle


def test_produces_four_artefacts(run_dirs):
    tmp_path, _ = run_dirs
    results = tmp_path / "results"
    for name in (
        "internal_carrier_table.parquet",
        "handoff_to_epi.csv",
        "feasibility_summary.txt",
        "airlock_manifest.json",
    ):
        assert (results / name).exists(), name
    # only the Lean-emitted canonical payload is staged in the airlock-pending area
    assert (results / "airlock_pending" / "release.json").exists()
    assert not (results / "airlock_pending" / "feasibility_summary.txt").exists()


def test_withdrawn_carrier_excluded_in_internal_not_in_handoff(run_dirs, tiny_cohort):
    tmp_path, _ = run_dirs
    results = tmp_path / "results"
    withdrawn = tiny_cohort["expected"]["withdrawn"]
    internal = pd.read_parquet(results / "internal_carrier_table.parquet")
    row = internal[internal["participant_id"] == withdrawn].iloc[0]
    assert row["decision"] == "excluded" and row["reason"] == "consent_withdrawn"
    handoff = pd.read_csv(results / "handoff_to_epi.csv")
    assert "participant_id" not in handoff.columns and len(handoff) == 3


def test_sdc_and_summary(run_dirs):
    tmp_path, bundle = run_dirs
    summary = (tmp_path / "results" / "feasibility_summary.txt").read_text()
    assert "<10" in summary and "SUPPRESSED" in summary
    assert bundle["result"].breakdown_suppressed is True


def test_airlock_manifest_exactly_one_export(run_dirs):
    tmp_path, _ = run_dirs
    manifest = json.loads((tmp_path / "results" / "airlock_manifest.json").read_text())
    assert sum(f["export_to_client"] for f in manifest["files"]) == 1
    export = next(f for f in manifest["files"] if f["export_to_client"])
    assert export["file"] == "release.json" and export["human_readable"]


def test_audit_ledger_emitted_and_verifies(run_dirs):
    from ofh_feasibility import audit, io

    results = run_dirs[0] / "results"
    events = io.read_jsonl(results / "audit_ledger.jsonl")
    root = (results / "audit_root.txt").read_text().strip()
    assert len(events) == 1 and audit.verify_ledger(events, root)
    assert not any("participant_id" in str(e) for e in events)  # never participant-level data
