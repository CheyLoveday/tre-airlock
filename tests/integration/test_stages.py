"""Integration: the file-staged stage_* orchestrators (Snakemake path) reproduce the in-memory run
and record provenance."""
import pandas as pd
import pytest

from ofh_feasibility import pipeline
from ofh_feasibility.config import Config
from ofh_feasibility.models import VariantRequest

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


def _run_stages(cfg):
    pipeline.stage_extract(cfg)
    pipeline.stage_qc(cfg)
    pipeline.stage_classify(cfg)
    pipeline.stage_report(cfg)
    pipeline.stage_airlock(cfg)


def test_snakefile_declares_all_staged_artefacts():
    # F5 regression guard: the Snakefile must declare the files the stage_* functions read/write,
    # so the DAG cannot silently drift (e.g. variant_preflight.json was added without declaring it).
    from pathlib import Path

    snakefile = (Path(__file__).resolve().parents[2] / "workflow" / "Snakefile").read_text()
    for artefact in (
        "variant_preflight.json",       # written by stage_extract, read by stage_report
        "annotated.parquet",            # read by stage_report
        "frequency_control_view.json",  # written by stage_report
        "release_candidate.json",       # written by stage_report (the release-controlled artefact)
    ):
        assert artefact in snakefile, f"Snakefile must declare {artefact}"


def test_stage_dispatch_table_is_complete():
    # the table the Snakemake / Nextflow / WDL wrappers (via scripts/run_stage.py) dispatch through
    assert set(pipeline.STAGES) == {"extract", "qc", "classify", "report", "airlock"}
    assert pipeline.STAGES["extract"] is pipeline.stage_extract


def test_stages_write_all_intermediates_and_artefacts(tmp_path, tiny_cohort):
    data = tmp_path / "synthetic"
    data.mkdir()
    _write_inputs(data, tiny_cohort)
    results = tmp_path / "results"
    _run_stages(_cfg(data, results))
    for name in (
        "candidate.parquet", "annotated.parquet", "sources.json", "variant_preflight.json",
        "provenance.json", "internal_carrier_table.parquet", "handoff_to_epi.csv",
        "feasibility_summary.txt", "airlock_manifest.json",
    ):
        assert (results / name).exists(), name


def test_stage_extract_duplicate_participant_fails_closed(tmp_path, tiny_cohort):
    data = tmp_path / "synthetic"
    data.mkdir()
    dup = pd.concat(
        [tiny_cohort["participants"], tiny_cohort["participants"].iloc[[0]]], ignore_index=True
    )
    tiny_cohort["participants"] = dup
    _write_inputs(data, tiny_cohort)
    results = tmp_path / "results"
    with pytest.raises(ValueError, match="participant_table: duplicate"):
        pipeline.stage_extract(_cfg(data, results))
    assert not (results / "candidate.parquet").exists()  # failed before producing the slice


def test_stage_extract_duplicate_genotype_row_fails_closed(tmp_path, tiny_cohort):
    data = tmp_path / "synthetic"
    data.mkdir()
    gs = tiny_cohort["genotype_slice"]
    tiny_cohort["genotype_slice"] = pd.concat([gs, gs.iloc[[0]]], ignore_index=True)
    _write_inputs(data, tiny_cohort)
    with pytest.raises(ValueError, match="genotype_slice: duplicate"):
        pipeline.stage_extract(_cfg(data, tmp_path / "results"))


def test_staged_preflight_records_strand_resolution_and_surfaces_caveat(tmp_path, tiny_cohort):
    from ofh_feasibility import io

    data = tmp_path / "synthetic"
    data.mkdir()
    _write_inputs(data, tiny_cohort)
    results = tmp_path / "results"
    _run_stages(_cfg(data, results))
    # the staged pre-flight artefact records the palindromic-SNP strand resolution (Wave 7)...
    preflight = io.read_json(results / "variant_preflight.json")
    assert preflight["is_palindromic"] is True and preflight["strand"] == "forward"
    assert preflight["build_resolved"] == "GRCh38" and preflight["ref_matched"] is True
    assert preflight["requested_source"] == "array_and_imputed"
    assert preflight["requested_sources_available"] is True
    assert preflight["source_caveats"] == []
    # ...and the client summary surfaces the palindromic caveat (not silently assumed forward).
    summary = (results / "feasibility_summary.txt").read_text()
    assert "palindromic" in summary and "strand resolved as forward" in summary


def test_staged_artefacts_match_in_memory(tmp_path, tiny_cohort):
    data = tmp_path / "synthetic"
    data.mkdir()
    _write_inputs(data, tiny_cohort)
    staged, mem = tmp_path / "staged", tmp_path / "mem"
    _run_stages(_cfg(data, staged))
    pipeline.orchestrate(_cfg(data, mem), VariantRequest.from_dict(tiny_cohort["request"]))

    # the two orchestration modes produce byte-identical governed artefacts
    assert (staged / "feasibility_summary.txt").read_text() == (
        mem / "feasibility_summary.txt"
    ).read_text()
    pd.testing.assert_frame_equal(
        pd.read_parquet(staged / "internal_carrier_table.parquet"),
        pd.read_parquet(mem / "internal_carrier_table.parquet"),
    )
    pd.testing.assert_frame_equal(
        pd.read_csv(staged / "handoff_to_epi.csv"), pd.read_csv(mem / "handoff_to_epi.csv")
    )


def test_staged_run_emits_verifiable_audit_chain(tmp_path, tiny_cohort):
    from ofh_feasibility import audit, io

    data = tmp_path / "synthetic"
    data.mkdir()
    _write_inputs(data, tiny_cohort)
    results = tmp_path / "results"
    _run_stages(_cfg(data, results))
    events = io.read_jsonl(results / "audit_ledger.jsonl")
    assert [e["stage"] for e in events] == ["extract", "qc", "classify", "report", "airlock"]
    assert audit.verify_ledger(events, (results / "audit_root.txt").read_text().strip())
    assert not any("participant_id" in str(e) for e in events)  # hashes + metadata only


def test_provenance_reproducible(tmp_path, tiny_cohort):
    data = tmp_path / "synthetic"
    data.mkdir()
    _write_inputs(data, tiny_cohort)
    cfg = _cfg(data, tmp_path / "results")
    req = VariantRequest.from_dict(tiny_cohort["request"])
    p1, p2 = pipeline.build_provenance(cfg, req), pipeline.build_provenance(cfg, req)
    assert p1["config_sha256"] == p2["config_sha256"]      # deterministic config hash
    assert p1["input_sha256"] == p2["input_sha256"]        # same inputs -> same hashes
    assert set(p1["input_sha256"]) == set(pipeline._INPUT_FILES)
    assert p1["cpra"] == CPRA and "python" in p1["versions"]
