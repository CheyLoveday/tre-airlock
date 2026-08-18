"""Runtime contract of the `airlock` executable (the release authority).

Skips unless `cd formal && lake build` has produced the binary. Refusal must
emit empty stdout. The Python bridge invokes this binary on every release
path and writes only its exact emitted bytes.

Exit codes: 0 released · 1 candidate rejected · 2 malformed · 3 invalid policy.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

pytestmark = pytest.mark.conformance

_EXE = Path(__file__).resolve().parents[2] / "formal" / ".lake" / "build" / "bin" / "airlock"

SCHEMA = "tre-airlock/v2"
POLICY_OK = {"min_cell": 10, "round_to": 5}


def _request(candidate: dict, *, policy: dict = POLICY_OK, extra: dict | None = None) -> dict:
    body = {"schema": SCHEMA, "policy": policy, "candidate": candidate}
    if extra:
        body.update(extra)
    return body


def _candidate(
    *,
    total: dict,
    breakdown: dict,
    subject_id: str = "10:119669928:C:G",
) -> dict:
    return {
        "subject_id": subject_id,
        "total": total,
        "breakdown": breakdown,
    }


def _run(payload: str | dict) -> subprocess.CompletedProcess[bytes]:
    raw = payload if isinstance(payload, str) else json.dumps(payload, separators=(",", ":"))
    return subprocess.run(
        [str(_EXE)], input=raw.encode(), capture_output=True, timeout=30
    )


@pytest.fixture(scope="module")
def airlock_exe() -> Path:
    if not _EXE.exists():
        pytest.skip("airlock not built (cd formal && lake build)")
    return _EXE


def test_valid_shown_total_emits_canonical_payload(airlock_exe: Path) -> None:
    proc = _run(
        _request(
            _candidate(
                total={"tag": "shown", "n": 70},
                breakdown={"tag": "suppressed"},
                subject_id="10:119669928:C:G",
            )
        )
    )
    assert proc.returncode == 0
    assert proc.stderr == b""
    body = json.loads(proc.stdout)
    assert proc.stdout.endswith(b"\n")
    assert proc.stdout.decode() == (
        '{"schema":"tre-airlock/v2","status":"released",'
        '"policy":{"min_cell":10,"round_to":5},'
        '"subject_id":"10:119669928:C:G",'
        '"total":"~70","breakdown":null}\n'
    )
    assert body["status"] == "released"
    assert body["total"] == "~70"
    assert body["breakdown"] is None


def test_suppressed_total_renders_policy_token(airlock_exe: Path) -> None:
    proc = _run(
        _request(_candidate(total={"tag": "suppressed"}, breakdown={"tag": "suppressed"}))
    )
    assert proc.returncode == 0
    assert json.loads(proc.stdout)["total"] == "<10"


def test_shown_cells_and_zero_cell_allowed(airlock_exe: Path) -> None:
    proc = _run(
        _request(
            _candidate(
                total={"tag": "shown", "n": 40},
                breakdown={
                    "tag": "shown",
                    "cells": [
                        {"label": "array_direct_high_confidence", "count": 40},
                        {"label": "imputed_supported_conditional", "count": 0},
                    ],
                },
            )
        )
    )
    assert proc.returncode == 0
    assert json.loads(proc.stdout)["breakdown"] == [
        {"label": "array_direct_high_confidence", "count": 40},
        {"label": "imputed_supported_conditional", "count": 0},
    ]


def test_exact_threshold_k_accepted(airlock_exe: Path) -> None:
    proc = _run(
        _request(_candidate(total={"tag": "shown", "n": 10}, breakdown={"tag": "suppressed"}))
    )
    assert proc.returncode == 0
    assert json.loads(proc.stdout)["total"] == "~10"


def test_bypass_small_cell_refuses_with_empty_stdout(airlock_exe: Path) -> None:
    proc = _run(
        _request(
            _candidate(
                total={"tag": "shown", "n": 70},
                breakdown={
                    "tag": "shown",
                    "cells": [
                        {"label": "array_direct_high_confidence", "count": 70},
                        {"label": "imputed_supported_conditional", "count": 2},
                    ],
                },
            )
        )
    )
    assert proc.returncode == 1
    assert proc.stdout == b""
    assert b"release rejected" in proc.stderr


def test_unrounded_total_refused(airlock_exe: Path) -> None:
    proc = _run(
        _request(_candidate(total={"tag": "shown", "n": 23}, breakdown={"tag": "suppressed"}))
    )
    assert proc.returncode == 1
    assert proc.stdout == b""


def test_invalid_policy_refused(airlock_exe: Path) -> None:
    proc = _run(
        _request(
            _candidate(total={"tag": "shown", "n": 70}, breakdown={"tag": "suppressed"}),
            policy={"min_cell": 4, "round_to": 5},
        )
    )
    assert proc.returncode == 3
    assert proc.stdout == b""
    assert b"invalid policy" in proc.stderr


def test_unknown_field_malformed(airlock_exe: Path) -> None:
    proc = _run(
        _request(
            _candidate(total={"tag": "shown", "n": 70}, breakdown={"tag": "suppressed"}),
            extra={"extra": 1},
        )
    )
    assert proc.returncode == 2
    assert proc.stdout == b""
    assert b"unknown field: extra" in proc.stderr


def test_unknown_schema_malformed(airlock_exe: Path) -> None:
    body = _request(_candidate(total={"tag": "shown", "n": 70}, breakdown={"tag": "suppressed"}))
    body["schema"] = "tre-airlock/v0"
    proc = _run(body)
    assert proc.returncode == 2
    assert proc.stdout == b""


def test_missing_field_malformed(airlock_exe: Path) -> None:
    body = _request(_candidate(total={"tag": "shown", "n": 70}, breakdown={"tag": "suppressed"}))
    del body["candidate"]["breakdown"]
    proc = _run(body)
    assert proc.returncode == 2
    assert proc.stdout == b""
    assert b"missing field: breakdown" in proc.stderr


def test_negative_count_malformed(airlock_exe: Path) -> None:
    proc = _run(
        _request(_candidate(total={"tag": "shown", "n": -2}, breakdown={"tag": "suppressed"}))
    )
    assert proc.returncode == 2
    assert proc.stdout == b""


def test_duplicate_label_malformed(airlock_exe: Path) -> None:
    proc = _run(
        _request(
            _candidate(
                total={"tag": "shown", "n": 40},
                breakdown={
                    "tag": "shown",
                    "cells": [
                        {"label": "array_direct_high_confidence", "count": 20},
                        {"label": "array_direct_high_confidence", "count": 20},
                    ],
                },
            )
        )
    )
    assert proc.returncode == 2
    assert proc.stdout == b""
    assert b"duplicate cell label" in proc.stderr


def test_empty_stdin_malformed(airlock_exe: Path) -> None:
    proc = _run("")
    assert proc.returncode == 2
    assert proc.stdout == b""


def test_study_id_is_an_unknown_field_in_v2(airlock_exe: Path) -> None:
    # v2 removed study_id from the released representation entirely: strict parsing refuses it.
    body = _request(_candidate(total={"tag": "shown", "n": 70}, breakdown={"tag": "suppressed"}))
    body["candidate"]["study_id"] = "demo"
    proc = _run(body)
    assert proc.returncode == 2
    assert proc.stdout == b""
    assert b"unknown field: study_id" in proc.stderr
