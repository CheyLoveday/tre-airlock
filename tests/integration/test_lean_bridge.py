"""Integration: the bridge + transactional publisher against the REAL Lean adjudicator.

Effect-binding evidence (plan §9, issues #54/#55/#56): success returns an immutable
`AirlockDecision` whose payload bytes are the adjudicator's exact stdout; refusal raises with no
bytes; the publisher's canonical slot is attempt-scoped (refusal invalidates a stale success) and
its promotion is atomic. Skips if the binary is not built (`make airlock`).
"""
import hashlib
import json
import subprocess

import pytest

from ofh_feasibility import bridge
from ofh_feasibility.models import ReleaseCandidate

pytestmark = pytest.mark.integration


def _seam_policy(tmp_path, min_cell=10, round_to=5):
    path = tmp_path / "seam_policy.json"
    path.write_text(json.dumps({
        "schema": "tre-airlock-policy/v1", "policy_id": "seam", "version": "1",
        "min_cell": min_cell, "round_to": round_to, "adjudicator_sha256": None,
    }))
    return path


def _candidate(**over):
    base = dict(
        study_id="demo", cpra="10:119669928:C:G", client_total="~70", breakdown_suppressed=True,
        reported_cells=(), min_cell=10, round_to=5,
    )
    return ReleaseCandidate(**{**base, **over})


_BYPASS = dict(  # the deliberate small-cell bypass example from the airlock design
    client_total="~70", breakdown_suppressed=False,
    reported_cells=(("array_direct_high_confidence", 70), ("imputed_supported_conditional", 2)),
)


@pytest.fixture()
def exe():
    path = bridge._TRUSTED_EXE
    if not path.is_file():
        pytest.skip("airlock not built (make airlock)")
    return path


def test_success_returns_the_exact_lean_bytes_and_attests_the_binary(exe):
    candidate = _candidate()
    decision = bridge.authorize(candidate)
    direct = subprocess.run([str(exe)], input=decision.request_bytes, capture_output=True)
    assert direct.returncode == 0
    assert decision.payload_bytes == direct.stdout  # byte-for-byte: carried, never re-rendered
    assert decision.payload_bytes.endswith(b"\n")
    # attestation: the recorded digest is the digest of the executable actually used (issue #54).
    assert decision.adjudicator_sha256 == hashlib.sha256(exe.read_bytes()).hexdigest()
    assert decision.adjudicator_path == str(exe)
    assert decision.request_sha256 == hashlib.sha256(decision.request_bytes).hexdigest()
    assert decision.payload_sha256 == hashlib.sha256(decision.payload_bytes).hexdigest()


def test_subprocess_stdin_is_byte_identical_to_the_decision_request(exe, monkeypatch):
    # issue #56: spy on the adjudicator's stdin and prove it equals decision.request_bytes.
    captured = {}
    real_run = subprocess.run

    def spy(argv, **kwargs):
        captured["stdin"] = kwargs.get("input")
        return real_run(argv, **kwargs)

    monkeypatch.setattr(bridge.subprocess, "run", spy)
    decision = bridge.authorize(_candidate())
    assert captured["stdin"] == decision.request_bytes


def test_recorded_request_digest_is_independent_of_later_object_state(exe):
    # issue #56: the decision is captured evidence — nothing after adjudication can move it.
    decision = bridge.authorize(_candidate())
    before = decision.request_sha256
    _ = _candidate(client_total="~95")  # build different objects afterwards
    assert decision.request_sha256 == before
    assert hashlib.sha256(decision.request_bytes).hexdigest() == before


def test_plan_bypass_candidate_is_refused_with_no_bytes(exe):
    with pytest.raises(bridge.AirlockRefusal, match="release refused") as exc:
        bridge.authorize(_candidate(**_BYPASS))
    assert exc.value.exit_code == bridge.EXIT_REJECTED


