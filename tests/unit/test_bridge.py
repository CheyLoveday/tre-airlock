"""Unit tests: the strict request builder + the trusted policy/adjudicator bindings.

`airlock.build_airlock_request` serialises a candidate into the strict `tre-airlock/v2` request
under the PLATFORM-authorised policy (never the analysis config or the candidate), mirroring the
Lean parser's closed value language: approved label vocabulary, charset/length-capped study id,
parsed CPRA subject, bounded counts. The bridge binds release authority to one platform-owned
executable and one platform-owned policy record — neither the process environment nor analyst
configuration can substitute them; tests reach fakes only through the private `_TEST_*` seams.
"""
import hashlib
import json
from pathlib import Path

import pytest

from ofh_feasibility import airlock, bridge
from ofh_feasibility.models import ReleaseCandidate

pytestmark = pytest.mark.unit

LABEL_A, LABEL_B = airlock.APPROVED_CELL_LABELS


def _policy(min_cell=10, round_to=5, adjudicator_sha256=None):
    return bridge.TrustedReleasePolicy(
        policy_id="test-policy", version="1", min_cell=min_cell, round_to=round_to,
        adjudicator_sha256=adjudicator_sha256, policy_sha256="0" * 64,
    )


def _policy_file(tmp_path, min_cell=10, round_to=5, adjudicator_sha256=None) -> Path:
    path = tmp_path / "release_policy.json"
    path.write_text(json.dumps({
        "schema": "tre-airlock-policy/v1", "policy_id": "seam-policy", "version": "1",
        "min_cell": min_cell, "round_to": round_to, "adjudicator_sha256": adjudicator_sha256,
    }))
    return path


def _candidate(**over):
    base = dict(
        study_id="S", cpra="10:1:C:G", client_total="~20", breakdown_suppressed=True,
        reported_cells=(), min_cell=10, round_to=5,
    )
    return ReleaseCandidate(**{**base, **over})


# --- the strict request builder (pure) -------------------------------------------------------


def test_shown_total_maps_structurally():
    req = airlock.build_airlock_request(_candidate(client_total="~70"), _policy())
    assert req["schema"] == "tre-airlock/v2"
    assert req["candidate"]["total"] == {"tag": "shown", "n": 70}
    assert req["candidate"]["breakdown"] == {"tag": "suppressed"}


def test_suppressed_token_maps_structurally():
    req = airlock.build_airlock_request(_candidate(client_total="<10"), _policy())
    assert req["candidate"]["total"] == {"tag": "suppressed"}


def test_candidate_policy_disagreement_refuses_before_adjudication():
    # the analysis cannot choose the policy that judges its own release: a candidate produced
    # under weaker SDC settings than the platform-authorised Γ refuses at serialisation.
    weak = _candidate(client_total="~5", min_cell=5, round_to=1)
    with pytest.raises(ValueError, match="platform-authorised policy"):
        airlock.build_airlock_request(weak, _policy(min_cell=10, round_to=5))


def test_request_policy_is_the_platform_policy():
    req = airlock.build_airlock_request(_candidate(), _policy(min_cell=10, round_to=5))
    assert req["policy"] == {"min_cell": 10, "round_to": 5}


def test_subject_id_carries_the_cpra():
    req = airlock.build_airlock_request(_candidate(cpra="10:119669928:C:G"), _policy())
    assert req["candidate"]["subject_id"] == "10:119669928:C:G"


def test_multi_cpra_subject_is_accepted():
    req = airlock.build_airlock_request(_candidate(cpra="10:1:C:G+17:43044295:G:A"), _policy())
    assert req["candidate"]["subject_id"] == "10:1:C:G+17:43044295:G:A"


@pytest.mark.parametrize("subject", [
    "I157T", "free text", "10:1:C", "23:1:C:G", "10:0:C:G", "10:01:C:G", "10:1:C:Z",
    "10:1::G", "", "+".join(["10:1:C:G"] * 17),
])
def test_out_of_language_subjects_fail_fast(subject):
    with pytest.raises(ValueError, match="subject"):
        airlock.build_airlock_request(_candidate(cpra=subject), _policy())


def test_study_id_never_reaches_the_wire():
    # v2: the released representation carries no free-form string field — study identity is
    # INTERNAL evidence only, whatever the candidate's study_id contains.
    req = airlock.build_airlock_request(
        _candidate(study_id="PERSON-ALPHA-CONFIDENTIAL-DATA"), _policy()
    )
    assert "study_id" not in req["candidate"]
    assert "PERSON-ALPHA-CONFIDENTIAL-DATA" not in str(req)


