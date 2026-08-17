"""E2E: the three committed example configs each run cleanly over generated synthetic data.

These configs under `configs/examples/` are the demo MVP's example entrypoints — single variant,
gene + disease panel, and the OFH-format pVCF/tabix path. CI does not pre-generate synthetic data,
so a module-scoped fixture generates it into a tmp dir; the real example configs are loaded
as-written, with only the data/request/results paths redirected via CLI overrides (the documented
run-matrix usage). This guards each example config against silent breakage and re-checks the
single-airlock-export governance invariant.
"""
import json
import subprocess
import sys
from pathlib import Path

import pytest

from ofh_feasibility import cli

pytestmark = pytest.mark.e2e

REPO = Path(__file__).resolve().parents[2]
EXAMPLE_CONFIGS = REPO / "configs" / "examples"


@pytest.fixture(scope="module")
def synthetic(tmp_path_factory) -> Path:
    """Generate the simplified synthetic dataset once, into a tmp dir the templates can point at."""
    out = tmp_path_factory.mktemp("synthetic")
    subprocess.run(
        [sys.executable, str(REPO / "scripts" / "generate_synthetic.py"), "--out", str(out)],
        check=True,
    )
    return out


def _assert_single_airlock_export(results: Path) -> None:
    # Governance invariant: the sole releasable artefact is the Lean-emitted canonical payload.
    payload = results / "airlock_pending" / "release.json"
    assert payload.is_file(), "canonical release payload missing from airlock_pending"
    assert json.loads(payload.read_text())["status"] == "released"
    # no Python-rendered client text may be staged in the egress-pending area.
    assert not list((results / "airlock_pending").glob("*.txt")), "text artefact staged for egress"


def test_single_variant_example_config_runs(synthetic, tmp_path):
    results = tmp_path / "single"
    cli.main([
        "run",
        "--config", str(EXAMPLE_CONFIGS / "single_variant_simplified.yaml"),
        "--data-dir", str(synthetic),
        "--request", str(synthetic / "variant_request.csv"),
        "--results-dir", str(results),
    ])
    _assert_single_airlock_export(results)
    assert (results / "release_candidate.json").exists()


def test_gene_panel_example_config_runs(synthetic, tmp_path):
    results = tmp_path / "gene"
    cli.main([
        "gene", "--symbol", "CHEK2",
        "--config", str(EXAMPLE_CONFIGS / "gene_panel_simplified.yaml"),
        "--data-dir", str(synthetic),
        "--results-dir", str(results),
    ])
    _assert_single_airlock_export(results)


def test_disease_panel_example_config_runs(synthetic, tmp_path):
    results = tmp_path / "disease"
    cli.main([
        "disease", "--panel", "breast_cancer",
        "--config", str(EXAMPLE_CONFIGS / "gene_panel_simplified.yaml"),
        "--data-dir", str(synthetic),
        "--results-dir", str(results),
    ])
    _assert_single_airlock_export(results)


def test_ofh_tre_example_config_runs(synthetic, tmp_path):
    pytest.importorskip("pysam")  # the ofhgen extra; skip when absent (default CI install)
    ofh = tmp_path / "ofh_tre"
    subprocess.run(
        [sys.executable, str(REPO / "scripts" / "generate_ofh_files.py"),
         "--in", str(synthetic), "--out", str(ofh)],
        check=True,
    )
    results = tmp_path / "ofhtre"
    cli.main([
        "run",
        "--config", str(EXAMPLE_CONFIGS / "ofh_tre_chek2_i157t.yaml"),
        "--data-dir", str(ofh),
        "--request", str(synthetic / "requests" / "chek2_i157t.csv"),
        "--results-dir", str(results),
    ])
    _assert_single_airlock_export(results)
