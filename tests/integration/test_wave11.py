"""Integration tests for WAVE_11 expanded BAG3/CHEK2/breast-cancer cases."""

import importlib.util
import json
import sys
from pathlib import Path

import pytest

from ofh_feasibility import cli, pipeline
from ofh_feasibility.config import Config

pytestmark = pytest.mark.integration

_SYN = Path(__file__).resolve().parents[2] / "scripts" / "generate_synthetic.py"
_OFH = Path(__file__).resolve().parents[2] / "scripts" / "generate_ofh_files.py"


def _load_script(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


def _config(path: Path, data: Path, results: Path) -> None:
    path.write_text(f"""\
array_call_rate_min: 0.98
array_gq_min: 20
imputed_dr2_min: 0.30
imputed_dr2_high_confidence: 0.80
imputed_dosage_carrier_threshold: 0.5
imputed_max_gp_min: 0.90
carrier_definition: het_and_homalt
require_consent: true
sdc_min_cell: 10
sdc_round_to: 5
data_dir: {data}
results_dir: {results}
""")


def _generated(tmp_path, monkeypatch):
    data = tmp_path / "synthetic"
    monkeypatch.setattr(sys, "argv", ["gen", "--out", str(data)])
    _load_script("gen_synthetic_wave11", _SYN).main()
    cfg = tmp_path / "config.yaml"
    _config(cfg, data, tmp_path / "unused")
    return data, cfg


def test_chek2_i157t_single_variant_shows_sdc_breakdowns(tmp_path, monkeypatch):
    data, cfg = _generated(tmp_path, monkeypatch)
    results = tmp_path / "i157t_results"

    cli.main([
        "run",
        "--config",
        str(cfg),
        "--request",
        str(data / "requests" / "chek2_i157t.csv"),
        "--results-dir",
        str(results),
    ])

    candidate = json.loads((results / "release_candidate.json").read_text())
    summary = (results / "feasibility_summary.txt").read_text()
    assert candidate["client_total"] == "~70"
    assert candidate["breakdown_suppressed"] is False
    assert ["array_direct_high_confidence", 70] in candidate["reported_cells"]
    assert "Array-direct (high confidence):  ~70" in summary
    assert "Ancestry breakdown (consented carriers):" in summary


def test_chek2_c1100delc_low_dr2_is_no_go_without_fake_array_count(tmp_path, monkeypatch):
    data, cfg = _generated(tmp_path, monkeypatch)
    results = tmp_path / "c1100_results"

    cli.main([
        "run",
        "--config",
        str(cfg),
        "--request",
        str(data / "requests" / "chek2_c1100delc.csv"),
        "--results-dir",
        str(results),
    ])

    candidate = json.loads((results / "release_candidate.json").read_text())
    summary = (results / "feasibility_summary.txt").read_text()
    assert candidate["client_total"] == "<10"
    assert "variant on OFH array: no" in summary
    assert "DR2) = 0.18" in summary
    assert "indel not directly typed on the array" in summary
    assert "targeted assay" in summary
    assert "RECOMMENDATION: NO-GO" in summary


def test_gene_and_disease_cli_resolve_to_batch_outputs(tmp_path, monkeypatch):
    data, cfg = _generated(tmp_path, monkeypatch)

    gene_results = tmp_path / "gene_results"
    cli.main([
        "gene",
        "--symbol",
        "CHEK2",
        "--config",
        str(cfg),
        "--data-dir",
        str(data),
        "--results-dir",
        str(gene_results),
    ])
    gene_summary = (gene_results / "batch_feasibility_summary.txt").read_text()
    assert "Variants assessed: 2" in gene_summary
    assert "COMBINED" in gene_summary
    assert (gene_results / "batch_airlock_manifest.json").exists()

    disease_results = tmp_path / "disease_results"
    cli.main([
        "disease",
        "--panel",
        "breast_cancer",
        "--config",
        str(cfg),
        "--data-dir",
        str(data),
        "--results-dir",
        str(disease_results),
    ])
    disease_summary = (disease_results / "batch_feasibility_summary.txt").read_text()
    assert "Variants assessed: 6" in disease_summary
    assert (disease_results / "batch_release_candidate.json").exists()


def test_snakemake_input_discovery_uses_request_path_override(tmp_path):
    request_path = tmp_path / "requests" / "chek2_i157t.csv"
    cfg = Config.from_dict(
        {
            "array_call_rate_min": 0.98,
            "array_gq_min": 20,
            "imputed_dr2_min": 0.30,
            "imputed_dr2_high_confidence": 0.80,
            "imputed_dosage_carrier_threshold": 0.5,
            "imputed_max_gp_min": 0.90,
            "carrier_definition": "het_and_homalt",
            "require_consent": True,
            "sdc_min_cell": 10,
            "sdc_round_to": 5,
            "data_dir": str(tmp_path / "synthetic"),
            "results_dir": str(tmp_path / "results"),
            "request_path": str(request_path),
            "variant_identifiability_path": str(tmp_path / "variant-identifiability.csv"),
        }
    )
    assert pipeline.required_input_files(cfg)["variant_request"] == str(request_path)
    assert pipeline.required_input_files(cfg)["variant_identifiability"] == str(
        tmp_path / "variant-identifiability.csv"
    )


def test_ofh_format_cli_runs_expanded_chek2_i157t(tmp_path, monkeypatch):
    pytest.importorskip("pysam")
    data, cfg = _generated(tmp_path, monkeypatch)
    ofh_dir = tmp_path / "ofh_tre"
    monkeypatch.setattr(sys, "argv", ["gen_ofh", "--in", str(data), "--out", str(ofh_dir)])
    _load_script("gen_ofh_wave11", _OFH).main()

    results = tmp_path / "ofh_i157t_results"
    cli.main([
        "run",
        "--config",
        str(cfg),
        "--source-format",
        "ofh_tre",
        "--data-dir",
        str(ofh_dir),
        "--request",
        str(data / "requests" / "chek2_i157t.csv"),
        "--results-dir",
        str(results),
    ])

    candidate = json.loads((results / "release_candidate.json").read_text())
    assert candidate["client_total"] == "~70"
    assert (results / "provenance.json").exists()

    gene_results = tmp_path / "ofh_gene_results"
    cli.main([
        "gene",
        "--symbol",
        "CHEK2",
        "--config",
        str(cfg),
        "--source-format",
        "ofh_tre",
        "--data-dir",
        str(ofh_dir),
        "--results-dir",
        str(gene_results),
    ])

    gene_summary = (gene_results / "batch_feasibility_summary.txt").read_text()
    assert "Variants assessed: 2" in gene_summary
    assert (gene_results / "batch_airlock_manifest.json").exists()
