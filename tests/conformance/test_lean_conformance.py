"""Conformance: the Python release gate (`airlock.release_ok`) agrees with the Lean checker over a
battery of release candidates — binding the implementation to the proven Lean specification.

Skips unless the Lean checker is built (`cd formal && lake build`), so the pure-Python CI is
unaffected; the dedicated Lean CI job builds it and runs this test.
"""
import subprocess
from pathlib import Path

import pytest

from ofh_feasibility import airlock
from ofh_feasibility.models import ReleaseCandidate

pytestmark = pytest.mark.conformance

_EXE = Path(__file__).resolve().parents[2] / "formal" / ".lake" / "build" / "bin" / "releasecheck"

# (min_cell, round_to, client_total, breakdown_suppressed, [subgroup counts]) — every edge case.
_BATTERY = [
    (10, 5, "<10", True, []),               # suppressed total, no breakdown
    (10, 5, "~20", True, []),               # rounded total, breakdown suppressed
    (10, 5, "~40", False, [25, 15]),        # full breakdown, all >= min
    (10, 5, "~40", False, [25, 5]),         # sub-min subgroup -> reject
    (10, 5, "~40", True, [25]),             # breakdown shown while flagged suppressed -> reject
    (10, 5, "~40", False, [23]),            # unrounded subgroup -> reject
    (10, 5, "~23", False, []),              # unrounded total -> reject
    (10, 5, "20", False, []),               # malformed total token -> reject
    (5, 5, "~15", False, [5, 10]),          # min_cell 5: cell of 5 is OK
    (20, 10, "~40", False, [20, 20]),       # larger thresholds, all OK
    (10, 5, "~40", False, [40, 0]),         # a structural zero cell is allowed
    (10, 5, "~10", False, [10]),            # boundary: exactly min, rounded -> OK
    # F6: a bare "<" prefix is not enough — the suppression token must be EXACTLY "<{min_cell}".
    (10, 5, "<5", True, []),                # wrong-min suppression token -> reject
    (10, 5, "<20", True, []),               # wrong-min suppression token -> reject
    (10, 5, "<banana", True, []),           # non-numeric suppression token -> reject
    (10, 5, "<10x", True, []),              # suppression token with suffix -> reject
    (10, 5, "~5", False, []),               # rounded total below min_cell -> reject
]


def _python_verdict(mc, rt, total, supp, counts) -> str:
    candidate = ReleaseCandidate(
        study_id="s", cpra="c", client_total=total, breakdown_suppressed=supp,
        reported_cells=tuple((f"c{i}", n) for i, n in enumerate(counts)), min_cell=mc, round_to=rt,
    )
    return "true" if airlock.release_ok(candidate) else "false"


def _lean_line(mc, rt, total, supp, counts) -> str:
    return f"{mc}|{rt}|{total}|{'true' if supp else 'false'}|{','.join(map(str, counts))}"


@pytest.mark.skipif(not _EXE.exists(), reason="Lean checker not built (cd formal && lake build)")
def test_python_and_lean_agree_across_the_battery():
    stdin = "\n".join(_lean_line(*c) for c in _BATTERY) + "\n"
    proc = subprocess.run([str(_EXE)], input=stdin, capture_output=True, text=True, timeout=60)
    assert proc.returncode == 0, proc.stderr
    lean_verdicts = proc.stdout.strip().split("\n")
    assert len(lean_verdicts) == len(_BATTERY)
    for case, lean_v in zip(_BATTERY, lean_verdicts, strict=True):
        py_v = _python_verdict(*case)
        assert py_v == lean_v, f"divergence on {case}: python={py_v} lean={lean_v}"
