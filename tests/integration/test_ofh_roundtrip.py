"""Integration: generate the real OFH-format files -> read them back -> the governed result matches.

Proves the Wave 9 format adapter is faithful: the OFH-format ingest (summary-stats VCF as manifest +
per-region pVCF slice + OFH sample-QC) yields the SAME counts + client figure as the simplified
inputs.
"""
import importlib.util
import sys
from pathlib import Path

import pandas as pd
import pytest

pysam = pytest.importorskip("pysam")  # the ofhgen extra; skip when absent (default CI install)

from ofh_feasibility import cli, io, ofh_formats, pipeline  # noqa: E402
from ofh_feasibility.config import Config  # noqa: E402
from ofh_feasibility.models import VariantRequest  # noqa: E402

pytestmark = pytest.mark.integration

CPRA = "10:119669928:C:G"
_GEN = Path(__file__).resolve().parents[2] / "scripts" / "generate_ofh_files.py"
_MANIFEST_ROW = {
    "cpra": CPRA, "chrom": "10", "pos": "119669928", "ref": "C", "alt": "G", "build": "GRCh38",
    "biallelic": "TRUE", "on_array": "TRUE", "on_imputed": "TRUE", "array_maf": "0.013",
    "imputed_maf": "0.014", "dosage_r2": "0.71", "annotation": "bag3",
    "inaccurate_annotation": "FALSE", "multiallelic_variant": "FALSE",
}


def _generator():
    spec = importlib.util.spec_from_file_location("gen_ofh", _GEN)
    mod = importlib.util.module_from_spec(spec)
    sys.modules["gen_ofh"] = mod
    spec.loader.exec_module(mod)
    return mod


def _cfg(data):
    return Config.from_dict(dict(
        array_call_rate_min=0.98, array_gq_min=20, imputed_info_min=0.30,
        imputed_info_high_confidence=0.80, imputed_dosage_carrier_threshold=0.5,
        imputed_max_gp_min=0.90, carrier_definition="het_and_homalt", require_consent=True,
        sdc_min_cell=10, sdc_round_to=5, data_dir=str(data), results_dir="r",
    ))


def _write_config(path: Path, data: Path, results: Path) -> None:
    path.write_text(f"""\
array_call_rate_min: 0.98
array_gq_min: 20
imputed_info_min: 0.30
imputed_info_high_confidence: 0.80
imputed_dosage_carrier_threshold: 0.5
imputed_max_gp_min: 0.90
carrier_definition: het_and_homalt
require_consent: true
sdc_min_cell: 10
sdc_round_to: 5
data_dir: {data}
results_dir: {results}
""")


def test_ofh_format_ingest_matches_simplified_result(tmp_path, tiny_cohort, monkeypatch):
    data = tmp_path / "synthetic"
    data.mkdir()
    tiny_cohort["participants"].to_parquet(data / "participant_table.parquet", index=False)
    tiny_cohort["genotype_slice"].to_parquet(data / "genotype_slice.parquet", index=False)
    tiny_cohort["sample_qc"].to_csv(data / "sample_qc_metrics.tsv", sep="\t", index=False)
    pd.DataFrame([_MANIFEST_ROW]).to_csv(data / "variant_manifest.csv", index=False)

    cfg, request = _cfg(data), VariantRequest.from_dict(tiny_cohort["request"])

    # simplified path
    simplified = pipeline.run_pipeline(
        cfg, request, io.read_variant_manifest(data), tiny_cohort["participants"],
        tiny_cohort["genotype_slice"], tiny_cohort["sample_qc"],
    )

    # transcode to real OFH formats, then read them BACK and run the same pipeline
    ofh_dir = data / "ofh_tre"
    monkeypatch.setattr(sys, "argv", ["gen", "--in", str(data), "--out", str(ofh_dir)])
    _generator().main()

    ofh = pipeline.run_pipeline(
        cfg, request, ofh_formats.read_ofh_variant_manifest(ofh_dir),
        tiny_cohort["participants"], ofh_formats.OfhTreGenotypeSource(ofh_dir).read_slice(),
        ofh_formats.read_ofh_sample_qc(ofh_dir),
    )

    # tiny_cohort has no low-GQ edge case, so the OFH ingest reproduces the result exactly
    assert ofh["cells"] == simplified["cells"]
    assert ofh["result"].client_total == simplified["result"].client_total
    assert ofh["result"].total_included == simplified["result"].total_included


def test_ofh_tre_source_format_orchestrates_end_to_end(tmp_path, tiny_cohort, monkeypatch):
    data = tmp_path / "synthetic"
    data.mkdir()
    tiny_cohort["participants"].to_parquet(data / "participant_table.parquet", index=False)
    tiny_cohort["genotype_slice"].to_parquet(data / "genotype_slice.parquet", index=False)
    tiny_cohort["sample_qc"].to_csv(data / "sample_qc_metrics.tsv", sep="\t", index=False)
    pd.DataFrame([tiny_cohort["request"]]).to_csv(data / "variant_request.csv", index=False)
    pd.DataFrame([_MANIFEST_ROW]).to_csv(data / "variant_manifest.csv", index=False)

    ofh_dir = data / "ofh_tre"
    monkeypatch.setattr(sys, "argv", ["gen", "--in", str(data), "--out", str(ofh_dir)])
    _generator().main()

    request = VariantRequest.from_dict(tiny_cohort["request"])
    cfg = _cfg(ofh_dir).model_copy(
        update={"results_dir": str(tmp_path / "ofh_results"), "source_format": "ofh_tre"}
    )
    bundle = pipeline.orchestrate(cfg, request)
    assert bundle["result"].total_included == 3
    assert (tmp_path / "ofh_results" / "provenance.json").exists()