def test_invalid_policy_is_refused(exe, tmp_path, monkeypatch):
    # the platform record itself could only carry an invalid Γ by platform error; Lean refuses
    # it independently (exit 3) — Policy.Valid and policy AUTHORISATION are separate conditions.
    monkeypatch.setattr(bridge, "_TEST_POLICY_OVERRIDE", _seam_policy(tmp_path, 4, 3))
    with pytest.raises(bridge.AirlockRefusal) as exc:
        bridge.authorize(_candidate(client_total="~4", min_cell=4, round_to=3))
    assert exc.value.exit_code == bridge.EXIT_INVALID_POLICY


def test_refusal_message_carries_reference_diagnostics(exe):
    candidate = _candidate(
        client_total="~40", breakdown_suppressed=False,
        reported_cells=(("array_direct_high_confidence", 5),),
    )
    with pytest.raises(bridge.AirlockRefusal, match="reference-predicate diagnostics"):
        bridge.authorize(candidate)


# --- the transaction (issue #55): attempt-scoped canonical slot -------------------------------


def test_success_then_refusal_leaves_no_canonical_payload(exe, tmp_path):
    pending = tmp_path / "airlock_pending"
    decision = bridge.publish_release(_candidate(), pending)
    target = pending / bridge.RELEASE_PAYLOAD
    assert target.read_bytes() == decision.payload_bytes
    assert (pending / bridge.RELEASE_READY).is_file()  # committed generation

    with pytest.raises(bridge.AirlockRefusal):
        bridge.publish_release(_candidate(**_BYPASS), pending)
    assert not target.exists(), "stale successful payload survived a refused attempt"
    assert not (pending / bridge.RELEASE_READY).exists()
    # the prior generation was rotated to INTERNAL history, keyed by its digest — not lost.
    rotated = tmp_path / bridge.RELEASE_HISTORY_DIR / f"release-{decision.payload_sha256}.json"
    assert rotated.read_bytes() == decision.payload_bytes


def test_success_then_missing_binary_leaves_no_canonical_payload(exe, tmp_path, monkeypatch):
    pending = tmp_path / "airlock_pending"
    bridge.publish_release(_candidate(), pending)
    monkeypatch.setattr(bridge, "_TEST_EXECUTABLE_OVERRIDE", tmp_path / "gone")
    with pytest.raises(RuntimeError, match="make airlock"):
        bridge.publish_release(_candidate(), pending)
    assert not (pending / bridge.RELEASE_PAYLOAD).exists()


def test_success_then_timeout_leaves_no_canonical_payload(exe, tmp_path, monkeypatch):
    pending = tmp_path / "airlock_pending"
    bridge.publish_release(_candidate(), pending)

    def boom(argv, **kwargs):
        raise subprocess.TimeoutExpired(argv, 1)

    monkeypatch.setattr(bridge.subprocess, "run", boom)
    with pytest.raises(subprocess.TimeoutExpired):
        bridge.publish_release(_candidate(), pending)
    assert not (pending / bridge.RELEASE_PAYLOAD).exists()


def test_success_replaces_success_with_exact_new_bytes(exe, tmp_path):
    pending = tmp_path / "airlock_pending"
    first = bridge.publish_release(_candidate(client_total="~70"), pending)
    second = bridge.publish_release(_candidate(client_total="~95"), pending)
    target = pending / bridge.RELEASE_PAYLOAD
    assert target.read_bytes() == second.payload_bytes != first.payload_bytes
    direct = subprocess.run([str(exe)], input=second.request_bytes, capture_output=True)
    assert target.read_bytes() == direct.stdout  # exact fresh-Lean byte equality survives


def test_failed_promotion_leaves_canonical_path_absent(exe, tmp_path, monkeypatch):
    # simulate a crash after the temp file is fully written but before promotion.
    pending = tmp_path / "airlock_pending"

    def refuse_replace(src, dst):
        raise OSError("simulated crash before promotion")

    monkeypatch.setattr(bridge.os, "replace", refuse_replace)
    with pytest.raises(OSError, match="simulated crash"):
        bridge.publish_release(_candidate(), pending)
    assert not (pending / bridge.RELEASE_PAYLOAD).exists()
    staging = tmp_path / bridge._STAGING_DIR
    assert not any(staging.iterdir()) if staging.is_dir() else True  # temp cleaned up