def test_shown_breakdown_maps_cells_in_order():
    candidate = _candidate(
        client_total="~40", breakdown_suppressed=False,
        reported_cells=((LABEL_A, 25), (LABEL_B, 15)),
    )
    req = airlock.build_airlock_request(candidate, _policy())
    assert req["candidate"]["breakdown"] == {
        "tag": "shown",
        "cells": [{"label": LABEL_A, "count": 25}, {"label": LABEL_B, "count": 15}],
    }


def test_unapproved_label_fails_fast():
    candidate = _candidate(
        client_total="~40", breakdown_suppressed=False,
        reported_cells=(("participant_record_xyz", 10),),
    )
    with pytest.raises(ValueError, match="approved vocabulary"):
        airlock.build_airlock_request(candidate, _policy())


@pytest.mark.parametrize("token", ["20", "<5", "<10x", "<banana", "~", "~x", "~-5", "",
                                   f"~{10**9 + 5}"])
def test_unmappable_total_token_fails_fast(token):
    with pytest.raises(ValueError, match="unmappable client_total"):
        airlock.build_airlock_request(_candidate(client_total=token), _policy())


def test_negative_cell_count_fails_fast():
    candidate = _candidate(
        client_total="~40", breakdown_suppressed=False, reported_cells=((LABEL_A, -5),)
    )
    with pytest.raises(ValueError, match="bounded non-negative"):
        airlock.build_airlock_request(candidate, _policy())


def test_duplicate_cell_labels_fail_fast():
    candidate = _candidate(
        client_total="~40", breakdown_suppressed=False,
        reported_cells=((LABEL_A, 15), (LABEL_A, 25)),
    )
    with pytest.raises(ValueError, match="duplicate"):
        airlock.build_airlock_request(candidate, _policy())


def test_suppressed_breakdown_with_cells_fails_fast():
    # never silently drop cells at the boundary (permissive-filterMap ban, plan §8).
    candidate = _candidate(
        client_total="~40", breakdown_suppressed=True, reported_cells=((LABEL_A, 15),)
    )
    with pytest.raises(ValueError, match="suppressed breakdown"):
        airlock.build_airlock_request(candidate, _policy())


def test_encode_request_is_compact_and_deterministic():
    req = airlock.build_airlock_request(_candidate(), _policy())
    raw = bridge.encode_request(req)
    assert raw == bridge.encode_request(req)
    assert b" " not in raw  # compact separators: canonical audit-hashable form


# --- trusted policy binding (second-review blocker 1) -----------------------------------------


def test_trusted_policy_loads_from_the_platform_record():
    policy = bridge.load_trusted_policy()
    assert policy.policy_id and policy.version
    assert policy.min_cell == 10 and policy.round_to == 5
    raw = bridge._TRUSTED_POLICY_FILE.read_bytes()
    assert policy.policy_sha256 == hashlib.sha256(raw).hexdigest()


def test_analyst_config_cannot_change_the_policy():
    # weakening sdc_min_cell in an analyst-supplied config changes NOTHING about Γ: the policy
    # comes from the platform record, and the weakened candidate refuses at the mismatch gate.
    policy = bridge.load_trusted_policy()
    assert (policy.min_cell, policy.round_to) == (10, 5)
    weak_candidate = _candidate(client_total="~5", min_cell=5, round_to=1)
    with pytest.raises(ValueError, match="platform-authorised policy"):
        airlock.build_airlock_request(weak_candidate, policy)


def test_missing_policy_record_is_a_hard_failure(monkeypatch, tmp_path):
    monkeypatch.setattr(bridge, "_TEST_POLICY_OVERRIDE", tmp_path / "nonexistent.json")
    with pytest.raises(RuntimeError, match="platform deployment record"):
        bridge.authorize(_candidate())


@pytest.mark.parametrize("mutation", [
    lambda d: d.update(extra=1),
    lambda d: d.pop("policy_id"),
    lambda d: d.update(schema="tre-airlock-policy/v2"),
    lambda d: d.update(min_cell="10"),
    lambda d: d.update(adjudicator_sha256="short"),
])
def test_malformed_policy_record_fails_closed(monkeypatch, tmp_path, mutation):
    data = {
        "schema": "tre-airlock-policy/v1", "policy_id": "p", "version": "1",
        "min_cell": 10, "round_to": 5, "adjudicator_sha256": None,
    }
    mutation(data)
    path = tmp_path / "policy.json"
    path.write_text(json.dumps(data))
    monkeypatch.setattr(bridge, "_TEST_POLICY_OVERRIDE", path)
    with pytest.raises(RuntimeError, match="airlock"):
        bridge.authorize(_candidate())