def test_ofh_tre_source_format_handles_array_only_bag3(tmp_path, tiny_cohort, monkeypatch):
    data = tmp_path / "synthetic"
    data.mkdir()
    tiny_cohort["participants"].to_parquet(data / "participant_table.parquet", index=False)
    tiny_cohort["genotype_slice"].to_parquet(data / "genotype_slice.parquet", index=False)
    tiny_cohort["sample_qc"].to_csv(data / "sample_qc_metrics.tsv", sep="\t", index=False)
    pd.DataFrame([tiny_cohort["request"]]).to_csv(data / "variant_request.csv", index=False)
    manifest_row = {
        **_MANIFEST_ROW,
        "on_imputed": "FALSE",
        "imputed_maf": "NA",
        "dosage_r2": "NA",
    }
    pd.DataFrame([manifest_row]).to_csv(data / "variant_manifest.csv", index=False)

    ofh_dir = data / "ofh_tre"
    monkeypatch.setattr(sys, "argv", ["gen", "--in", str(data), "--out", str(ofh_dir)])
    _generator().main()

    request = VariantRequest.from_dict(tiny_cohort["request"])
    cfg = _cfg(ofh_dir).model_copy(
        update={"results_dir": str(tmp_path / "array_only_results"), "source_format": "ofh_tre"}
    )
    bundle = pipeline.orchestrate(cfg, request)
    manifest = ofh_formats.read_ofh_variant_manifest(ofh_dir, CPRA)

    assert manifest.iloc[0]["on_array"] == "TRUE"
    assert manifest.iloc[0]["on_imputed"] == "FALSE"
    assert bundle["sources"]["use_array"] is True
    assert bundle["sources"]["use_imputed"] is False
    assert bundle["result"].variant_on_array is True
    assert bundle["result"].total_included == 2


def test_cli_source_format_ofh_tre_runs(tmp_path, tiny_cohort, monkeypatch):
    data = tmp_path / "synthetic"
    data.mkdir()
    tiny_cohort["participants"].to_parquet(data / "participant_table.parquet", index=False)
    tiny_cohort["genotype_slice"].to_parquet(data / "genotype_slice.parquet", index=False)
    tiny_cohort["sample_qc"].to_csv(data / "sample_qc_metrics.tsv", sep="\t", index=False)
    pd.DataFrame([tiny_cohort["request"]]).to_csv(data / "variant_request.csv", index=False)
    pd.DataFrame([_MANIFEST_ROW]).to_csv(data / "variant_manifest.csv", index=False)

    ofh_dir = data / "ofh_tre"
    monkeypatch.setattr(sys, "argv", ["gen", "--in", str(data), "--out", str(ofh_dir)])
    _generator().main()
    cfg_path = tmp_path / "config.yaml"
    results = tmp_path / "cli_results"
    _write_config(cfg_path, data, tmp_path / "unused_results")

    cli.main([
        "run", "--config", str(cfg_path), "--source-format", "ofh_tre",
        "--data-dir", str(ofh_dir), "--results-dir", str(results),
    ])
    assert (results / "feasibility_summary.txt").exists()
    assert (results / "provenance.json").exists()


def test_ofh_files_have_real_names_and_formats(tmp_path, tiny_cohort, monkeypatch):
    data = tmp_path / "synthetic"
    data.mkdir()
    tiny_cohort["participants"].to_parquet(data / "participant_table.parquet", index=False)
    tiny_cohort["genotype_slice"].to_parquet(data / "genotype_slice.parquet", index=False)
    tiny_cohort["sample_qc"].to_csv(data / "sample_qc_metrics.tsv", sep="\t", index=False)
    pd.DataFrame([_MANIFEST_ROW]).to_csv(data / "variant_manifest.csv", index=False)
    ofh_dir = data / "ofh_tre"
    monkeypatch.setattr(sys, "argv", ["gen", "--in", str(data), "--out", str(ofh_dir)])
    _generator().main()

    for name in (
        "ofh_snv.chr10-b0001.vcf.gz", "ofh_snv.chr10-b0001.vcf.gz.tbi",
        "ofh_imputed.v6.chr10-b0001.vcf.gz", "ofh_imputed_variant_summary_stats.v6.vcf.gz",
        "ofh_sample_qc_metrics.tsv", "ofh_imputed_sample_qc_metrics.v6.tsv",
        "ofh_snv.chr10-b0001.sample", "ofh_snv_kinship.txt", "ofh_snv_regions.bed",
    ):
        assert (ofh_dir / name).exists(), name
    # the VCFs are GENUINE bgzip (BGZF) read by htslib, with the right FORMAT per OFH
    array = pysam.VariantFile(str(ofh_dir / "ofh_snv.chr10-b0001.vcf.gz"))
    assert array.compression == "BGZF" and "VCFv4.1" in str(array.header).split("\n")[0]
    arec = next(iter(array))
    assert "GT" in arec.format and "GP" not in arec.format  # array is GT only
    imp = pysam.VariantFile(str(ofh_dir / "ofh_imputed.v6.chr10-b0001.vcf.gz"))
    irec = next(iter(imp))
    assert "GT" in irec.format and "GP" in irec.format  # imputed carries GP
