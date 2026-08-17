"""Integration: the Wave 8 finalize-eligible round trip (genotype ceiling -> post-phenotype)."""
import pandas as pd
import pytest

from ofh_feasibility import audit, epi, io, pipeline
from ofh_feasibility.config import Config
from ofh_feasibility.models import EpiReturn, HumanReviewCheckpoint, VariantRequest

pytestmark = pytest.mark.integration

CPRA = "10:119669928:C:G"
_MANIFEST_ROW = {
    "cpra": CPRA, "chrom": "10", "pos": "119669928", "ref": "C", "alt": "G", "build": "GRCh38",
    "biallelic": "TRUE", "on_array": "TRUE", "on_imputed": "TRUE", "array_maf": "0.013",
    "imputed_maf": "0.014", "dosage_r2": "0.71", "annotation": "bag3",
    "inaccurate_annotation": "FALSE", "multiallelic_variant": "FALSE",
}


def _cfg(data, results):
    return Config.from_dict(dict(
        array_call_rate_min=0.98, array_gq_min=20, imputed_info_min=0.30,
        imputed_info_high_confidence=0.80, imputed_dosage_carrier_threshold=0.5,
        imputed_max_gp_min=0.90, carrier_definition="het_and_homalt", require_consent=True,
        sdc_min_cell=10, sdc_round_to=5, data_dir=str(data), results_dir=str(results),
    ))


def _write_inputs(d, tiny_cohort):
    tiny_cohort["participants"].to_parquet(d / "participant_table.parquet", index=False)
    tiny_cohort["genotype_slice"].to_parquet(d / "genotype_slice.parquet", index=False)
    tiny_cohort["sample_qc"].to_csv(d / "sample_qc_metrics.tsv", sep="\t", index=False)
    pd.DataFrame([tiny_cohort["request"]]).to_csv(d / "variant_request.csv", index=False)
    pd.DataFrame([_MANIFEST_ROW]).to_csv(d / "variant_manifest.csv", index=False)


def _epi_return(**over):
    request = VariantRequest.from_dict({**over.pop("_request", {})} or {
        "study_id": "TEST", "cpra": CPRA, "chrom": "10", "pos": 119669928, "ref": "C", "alt": "G",
        "build": "GRCh38", "carrier_definition": "het_and_homalt",
        "requested_source": "array_and_imputed", "purpose": "test",
    })
    base = dict(
        study_id=request.study_id, cpra=request.cpra, run_id=epi.expected_run_id(request),
        eligible_count=2,
        phenotype_definition_id="PD-HEART-1", icd10_codeset_label="ICD10-HD",
        icd10_codeset_version="2026-01", linked_record_scope="primary_care",
        reviewer="Dr Epi", return_timestamp="2026-06-09T10:00:00", sign_off_status="signed",
    )
    return EpiReturn.from_dict({**base, **over})


def _setup(tmp_path, tiny_cohort):
    data = tmp_path / "synthetic"
    data.mkdir()
    _write_inputs(data, tiny_cohort)
    return _cfg(data, tmp_path / "results"), VariantRequest.from_dict(tiny_cohort["request"])


def _run_bound_epi_return(cfg, request, **over):
    run_id = epi.build_run_id(request, pipeline.build_provenance(cfg, request))
    return _epi_return(_request=request.model_dump(), run_id=run_id, **over)


def test_finalize_eligible_writes_governed_final_artefacts(tmp_path, tiny_cohort):
    cfg, request = _setup(tmp_path, tiny_cohort)
    results = tmp_path / "results"
    bundle = pipeline.orchestrate_finalize(
        cfg, request, _run_bound_epi_return(cfg, request, eligible_count=2)
    )

    for name in ("final_feasibility_summary.txt", "final_release_candidate.json",
                 "final_airlock_manifest.json"):
        assert (results / name).exists(), name
    # genotype ceiling (3 included) and eligible (2) both suppress under min_cell 10
    final = bundle["final_result"]
    assert final.genotype_total_included == 3 and final.post_phenotype_eligible == 2
    assert "GENOTYPE FEASIBILITY (upper bound / ceiling)" in bundle["final_summary"]
    assert "POST-PHENOTYPE ELIGIBLE CARRIERS (the FINAL figure)" in bundle["final_summary"]


