"""Scaling regression guard — the pipeline must stay sub-quadratic as the cohort grows.

Machine-INDEPENDENT: it asserts the log-log scaling *slope*, not absolute wall time, so it catches a
reintroduced big-axis Python loop / O(n^2) merge without flaking on CI hardware speed. Opt-in
(set ``RUN_PERF=1``) so it never slows or flakes the default suite — run it in a dedicated perf job,
the same pattern as the Lean conformance test.

    RUN_PERF=1 uv run pytest tests/e2e/test_scaling_regression.py -q
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import numpy as np
import pytest

pytestmark = pytest.mark.e2e

_REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_REPO / "scripts"))  # reuse the profiling harness

requires_perf = pytest.mark.skipif(
    not os.environ.get("RUN_PERF"),
    reason="scaling regression test; set RUN_PERF=1 to run (perf job only)",
)


@pytest.fixture(scope="module")
def _base_cohort() -> None:
    if not (_REPO / "data" / "synthetic" / "participant_table.parquet").exists():
        subprocess.run([sys.executable, "scripts/generate_synthetic.py"], cwd=_REPO, check=True)


@requires_perf
def test_pipeline_scales_subquadratically(_base_cohort: None, tmp_path: Path) -> None:
    """A reintroduced cohort-scale loop / O(n^2) merge shows up as a super-linear slope."""
    from profile_pipeline import profile_one

    sizes = [4000, 16000, 64000]
    walls = [profile_one(n, tmp_path, repeats=2)["wall_s"] for n in sizes]
    slope = float(np.polyfit(np.log(sizes), np.log(walls), 1)[0])
    assert slope < 1.9, (
        f"pipeline scaling slope {slope:.2f} over N={sizes} "
        f"(walls={[round(w, 2) for w in walls]}) — super-linear: a big-axis loop or O(n^2) merge "
        "may have been reintroduced (quadratic ~ 2.0)."
    )
