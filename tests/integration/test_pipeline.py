"""Integration: the in-memory pipeline over the tiny_cohort fixture (stages interacting)."""

from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from ofh_feasibility import pipeline
from ofh_feasibility.config import Config
from ofh_feasibility.models import ReleaseCandidate, VariantRequest

pytestmark = pytest.mark.integration

CPRA = "10:119669928:C:G"
_REQUEST = dict(
    study_id="S", cpra=CPRA, chrom="10", pos=119669928, ref="C", alt="G", build="GRCh38",
    carrier_definition="het_and_homalt", requested_source="array_and_imputed", purpose="t",
)


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


def _run(tiny_cohort):
    return pipeline.run_pipeline(
        _cfg(),
        VariantRequest.from_dict(tiny_cohort["request"]),
        _manifest(),
        tiny_cohort["participants"],
        tiny_cohort["genotype_slice"],
        tiny_cohort["sample_qc"],
    )


def test_counts_reconcile(tiny_cohort):
    cells = _run(tiny_cohort)["cells"]
    # carriers {3,7,11,15}; 7 withdrawn -> excluded; 15 imputed-only -> conditional; 3,11 -> high
    assert cells == {
        "high_confidence": 2,
        "conditional": 1,
        "total": 3,
        "excluded": 1,
        "flagged": 0,
    }


def test_withdrawn_carrier_excluded_not_handed_off(tiny_cohort):
    bundle = _run(tiny_cohort)
    withdrawn = tiny_cohort["expected"]["withdrawn"]  # OFH100007
    internal = bundle["internal"]
    row = internal[internal["participant_id"] == withdrawn].iloc[0]
    assert row["decision"] == "excluded" and row["reason"] == "consent_withdrawn"
    # never in the included handoff (pseudonymised); 3 included carriers handed off
    assert len(bundle["handoff"]) == 3


def test_sdc_suppresses_small_cohort(tiny_cohort):
    result = _run(tiny_cohort)["result"]
    assert result.client_total == "<10" and result.breakdown_suppressed is True


def test_kernel_reconciles_post_consent_array_direct_carriers(tiny_cohort):
    # array-direct carriers passing QC + consent: {3, 11}; withdrawn {7} is not included.
    bundle = _run(tiny_cohort)
    assert bundle["kernel_counts"] == (2, 2, 0)
    pandas_count = int(
        (
            (bundle["classified"]["decision"] == "included")
            & (bundle["classified"]["evidence_priority"] == "array_direct")
        ).sum()
    )
    assert bundle["kernel_counts"][0] == pandas_count


def test_airlock_manifest_single_export(tiny_cohort):
    files = _run(tiny_cohort)["airlock_manifest"]["files"]
    assert sum(f["export_to_client"] for f in files) == 1


def _solo_array_carrier():
    """One clean array-direct carrier (gt=1) with NO imputed evidence — isolates array gating."""
    participants = pd.DataFrame({
        "participant_id": ["P0"], "pseudo_id": ["a"], "sex": ["M"], "ancestry_stub": ["EUR"],
        "consent_status": ["consented"], "baseline_qc_pass": [True],
    })
    gs = pd.DataFrame([{
        "participant_id": "P0", "cpra": CPRA, "source": "array", "gt_code": 1, "gq": 40,
        "call_rate": 0.99, "dosage": np.nan, "max_gp": np.nan,
    }])
    sqc = pd.DataFrame({
        "participant_id": ["P0"], "array_call_rate": [0.99], "het_rate": [0.25],
        "sex_check_pass": [True], "ancestry_pc1": [0.0], "ancestry_pc2": [0.0],
        "kinship_flag": [False],
    })
    return participants, gs, sqc


def test_f2_imputed_only_request_excludes_array_carrier():
    # requested_source="imputed" -> use_array=False -> an array-only carrier must NOT be counted.
    participants, gs, sqc = _solo_array_carrier()
    req = VariantRequest.from_dict({**_REQUEST, "requested_source": "imputed"})
    cells = pipeline.run_pipeline(_cfg(), req, _manifest(), participants, gs, sqc)["cells"]
    assert cells["total"] == 0


def test_f2_on_array_false_excludes_array_carrier():
    # manifest on_array=FALSE -> the variant is not directly typed -> array evidence is unusable.
    participants, gs, sqc = _solo_array_carrier()
    manifest = _manifest()
    manifest.loc[0, "on_array"] = "FALSE"
    bundle = pipeline.run_pipeline(
        _cfg(), VariantRequest.from_dict(_REQUEST), manifest, participants, gs, sqc
    )
    cells = bundle["cells"]
    assert cells["total"] == 0
    assert bundle["preflight"]["requested_sources_available"] is False
    assert any(
        "array-direct evidence is unavailable" in c
        for c in bundle["preflight"]["source_caveats"]
    )


def test_f2_array_and_imputed_request_still_counts_array_carrier():
    # control: the default request DOES use array -> the same carrier is counted (no over-gating).
    participants, gs, sqc = _solo_array_carrier()
    cells = pipeline.run_pipeline(
        _cfg(), VariantRequest.from_dict(_REQUEST), _manifest(), participants, gs, sqc
    )["cells"]
    assert cells["total"] == 1


def test_pipeline_rejects_carrier_definition_mismatch(tiny_cohort):
    # request says het_and_homalt; config says het_only -> fail fast (count vs note can't diverge)
    cfg = Config.from_dict({
        **dict(
            array_call_rate_min=0.98, array_gq_min=20, imputed_info_min=0.30,
            imputed_info_high_confidence=0.80, imputed_dosage_carrier_threshold=0.5,
            imputed_max_gp_min=0.90, require_consent=True, sdc_min_cell=10, sdc_round_to=5,
            data_dir="d", results_dir="r",
        ),
        "carrier_definition": "het_only",
    })
    with pytest.raises(ValueError, match="carrier_definition mismatch"):
        pipeline.run_pipeline(
            cfg, VariantRequest.from_dict(tiny_cohort["request"]), _manifest(),
            tiny_cohort["participants"], tiny_cohort["genotype_slice"], tiny_cohort["sample_qc"],
        )


def test_write_outputs_authorizes_before_any_client_shaped_write(tmp_path):
    cfg = _cfg().model_copy(update={"results_dir": str(tmp_path / "results")})
    bad_candidate = ReleaseCandidate(
        study_id="S",
        cpra=CPRA,
        client_total="~23",
        breakdown_suppressed=True,
        reported_cells=(),
        min_cell=10,
        round_to=5,
    )
    bundle = {
        "internal": pd.DataFrame(),
        "handoff": pd.DataFrame(),
        "frequency_control": {},
        "release_candidate": bad_candidate,
        "summary": "CLIENT SUMMARY SHOULD NOT BE WRITTEN",
        "airlock_manifest": {},
    }

    with pytest.raises(ValueError, match="release refused"):
        pipeline.write_outputs(bundle, cfg)

    assert not (Path(cfg.results_dir) / pipeline.SUMMARY).exists()
    # Lean refusal: NO releasable payload reaches the egress-pending path (fail closed).
    pending = Path(cfg.results_dir) / pipeline.AIRLOCK_PENDING
    assert not (pending / pipeline.RELEASE_PAYLOAD).exists()
    assert not (pending / pipeline.SUMMARY).exists()