def test_finalize_eligible_final_manifest_releases_only_the_lean_payload(tmp_path, tiny_cohort):
    cfg, request = _setup(tmp_path, tiny_cohort)
    manifest = pipeline.orchestrate_finalize(
        cfg, request, _run_bound_epi_return(cfg, request, eligible_count=2)
    )["airlock_manifest"]
    exports = [f for f in manifest["files"] if f["export_to_client"]]
    assert len(exports) == 1
    assert exports[0]["file"] == "release.json"
    assert "Only release.json is proposed for export" in manifest["note"]
    # both analyst summaries are retained INTERNAL-only, not exported
    for name in ("feasibility_summary.txt", "final_feasibility_summary.txt"):
        entry = next(f for f in manifest["files"] if f["file"] == name)
        assert entry["export_to_client"] is False


def test_finalize_eligible_audit_chain_extends_and_has_no_pii(tmp_path, tiny_cohort):
    cfg, request = _setup(tmp_path, tiny_cohort)
    results = tmp_path / "results"
    pipeline.orchestrate_finalize(
        cfg, request, _run_bound_epi_return(cfg, request, eligible_count=2)
    )

    events = io.read_jsonl(results / "audit_ledger.jsonl")
    assert any(e.get("sdc", {}).get("stage") == "finalize_eligible" for e in events)
    assert audit.verify_ledger(events, (results / "audit_root.txt").read_text().strip())
    assert not any(audit.has_forbidden_pii(e) for e in events)


def test_finalize_eligible_count_over_ceiling_fails_closed(tmp_path, tiny_cohort):
    cfg, request = _setup(tmp_path, tiny_cohort)
    results = tmp_path / "results"
    with pytest.raises(ValueError, match="exceeds the genotype ceiling"):
        pipeline.orchestrate_finalize(
            cfg, request, _run_bound_epi_return(cfg, request, eligible_count=99)
        )
    assert not (results / "final_feasibility_summary.txt").exists()  # nothing released


def test_finalize_eligible_blocking_checkpoint_halts_release(tmp_path, tiny_cohort):
    cfg, request = _setup(tmp_path, tiny_cohort)
    results = tmp_path / "results"
    block = HumanReviewCheckpoint.from_dict(dict(
        checkpoint="pre_airlock", reviewer="Gov", timestamp="2026-06-09T11:00:00",
        artefacts_checked=("final_summary",), decision="block",
        notes="SDC wording unclear", follow_up_owner="Analyst",
    ))
    with pytest.raises(ValueError, match="blocked by human review"):
        pipeline.orchestrate_finalize(
            cfg, request, _run_bound_epi_return(cfg, request, eligible_count=2), [block]
        )
    assert not (results / "final_feasibility_summary.txt").exists()


def test_genotype_run_writes_internal_epi_notification(tmp_path, tiny_cohort):
    # Wave 8 AC: a request produces an internal rapid-turnaround notification alongside the run.
    cfg, request = _setup(tmp_path, tiny_cohort)
    results = tmp_path / "results"
    pipeline.orchestrate(cfg, request)
    note = io.read_json(results / "epi_notification.json")
    assert note["workflow_state"] == "genotype_running"
    assert note["study_id"] == request.study_id and note["cpra"] == request.cpra
    assert note["run_id"] == epi.build_run_id(request, pipeline.build_provenance(cfg, request))
    assert "participant_id" not in str(note) and "pseudo" not in str(note)  # internal, no IDs


def test_finalize_eligible_unsigned_return_fails_closed(tmp_path, tiny_cohort):
    cfg, request = _setup(tmp_path, tiny_cohort)
    with pytest.raises(ValueError, match="signed"):
        pipeline.orchestrate_finalize(
            cfg,
            request,
            _run_bound_epi_return(
                cfg, request, eligible_count=2, sign_off_status="pending_sign_off"
            ),
        )