def test_publish_retains_the_exact_request_preimage(exe, tmp_path):
    # issue #56 (preferred replay option): the exact request bytes are retained internally.
    pending = tmp_path / "airlock_pending"
    decision = bridge.publish_release(_candidate(), pending)
    evidence = bridge.request_evidence_path(tmp_path, decision.request_sha256)
    assert evidence.read_bytes() == decision.request_bytes


def test_success_then_each_failure_mode_leaves_no_canonical_payload(exe, tmp_path, monkeypatch):
    # issue #55 acceptance: invalid policy, malformed request, unexpected non-zero exit, and a
    # write/fsync failure BEFORE promotion — each after a prior success in the same directory.
    pending = tmp_path / "airlock_pending"
    target = pending / bridge.RELEASE_PAYLOAD

    def rerun_success():
        bridge.publish_release(_candidate(), pending)
        assert target.exists()

    # 1. invalid policy (exit 3) via a seam-injected platform record.
    rerun_success()
    monkeypatch.setattr(bridge, "_TEST_POLICY_OVERRIDE", _seam_policy(tmp_path, 4, 3))
    with pytest.raises(bridge.AirlockRefusal):
        bridge.publish_release(_candidate(client_total="~4", min_cell=4, round_to=3), pending)
    assert not target.exists()
    monkeypatch.setattr(bridge, "_TEST_POLICY_OVERRIDE", None)

    # 2. malformed request (the strict builder refuses before any invocation).
    rerun_success()
    with pytest.raises(ValueError, match="unmappable client_total"):
        bridge.publish_release(_candidate(client_total="20"), pending)
    assert not target.exists()

    # 3. unexpected non-zero exit from the adjudicator (seam-injected exit 7).
    rerun_success()
    weird = tmp_path / "exit7"
    weird.write_text("#!/bin/sh\nexit 7\n")
    weird.chmod(0o755)
    monkeypatch.setattr(bridge, "_TEST_EXECUTABLE_OVERRIDE", weird)
    with pytest.raises(bridge.AirlockRefusal) as exc:
        bridge.publish_release(_candidate(), pending)
    assert exc.value.exit_code == 7
    assert not target.exists()
    monkeypatch.setattr(bridge, "_TEST_EXECUTABLE_OVERRIDE", None)

    # 4. write/fsync failure BEFORE promotion: canonical absent, staging cleaned.
    rerun_success()

    def failing_fsync(fd):
        raise OSError("simulated fsync failure")

    monkeypatch.setattr(bridge.os, "fsync", failing_fsync)
    with pytest.raises(OSError, match="simulated fsync"):
        bridge.publish_release(_candidate(), pending)
    monkeypatch.undo()
    assert not target.exists()
    staging = tmp_path / bridge._STAGING_DIR
    assert not staging.is_dir() or not any(staging.iterdir())


def test_bridge_level_success_refusal_success_recovery(exe, tmp_path):
    # the full issue #55 regression triple at bridge level, one pending directory throughout.
    pending = tmp_path / "airlock_pending"
    target = pending / bridge.RELEASE_PAYLOAD

    first = bridge.publish_release(_candidate(client_total="~70"), pending)
    assert target.read_bytes() == first.payload_bytes

    with pytest.raises(bridge.AirlockRefusal):
        bridge.publish_release(_candidate(**_BYPASS), pending)
    assert not target.exists()

    second = bridge.publish_release(_candidate(client_total="~95"), pending)
    assert target.read_bytes() == second.payload_bytes != first.payload_bytes


def test_refusal_clears_stale_batch_and_final_manifests(exe, tmp_path):
    # issue #55: generation cleanup beyond the single-variant case — a refused attempt must not
    # inherit the previous generation's pending manifests (batch/final names as written by
    # pipeline.orchestrate_batch / finalize_eligible).
    pending = tmp_path / "airlock_pending"
    bridge.publish_release(_candidate(), pending)
    (pending / "batch_airlock_manifest.json").write_text("{}")
    (pending / "final_airlock_manifest.json").write_text("{}")

    with pytest.raises(bridge.AirlockRefusal):
        bridge.publish_release(_candidate(**_BYPASS), pending)
    assert not any(pending.iterdir()), list(pending.iterdir())


