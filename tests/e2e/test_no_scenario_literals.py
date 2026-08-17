"""Regression guard: outputs must reflect the actual request, not a hardcoded scenario.

Derived-outputs guard: the gene/disease CLI defaults used to
bake in CHEK2 / breast-cancer, so `gene --symbol BRCA1` emitted a client summary claiming "CHEK2
carriers". The defaults now derive from the request (study_id / purpose from the symbol / panel).
This asserts no scenario literal leaks into the client output for a non-default gene.
"""
import subprocess
import sys
from pathlib import Path

import pytest

from ofh_feasibility import cli

pytestmark = pytest.mark.e2e

REPO = Path(__file__).resolve().parents[2]


@pytest.fixture(scope="module")
def synthetic(tmp_path_factory) -> Path:
    out = tmp_path_factory.mktemp("synthetic")
    subprocess.run(
        [sys.executable, str(REPO / "scripts" / "generate_synthetic.py"), "--out", str(out)],
        check=True,
    )
    return out


def test_gene_output_reflects_symbol_not_hardcoded_scenario(synthetic, tmp_path):
    results = tmp_path / "brca1"
    cli.main([
        "gene", "--symbol", "BRCA1",
        "--data-dir", str(synthetic),
        "--results-dir", str(results),
    ])
    summary = (results / "batch_feasibility_summary.txt").read_text()
    # The derived study-id / purpose for the requested gene must appear...
    assert "BRCA1" in summary, "the requested gene is missing from its own summary"
    # ...and the previously-hardcoded CHEK2 / breast-cancer scenario must NOT leak in.
    assert "CHEK2" not in summary, "hardcoded CHEK2 scenario literal leaked into a BRCA1 request"
    assert "breast" not in summary.lower(), "hardcoded breast-cancer scenario literal leaked"