# --- trusted executable binding (issue #54) ---------------------------------------------------


def test_environment_cannot_substitute_the_adjudicator(monkeypatch, tmp_path):
    # the forged-executable attack: an exit-0 script that prints a valid-looking payload.
    forged = tmp_path / "forged"
    marker = tmp_path / "invoked"
    forged.write_text(
        "#!/bin/sh\n"
        f"touch {marker}\n"
        "printf '{\"schema\":\"tre-airlock/v1\",\"status\":\"released\",\"forged\":true}\\n'\n"
        "exit 0\n"
    )
    forged.chmod(0o755)
    monkeypatch.setenv("OFH_AIRLOCK_BIN", str(forged))
    # the binding ignores the environment entirely: the resolved adjudicator is the platform one.
    assert bridge._adjudicator() == bridge._TRUSTED_EXE
    if bridge._TRUSTED_EXE.is_file():
        decision = bridge.authorize(_candidate())
        assert not marker.exists(), "forged executable was invoked"
        assert b"forged" not in decision.payload_bytes
        assert decision.adjudicator_path == str(bridge._TRUSTED_EXE)


def test_public_api_exposes_no_executable_or_policy_parameter():
    import inspect

    for fn in (bridge.authorize, bridge.publish_release, bridge.release_transaction):
        params = set(inspect.signature(fn).parameters)
        banned = {"exe", "executable", "path", "runner", "command", "bin", "policy", "cfg",
                  "config"}
        assert not params & banned, fn


def test_missing_binary_is_a_hard_failure(monkeypatch, tmp_path):
    # fail closed: without the adjudicator there is NO release and NO Python fallback.
    monkeypatch.setattr(bridge, "_TEST_EXECUTABLE_OVERRIDE", tmp_path / "nonexistent")
    with pytest.raises(RuntimeError, match="make airlock"):
        bridge.authorize(_candidate())


def test_non_regular_file_adjudicator_is_a_hard_failure(monkeypatch, tmp_path):
    # a directory (or any non-regular file) at the adjudicator path fails closed pre-invocation.
    monkeypatch.setattr(bridge, "_TEST_EXECUTABLE_OVERRIDE", tmp_path)
    with pytest.raises(RuntimeError, match="make airlock"):
        bridge.authorize(_candidate())


def test_digest_pin_mismatch_refuses_before_invocation(monkeypatch, tmp_path):
    # the pin is a PLATFORM record field (mandatory trust anchor when set), not a module toggle.
    fake = tmp_path / "fake"
    marker = tmp_path / "invoked"
    fake.write_text(f"#!/bin/sh\ntouch {marker}\nexit 0\n")
    fake.chmod(0o755)
    monkeypatch.setattr(bridge, "_TEST_EXECUTABLE_OVERRIDE", fake)
    monkeypatch.setattr(
        bridge, "_TEST_POLICY_OVERRIDE", _policy_file(tmp_path, adjudicator_sha256="0" * 64)
    )
    with pytest.raises(RuntimeError, match="attestation mismatch"):
        bridge.authorize(_candidate())
    assert not marker.exists(), "executable ran despite failed attestation"


def test_digest_pin_match_allows_invocation(monkeypatch, tmp_path):
    fake = tmp_path / "fake"
    fake.write_text("#!/bin/sh\nprintf 'x\\n'\nexit 1\n")  # refusal path is fine here
    fake.chmod(0o755)
    monkeypatch.setattr(bridge, "_TEST_EXECUTABLE_OVERRIDE", fake)
    pin = hashlib.sha256(fake.read_bytes()).hexdigest()
    monkeypatch.setattr(
        bridge, "_TEST_POLICY_OVERRIDE", _policy_file(tmp_path, adjudicator_sha256=pin)
    )
    with pytest.raises(bridge.AirlockRefusal):  # pin passed; the fake then refused (exit 1)
        bridge.authorize(_candidate())


def test_decision_is_immutable(monkeypatch, tmp_path):
    import dataclasses

    fake = tmp_path / "fake"
    fake.write_text("#!/bin/sh\nprintf '{\"ok\":true}\\n'\nexit 0\n")
    fake.chmod(0o755)
    monkeypatch.setattr(bridge, "_TEST_EXECUTABLE_OVERRIDE", fake)
    decision = bridge.authorize(_candidate())
    with pytest.raises(dataclasses.FrozenInstanceError):
        decision.payload_bytes = b"tampered"  # type: ignore[misc]
    assert decision.policy_id == bridge.load_trusted_policy().policy_id