def test_attempt_lock_enforces_single_writer(exe, tmp_path):
    # issue #55: 'state AND enforce' — a held lock fails a second attempt closed.
    pending = tmp_path / "airlock_pending"
    lock = tmp_path / bridge._ATTEMPT_LOCK
    lock.parent.mkdir(parents=True, exist_ok=True)
    lock.touch()
    with pytest.raises(RuntimeError, match="another release attempt"):
        bridge.publish_release(_candidate(), pending)
    assert not (pending / bridge.RELEASE_PAYLOAD).exists()
    lock.unlink()
    bridge.publish_release(_candidate(), pending)  # released lock -> attempt proceeds
    assert not lock.exists()  # completed attempt releases the lock


def test_mutating_the_original_objects_cannot_move_the_recorded_digest(exe):
    # issue #56 acceptance, strengthened: the ORIGINAL candidate used in the authorize call.
    import pydantic

    candidate = _candidate()
    decision = bridge.authorize(candidate)
    before_sha = decision.request_sha256
    before_bytes = decision.request_bytes

    with pytest.raises(pydantic.ValidationError):
        candidate.client_total = "~95"  # frozen model: ordinary mutation is impossible
    object.__setattr__(candidate, "client_total", "~95")  # force past the freeze anyway
    assert candidate.client_total == "~95"  # the object really did change...
    assert decision.request_sha256 == before_sha  # ...and the captured evidence did not
    assert decision.request_bytes == before_bytes


# --- committed-generation semantics (second-review blocker 3) ---------------------------------


def test_caller_failure_inside_the_transaction_leaves_no_committed_generation(exe, tmp_path):
    # simulates an internal-artefact or audit-append failure AFTER Lean success: the payload was
    # placed, but the commit receipt never lands and the rollback clears the canonical slot.
    pending = tmp_path / "airlock_pending"
    with pytest.raises(RuntimeError, match="simulated caller failure"):
        with bridge.release_transaction(_candidate(), pending) as decision:
            assert (pending / bridge.RELEASE_PAYLOAD).read_bytes() == decision.payload_bytes
            assert not (pending / bridge.RELEASE_READY).exists()  # not yet committed
            raise RuntimeError("simulated caller failure")
    assert not (pending / bridge.RELEASE_PAYLOAD).exists()
    assert not (pending / bridge.RELEASE_READY).exists()


def test_directory_fsync_failure_after_promotion_rolls_back(exe, tmp_path, monkeypatch):
    # the review's specific trace: os.replace succeeded, the directory fsync after it fails.
    pending = tmp_path / "airlock_pending"
    real_fsync = bridge.os.fsync
    calls = {"n": 0}

    def flaky_fsync(fd):
        calls["n"] += 1
        if calls["n"] == 2:  # 1st = payload file fsync; 2nd = pending-dir fsync after replace
            raise OSError("simulated dir-fsync failure")
        return real_fsync(fd)

    monkeypatch.setattr(bridge.os, "fsync", flaky_fsync)
    with pytest.raises(OSError, match="dir-fsync"):
        bridge.publish_release(_candidate(), pending)
    monkeypatch.undo()
    assert not (pending / bridge.RELEASE_PAYLOAD).exists()
    assert not (pending / bridge.RELEASE_READY).exists()


def test_uncommitted_payload_is_not_verifiable_and_is_rotated_by_the_next_attempt(exe, tmp_path):
    # simulate a hard death between payload placement and commit: payload without receipt.
    pending = tmp_path / "airlock_pending"
    pending.mkdir(parents=True)
    (pending / bridge.RELEASE_PAYLOAD).write_bytes(b'{"orphan":true}\n')
    report = bridge.verify_release_generation(tmp_path)
    assert report["ok"] is False
    assert any("uncommitted" in f for f in report["failures"])
    decision = bridge.publish_release(_candidate(), pending)  # next attempt rotates the orphan
    assert (pending / bridge.RELEASE_PAYLOAD).read_bytes() == decision.payload_bytes
    _bind_ledger(tmp_path, decision)
    assert bridge.verify_release_generation(tmp_path)["ok"] is True


