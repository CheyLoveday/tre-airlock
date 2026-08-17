"""Unit tests for the airlock manifest builder + its governance invariant."""

import pytest

from ofh_feasibility import airlock
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
            purpose="t",
        )
    )


def test_default_files_have_exactly_one_export():
    files = airlock.default_airlock_files()
    assert sum(f["export_to_client"] for f in files) == 1
    export = next(f for f in files if f["export_to_client"])
    assert export["file"] == "release.json" and export["human_readable"]
    # the Python-rendered analyst summary is INTERNAL: client bytes come only from Lean.
    summary = next(f for f in files if f["file"] == "feasibility_summary.txt")
    assert summary["classification"] == "INTERNAL-TRE-ONLY" and not summary["export_to_client"]


def test_frequency_control_view_is_internal_and_blocked_from_export():
    files = airlock.default_airlock_files()
    fc = next(f for f in files if f["file"] == "frequency_control_view.json")
    assert fc["classification"] == "INTERNAL-TRE-ONLY" and fc["export_to_client"] is False
    # the inspector blocks it: marking it export must fail (it isn't an export candidate)
    fc["export_to_client"] = True
    with pytest.raises(ValueError, match="exactly one file may be export_to_client"):
        airlock.build_airlock_manifest(_request(), files, _cfg())  # now two exports
    files2 = airlock.default_airlock_files()
    files2 = [f for f in files2 if not f["export_to_client"]]  # drop the legit export
    next(f for f in files2 if f["file"] == "frequency_control_view.json")["export_to_client"] = True
    with pytest.raises(ValueError, match="classified AIRLOCK-EXPORT-CANDIDATE"):
        airlock.build_airlock_manifest(_request(), files2, _cfg())


def test_manifest_structure():
    m = airlock.build_airlock_manifest(_request(), airlock.default_airlock_files(), _cfg())
    assert m["study_id"] == "OFH-DEMO" and m["code_also_through_airlock"] is True
    criteria = m["airlock_four_criteria"]
    assert set(criteria) == {
        "aligned_with_approved_aims",
        "files_described_and_inspectable",
        "no_reidentification_or_confidentiality_risk",
        "technically_feasible",
    }
    assert criteria["files_described_and_inspectable"] is True
    assert criteria["technically_feasible"] is True
    assert "human airlock reviewer must attest" in criteria["aligned_with_approved_aims"]
    assert m["sdc"] == {"min_cell": 10, "round_to": 5}


def test_manifest_criteria_are_derived_from_file_descriptors():
    files = airlock.default_airlock_files()
    files[0].pop("reason")
    m = airlock.build_airlock_manifest(_request(), files, _cfg())
    assert m["airlock_four_criteria"]["files_described_and_inspectable"] is False
    assert m["airlock_four_criteria"]["technically_feasible"] is False


def test_manifest_rejects_more_than_one_export():
    files = airlock.default_airlock_files()
    files[0]["export_to_client"] = True  # now two export candidates
    with pytest.raises(ValueError, match="exactly one file may be export_to_client"):
        airlock.build_airlock_manifest(_request(), files, _cfg())


def test_manifest_rejects_zero_exports():
    files = [{**f, "export_to_client": False} for f in airlock.default_airlock_files()]
    with pytest.raises(ValueError, match="exactly one file may be export_to_client"):
        airlock.build_airlock_manifest(_request(), files, _cfg())


def test_manifest_rejects_non_human_readable_export():
    files = airlock.default_airlock_files()
    export = next(f for f in files if f["export_to_client"])
    export["human_readable"] = False
    with pytest.raises(ValueError, match="exported file must be human-readable"):
        airlock.build_airlock_manifest(_request(), files, _cfg())


def test_manifest_rejects_export_not_classified_as_candidate():
    files = airlock.default_airlock_files()
    export = next(f for f in files if f["export_to_client"])
    export["classification"] = "INTERNAL-TRE-ONLY"  # flag says export, classification says internal
    with pytest.raises(ValueError, match="classified AIRLOCK-EXPORT-CANDIDATE"):
        airlock.build_airlock_manifest(_request(), files, _cfg())


def test_manifest_rejects_internal_file_marked_export():
    # a single export, human-readable, BUT it is an INTERNAL-TRE-ONLY file -> blocked
    files = [
        {"file": "internal_carrier_table.parquet", "classification": "INTERNAL-TRE-ONLY",
         "export_to_client": True, "human_readable": True, "reason": "x"},
    ]
    with pytest.raises(ValueError, match="classified AIRLOCK-EXPORT-CANDIDATE"):
        airlock.build_airlock_manifest(_request(), files, _cfg())
