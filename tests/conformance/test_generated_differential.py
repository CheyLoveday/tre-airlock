"""Generated Python/Lean differential conformance (TRE-airlock MVP, plan §12).

Enumerates a deterministic grid of release candidates and asserts the Python reference predicate
and the runtime Lean adjudicator return the SAME verdict on every one. "Refused" on the Python
side means either the reference predicate fails OR the strict request builder refuses to
serialise the candidate at all (malformed token / negative count / duplicate label): a candidate
that cannot legally cross the boundary is a refusal by construction on both sides.

Skips if the binary is not built (`make airlock`).
"""
import itertools
import subprocess

import pytest

from ofh_feasibility import airlock, bridge
from ofh_feasibility.models import ReleaseCandidate

pytestmark = pytest.mark.conformance

_TOKENS = ["<10", "~10", "~15", "~70", "~5", "~7", "~0", "<5", "<10x", "20"]
_CELLS = [
    (),
    (("array_direct_high_confidence", 15),),
    (("array_direct_high_confidence", 15), ("b", 25)),
    (("array_direct_high_confidence", 15), ("b", 2)),
    (("array_direct_high_confidence", 0),),
    (("array_direct_high_confidence", 7),),
    (("array_direct_high_confidence", 15), ("array_direct_high_confidence", 25)),  # duplicate
    (("array_direct_high_confidence", 15), ("unapproved_label", 25)),  # out-of-vocabulary
    (("array_direct_high_confidence", -5),),  # negative count
]
_GRID = list(itertools.product(_TOKENS, _CELLS, (True, False)))


def _policy():
    return bridge.TrustedReleasePolicy(
        policy_id="grid", version="1", min_cell=10, round_to=5,
        adjudicator_sha256=None, policy_sha256="0" * 64,
    )


@pytest.fixture(scope="module")
def exe():
    path = bridge._TRUSTED_EXE
    if not path.is_file():
        pytest.skip("airlock not built (make airlock)")
    return path


def _python_verdict(candidate, policy) -> bool:
    # the END-TO-END Python-side gate: the strict builder (closed value language + policy
    # mismatch) AND the reference predicate — exactly what stands before Lean on the bridge.
    try:
        airlock.build_airlock_request(candidate, policy)
    except ValueError:
        return False
    return airlock.release_ok(candidate)


def _lean_verdict(candidate, policy, exe) -> bool:
    try:
        request = airlock.build_airlock_request(candidate, policy)
    except ValueError:
        return False  # unserialisable == refused at the boundary (fail closed)
    proc = subprocess.run(
        [str(exe)], input=bridge.encode_request(request), capture_output=True, timeout=30
    )
    return proc.returncode == 0


@pytest.mark.parametrize(
    "token,cells,suppressed",
    _GRID,
    ids=[f"{t}|{len(c)}cells|sup={s}" for t, c, s in _GRID],
)
def test_python_and_lean_agree(token, cells, suppressed, exe):
    candidate = ReleaseCandidate(
        study_id="S", cpra="10:1:C:G", client_total=token,
        breakdown_suppressed=suppressed, reported_cells=cells,
        min_cell=10, round_to=5,
    )
    policy = _policy()
    assert _python_verdict(candidate, policy) == _lean_verdict(candidate, policy, exe), (
        f"Python and Lean disagree on token={token!r} cells={cells!r} suppressed={suppressed}"
    )