def _bind_ledger(results_dir, decision):
    """Append the minimal ledger event a production transaction would have written."""
    event = {"airlock": bridge.ready_receipt(decision, results_dir)}
    (results_dir / "audit_ledger.jsonl").write_text(json.dumps(event) + "\n")


# --- generation verification (second-review item 5) -------------------------------------------


def test_verifier_passes_a_committed_generation_and_replays_it(exe, tmp_path):
    pending = tmp_path / "airlock_pending"
    decision = bridge.publish_release(_candidate(), pending)
    _bind_ledger(tmp_path, decision)
    report = bridge.verify_release_generation(tmp_path)
    assert report == {"ok": True, "generation": True, "failures": []}


def test_verifier_requires_a_ledger_binding(exe, tmp_path):
    # a committed generation with no ledger event is not fully evidenced: fail closed.
    pending = tmp_path / "airlock_pending"
    bridge.publish_release(_candidate(), pending)
    report = bridge.verify_release_generation(tmp_path)
    assert report["ok"] is False
    assert any("audit ledger" in f for f in report["failures"])


def test_verifier_detects_a_self_consistent_forged_generation(exe, tmp_path):
    # the second review's confirmed refutation: swap in a WHOLE forged generation — payload
    # regenerated through the REAL adjudicator (replay-valid), receipt and evidence rewritten to
    # match. Only the Merkle-rooted ledger still records the original figures; the verifier must
    # catch the mismatch.
    pending = tmp_path / "airlock_pending"
    genuine = bridge.publish_release(_candidate(client_total="~70"), pending)
    _bind_ledger(tmp_path, genuine)

    forged = bridge.authorize(_candidate(client_total="~700"))  # inflated but adjudicator-valid
    (pending / bridge.RELEASE_PAYLOAD).write_bytes(forged.payload_bytes)
    receipt = bridge.ready_receipt(forged, tmp_path)
    (pending / bridge.RELEASE_READY).write_bytes(
        (json.dumps(receipt, sort_keys=True, separators=(",", ":")) + "\n").encode()
    )
    evidence = bridge.request_evidence_path(tmp_path, forged.request_sha256)
    evidence.parent.mkdir(parents=True, exist_ok=True)
    evidence.write_bytes(forged.request_bytes)

    report = bridge.verify_release_generation(tmp_path)
    assert report["ok"] is False
    assert any("ledger" in f for f in report["failures"]), report["failures"]


def test_verifier_detects_payload_mutation_after_the_run(exe, tmp_path):
    pending = tmp_path / "airlock_pending"
    decision = bridge.publish_release(_candidate(), pending)
    _bind_ledger(tmp_path, decision)
    target = pending / bridge.RELEASE_PAYLOAD
    mutated = target.read_bytes().replace(b"~70", b"~7000")
    assert mutated != target.read_bytes()  # the mutation must actually change the payload
    target.write_bytes(mutated)
    report = bridge.verify_release_generation(tmp_path)
    assert report["ok"] is False
    assert any("payload sha256" in f for f in report["failures"])


def test_verifier_detects_evidence_mutation(exe, tmp_path):
    pending = tmp_path / "airlock_pending"
    decision = bridge.publish_release(_candidate(), pending)
    _bind_ledger(tmp_path, decision)
    evidence = bridge.request_evidence_path(tmp_path, decision.request_sha256)
    evidence.write_bytes(evidence.read_bytes() + b" ")
    report = bridge.verify_release_generation(tmp_path)
    assert report["ok"] is False
    assert any("preimage" in f for f in report["failures"])


def test_verifier_flags_replay_unavailable_on_adjudicator_change(exe, tmp_path, monkeypatch):
    pending = tmp_path / "airlock_pending"
    decision = bridge.publish_release(_candidate(), pending)
    _bind_ledger(tmp_path, decision)
    other = tmp_path / "other-binary"
    other.write_bytes(b"#!/bin/sh\nexit 0\n")
    monkeypatch.setattr(bridge, "_TEST_EXECUTABLE_OVERRIDE", other)
    report = bridge.verify_release_generation(tmp_path)
    assert report["ok"] is False
    assert any("replay not possible" in f for f in report["failures"])
