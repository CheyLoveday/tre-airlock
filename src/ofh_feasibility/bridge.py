"""bridge — trusted policy + adjudicator binding, transactional publication, verification (shell).

This module is the ONLY supported path to the canonical release payload, and it binds BOTH
authority inputs to platform-owned records (second-review blockers 1, 3, 5, 6):

- **Trusted policy Γ** is loaded from the platform deployment record `platform/release_policy.json`
  — never from the analysis config, the candidate, the environment, or any analyst-reachable
  parameter. `Policy.Valid` (internal coherence, judged by Lean) and policy AUTHORISATION (the
  platform owning Γ) are separate conditions: the analysis cannot select the rule it is judged
  by, and a candidate whose declared policy fields disagree with Γ refuses before adjudication.
- **The adjudicator executable** is a fixed platform constant, SHA-256-attested on every
  adjudication; when the policy record pins `adjudicator_sha256`, a mismatch refuses BEFORE
  invocation. Tests substitute either only through the private `_TEST_*` seams, which production
  code never assigns (statically enforced).
- Every adjudication produces one immutable `AirlockDecision` carrying the EXACT request bytes,
  the EXACT payload bytes, and the digests of request, payload, executable, and policy. Nothing
  is reconstructed after the fact; audit records copy these fields.
- `release_transaction` is the single release transaction used by every egress site: O_EXCL
  attempt lock → rotate the prior generation out of the canonical slot → adjudicate → place the
  payload + retained request preimage (uncommitted) → caller writes internal artefacts and the
  audit event → `release.ready` receipt lands LAST as the atomic COMMIT marker. Any failure at
  any phase — refusal, timeout, crash, missing binary, evidence/audit/internal-write failure —
  leaves NO COMMITTED generation: either the canonical path is absent, or it lacks its receipt
  and is therefore not transferable. Transfer consumers MUST verify `release.ready`
  (`verify_release_generation` / `ofh-feasibility audit verify` do).

Trust boundary (platform TCB): Lean formally guarantees that a successful adjudication rendered
its payload from a proof-indexed `AirlockExport` over a value-closed release language. The
policy/executable binding, this bridge/publisher, and the filesystem are the OPERATIONAL half —
disciplined, statically-guarded, tested Python, attested by digests, not Lean-proved. In-process
Python offers no memory isolation: if analyst-controlled code runs in the SAME interpreter it
could monkeypatch this module, so production deployments must run adjudication/publication as a
separate platform-owned process with a read-only executable, a pinned digest, and no test seams.

Concurrency: one release attempt per results directory, ENFORCED by the O_EXCL attempt lock held
for the whole transaction. A hard crash leaves the lock in place deliberately for operator review.

Replay vs verification: the digests VERIFY separately retained artefacts; byte-for-byte REPLAY
re-runs the attested adjudicator over the retained request preimage — available only while an
executable matching the recorded digest is available.
"""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import tempfile
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

from . import airlock

if TYPE_CHECKING:
    from .models import ReleaseCandidate

_REPO_ROOT = Path(__file__).resolve().parents[2]

#: Platform-owned trusted adjudicator (platform TCB). Not configurable from the environment or
#: the analysis config. In a deployed TRE: an absolute platform-managed, read-only path.
_TRUSTED_EXE = _REPO_ROOT / "formal" / ".lake" / "build" / "bin" / "airlock"

#: Platform-owned trusted release policy Γ (platform TCB). See platform/README.md.
_TRUSTED_POLICY_FILE = _REPO_ROOT / "platform" / "release_policy.json"

#: PRIVATE TEST SEAMS. Production code never assigns these (statically enforced); tests may
#: monkeypatch them to inject a substitute adjudicator / policy record.
_TEST_EXECUTABLE_OVERRIDE: Path | None = None
_TEST_POLICY_OVERRIDE: Path | None = None

_TIMEOUT_S = 60

RELEASE_PAYLOAD = "release.json"  # the canonical releasable artefact inside airlock_pending/
RELEASE_READY = "release.ready"  # the COMMIT receipt: a payload without it is NOT transferable
RELEASE_HISTORY_DIR = "release_history"  # INTERNAL: rotated prior-generation payloads
EVIDENCE_DIR = "airlock_evidence"  # INTERNAL: retained exact request bytes (replay preimages)
_STAGING_DIR = ".release_staging"  # non-canonical same-filesystem staging for atomic writes
_ATTEMPT_LOCK = ".release_attempt.lock"  # O_EXCL single-writer lock, held per transaction

_POLICY_SCHEMA = "tre-airlock-policy/v1"
_POLICY_KEYS = {"schema", "policy_id", "version", "min_cell", "round_to", "adjudicator_sha256"}

#: exit codes fixed by the adjudicator CLI (formal/TreAirlockMain.lean).
EXIT_RELEASED = 0
EXIT_REJECTED = 1
EXIT_MALFORMED = 2
EXIT_INVALID_POLICY = 3


@dataclass(frozen=True)
class TrustedReleasePolicy:
    """The authorised Γ, as loaded from the platform deployment record (immutable)."""

    policy_id: str
    version: str
    min_cell: int
    round_to: int
    adjudicator_sha256: str | None
    policy_sha256: str  # digest of the exact policy-record bytes


@dataclass(frozen=True)
class AirlockDecision:
    """Immutable evidence of one successful adjudication — the exact bytes, never rebuilt."""

    schema: str
    request_bytes: bytes
    request_sha256: str
    payload_bytes: bytes
    payload_sha256: str
    adjudicator_path: str
    adjudicator_sha256: str
    policy_id: str
    policy_version: str
    policy_sha256: str


class AirlockRefusal(ValueError):
    """The Lean airlock refused the candidate: no proof, no export, no payload bytes."""

    def __init__(self, message: str, exit_code: int, reason: str) -> None:
        super().__init__(message)
        self.exit_code = exit_code
        self.reason = reason


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _adjudicator() -> Path:
    return _TEST_EXECUTABLE_OVERRIDE if _TEST_EXECUTABLE_OVERRIDE is not None else _TRUSTED_EXE


def _policy_file() -> Path:
    return _TEST_POLICY_OVERRIDE if _TEST_POLICY_OVERRIDE is not None else _TRUSTED_POLICY_FILE


def load_trusted_policy() -> TrustedReleasePolicy:
    """Load and strictly validate the platform-owned Γ (fail closed on any deviation)."""
    path = _policy_file()
    if not path.is_file():
        raise RuntimeError(
            f"airlock: trusted release policy not found at {path} — a platform deployment "
            "record is required; the analysis config cannot supply the release policy"
        )
    raw = path.read_bytes()
    data = json.loads(raw)
    if not isinstance(data, dict) or set(data) != _POLICY_KEYS:
        raise RuntimeError(f"airlock: malformed trusted policy record at {path}")
    if data["schema"] != _POLICY_SCHEMA:
        raise RuntimeError(f"airlock: unknown policy schema: {data['schema']!r}")
    for key in ("min_cell", "round_to"):
        value = data[key]
        if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
            raise RuntimeError(f"airlock: trusted policy {key} must be a positive integer")
    for key in ("policy_id", "version"):
        if not isinstance(data[key], str) or not data[key].strip():
            raise RuntimeError(f"airlock: trusted policy {key} must be a non-empty string")
    pin = data["adjudicator_sha256"]
    if pin is not None and not (isinstance(pin, str) and len(pin) == 64):
        raise RuntimeError("airlock: adjudicator_sha256 must be null or a sha256 hex digest")
    return TrustedReleasePolicy(
        policy_id=data["policy_id"],
        version=data["version"],
        min_cell=data["min_cell"],
        round_to=data["round_to"],
        adjudicator_sha256=pin,
        policy_sha256=_sha256_bytes(raw),
    )


def encode_request(request: dict) -> bytes:
    """Canonical compact encoding of the `tre-airlock/v1` request (the adjudicator's stdin)."""
    return json.dumps(request, separators=(",", ":")).encode()


def request_evidence_path(results_dir: str | Path, request_sha256: str) -> Path:
    """INTERNAL retention slot for the exact request bytes, keyed by their digest."""
    return Path(results_dir) / EVIDENCE_DIR / f"request-{request_sha256}.json"


def _resolve_and_attest_adjudicator(policy: TrustedReleasePolicy) -> tuple[Path, str]:
    """Fail closed unless the bound adjudicator exists as a regular file; attest its bytes.

    When the platform policy record pins `adjudicator_sha256`, a digest mismatch refuses
    BEFORE invocation (the mandatory production trust anchor; null only in this per-host repo).
    """
    exe = _adjudicator()
    if not exe.is_file():
        raise RuntimeError(
            f"airlock: Lean adjudicator not built at {exe} — run `make airlock` "
            "(cd formal && lake build); there is no Python fallback for release authority"
        )
    exe_sha = _sha256_bytes(exe.read_bytes())
    if policy.adjudicator_sha256 is not None and exe_sha != policy.adjudicator_sha256:
        raise RuntimeError(
            "airlock: adjudicator attestation mismatch — executable sha256 "
            f"{exe_sha} != pinned {policy.adjudicator_sha256}; refusing before invocation"
        )
    return exe, exe_sha


def authorize(candidate: ReleaseCandidate) -> AirlockDecision:
    """Adjudicate under the PLATFORM policy with the trusted Lean airlock; return evidence.

    Loads Γ from the platform record, attests the executable, builds and encodes the request
    exactly once (refusing candidates whose declared policy fields disagree with Γ), and on the
    proof-bearing success branch returns an immutable `AirlockDecision`. Every other outcome
    raises (fail closed); refusal messages append the Python reference predicate's reasons as
    NON-AUTHORITATIVE diagnostics.
    """
    policy = load_trusted_policy()
    exe, exe_sha = _resolve_and_attest_adjudicator(policy)
    request = airlock.build_airlock_request(candidate, policy)
    raw = encode_request(request)
    proc = subprocess.run([str(exe)], input=raw, capture_output=True, timeout=_TIMEOUT_S)
    if proc.returncode == EXIT_RELEASED:
        payload = proc.stdout
        if not payload.endswith(b"\n") or payload.count(b"\n") != 1:
            raise RuntimeError("airlock: adjudicator produced a non-canonical payload")
        return AirlockDecision(
            schema=request["schema"],
            request_bytes=raw,
            request_sha256=_sha256_bytes(raw),
            payload_bytes=payload,
            payload_sha256=_sha256_bytes(payload),
            adjudicator_path=str(exe),
            adjudicator_sha256=exe_sha,
            policy_id=policy.policy_id,
            policy_version=policy.version,
            policy_sha256=policy.policy_sha256,
        )
    reason = proc.stderr.decode(errors="replace").strip() or f"exit {proc.returncode}"
    hints = airlock.release_reasons(candidate)
    diagnostic = f" [reference-predicate diagnostics: {'; '.join(hints)}]" if hints else ""
    raise AirlockRefusal(
        f"airlock: release refused — {reason}{diagnostic}", proc.returncode, reason
    )


# --- transactional committed generation (one supported publisher for every egress site) --------


def ready_receipt(decision: AirlockDecision, results_dir: str | Path) -> dict:
    """The commit receipt content: binds payload, request, adjudicator, and policy digests."""
    return {
        "schema": decision.schema,
        "adjudicator": {
            "kind": "lean-runtime",
            "path": decision.adjudicator_path,
            "sha256": decision.adjudicator_sha256,
        },
        "policy": {
            "id": decision.policy_id,
            "version": decision.policy_version,
            "sha256": decision.policy_sha256,
        },
        "request": {
            "sha256": decision.request_sha256,
            "retained_internal_path": str(
                request_evidence_path(results_dir, decision.request_sha256)
            ),
        },
        "payload": {
            "sha256": decision.payload_sha256,
            "canonical_path": f"airlock_pending/{RELEASE_PAYLOAD}",
        },
    }


def _acquire_attempt_lock(results_dir: Path) -> Path:
    """Enforce the single-writer precondition with an O_EXCL lock (fail closed on contention)."""
    results_dir.mkdir(parents=True, exist_ok=True)
    lock = results_dir / _ATTEMPT_LOCK
    try:
        os.close(os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY))
    except FileExistsError:
        raise RuntimeError(
            f"airlock: another release attempt holds {lock} — one attempt per results "
            "directory; if no attempt is live (a crashed run), verify and remove the lock"
        ) from None
    return lock


def _invalidate_previous_generation(pending: Path) -> None:
    """Make the canonical slot the CURRENT attempt's: rotate the prior payload to INTERNAL
    history (keyed by content digest) and clear stale receipts/manifests/artefacts."""
    target = pending / RELEASE_PAYLOAD
    if target.is_file():
        stale = target.read_bytes()
        history = pending.parent / RELEASE_HISTORY_DIR
        history.mkdir(parents=True, exist_ok=True)
        os.replace(target, history / f"release-{_sha256_bytes(stale)}.json")
    if pending.is_dir():
        for leftover in pending.iterdir():
            if leftover.is_file():
                leftover.unlink()


def _atomic_write_exact(payload: bytes, target: Path) -> None:
    """Exact-byte atomic placement: staged temp (same filesystem) + fsync + os.replace +
    directory fsync. Bytes are never parsed, normalised, or re-encoded; any failure removes
    the temp file and leaves the target absent."""
    target.parent.mkdir(parents=True, exist_ok=True)
    staging = target.parent.parent / _STAGING_DIR
    staging.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(dir=staging, prefix="release-", suffix=".tmp")
    tmp = Path(tmp_name)
    try:
        with os.fdopen(fd, "wb") as fh:
            fh.write(payload)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp, target)
    finally:
        tmp.unlink(missing_ok=True)
    dir_fd = os.open(target.parent, os.O_RDONLY)
    try:
        os.fsync(dir_fd)
    finally:
        os.close(dir_fd)


def _rollback_uncommitted(pending: Path) -> None:
    """Remove this attempt's uncommitted artefacts from the canonical slot (fail closed)."""
    (pending / RELEASE_READY).unlink(missing_ok=True)
    (pending / RELEASE_PAYLOAD).unlink(missing_ok=True)


@contextmanager
def release_transaction(
    candidate: ReleaseCandidate, pending_dir: str | Path
) -> Iterator[AirlockDecision]:
    """The ONE supported release transaction (attempt-scoped, committed-generation semantics).

    Phases: lock → invalidate prior generation → adjudicate → retain request preimage → place
    payload (UNCOMMITTED) → yield to the caller for internal artefacts + the audit event →
    write the `release.ready` receipt LAST (the atomic COMMIT). Any exception at any phase
    rolls the uncommitted payload back out of the canonical slot; a hard process death between
    payload placement and commit leaves a payload WITHOUT a receipt, which no transfer consumer
    may treat as a release (verify_release_generation fails it, and the next attempt rotates it).

    `pending_dir` must sit directly under the run's results directory. Single writer per
    results directory is enforced by the attempt lock.
    """
    pending = Path(pending_dir)
    lock = _acquire_attempt_lock(pending.parent)
    try:
        _invalidate_previous_generation(pending)
        decision = authorize(candidate)  # raises on any non-proof outcome; slot stays absent
        try:
            evidence = request_evidence_path(pending.parent, decision.request_sha256)
            evidence.parent.mkdir(parents=True, exist_ok=True)
            evidence.write_bytes(decision.request_bytes)  # INTERNAL preimage, never releasable
            _atomic_write_exact(decision.payload_bytes, pending / RELEASE_PAYLOAD)
            yield decision  # caller: internal artefacts + audit event (may hash the payload)
            receipt = json.dumps(
                ready_receipt(decision, pending.parent), sort_keys=True, separators=(",", ":")
            ).encode() + b"\n"
            _atomic_write_exact(receipt, pending / RELEASE_READY)  # THE commit, last
        except BaseException:
            _rollback_uncommitted(pending)
            raise
    finally:
        lock.unlink(missing_ok=True)


def publish_release(candidate: ReleaseCandidate, pending_dir: str | Path) -> AirlockDecision:
    """Adjudicate + publish a committed generation with no interleaved caller writes."""
    with release_transaction(candidate, pending_dir) as decision:
        pass
    return decision


# --- generation verification (audit verify must check the artefacts, not just the ledger) ------


def _ledger_binding_failures(results: Path, receipt: dict) -> list[str]:
    """Cross-check the (unprotected) receipt against the tamper-evident Merkle ledger.

    The receipt is a plain file: an actor with write access could swap in a fully
    self-consistent forged generation (payload + receipt + evidence all rewritten, even
    replay-valid). The audit LEDGER is Merkle-rooted, so the committed generation must match the
    airlock record the ledger captured inside the transaction — a swapped generation cannot.
    """
    ledger = results / "audit_ledger.jsonl"
    if not ledger.is_file():
        return ["committed generation has no audit ledger to bind against"]
    airlock_records = []
    for line in ledger.read_text().splitlines():
        if not line.strip():
            continue
        try:
            event = json.loads(line)
        except ValueError:
            return ["unreadable audit ledger"]
        if isinstance(event, dict) and isinstance(event.get("airlock"), dict):
            airlock_records.append(event["airlock"])
    if not airlock_records:
        return ["committed generation has no airlock record in the audit ledger"]
    recorded = airlock_records[-1]  # the transaction appends its event before committing
    failures = []
    if recorded.get("payload", {}).get("sha256") != receipt.get("payload", {}).get("sha256"):
        failures.append(
            "receipt payload sha256 does not match the ledger's recorded airlock payload"
        )
    if recorded.get("request", {}).get("sha256") != receipt.get("request", {}).get("sha256"):
        failures.append(
            "receipt request sha256 does not match the ledger's recorded airlock request"
        )
    return failures


def verify_release_generation(results_dir: str | Path) -> dict:
    """Verify the current committed generation against receipt, LEDGER, evidence, adjudicator.

    Checks: the receipt exists and parses; H(release.json) equals the receipt's payload digest;
    the receipt's payload/request digests match the Merkle-rooted ledger's recorded airlock
    record (a plain-file receipt alone could be swapped wholesale — the ledger cannot);
    H(retained request) equals the receipt's request digest; the bound adjudicator's current
    digest equals the recorded one (replay availability); and REPLAY — re-running the attested
    adjudicator over the retained preimage reproduces the canonical bytes exactly. A payload
    without a valid matching receipt FAILS (uncommitted generation). No generation at all is
    reported ok=True with generation=False.
    """
    results = Path(results_dir)
    pending = results / "airlock_pending"
    payload_path = pending / RELEASE_PAYLOAD
    ready_path = pending / RELEASE_READY
    failures: list[str] = []
    if not payload_path.is_file() and not ready_path.is_file():
        return {"ok": True, "generation": False, "failures": []}
    if not ready_path.is_file():
        return {
            "ok": False,
            "generation": True,
            "failures": ["uncommitted generation: release.json present without release.ready"],
        }
    try:
        receipt = json.loads(ready_path.read_text())
    except ValueError:
        return {"ok": False, "generation": True, "failures": ["unreadable release.ready receipt"]}
    if not isinstance(receipt, dict) or not all(
        isinstance(receipt.get(k), dict) for k in ("payload", "request", "adjudicator", "policy")
    ):
        return {"ok": False, "generation": True, "failures": ["unreadable release.ready receipt"]}
    if not payload_path.is_file():
        return {
            "ok": False,
            "generation": True,
            "failures": ["release.ready present without release.json"],
        }
    payload_sha = _sha256_bytes(payload_path.read_bytes())
    if payload_sha != receipt.get("payload", {}).get("sha256"):
        failures.append("release.json does not match the receipt's payload sha256")
    failures.extend(_ledger_binding_failures(results, receipt))
    request_sha = receipt.get("request", {}).get("sha256", "")
    evidence = request_evidence_path(results, request_sha)
    if not evidence.is_file():
        failures.append("retained request preimage missing")
        request_bytes = None
    else:
        request_bytes = evidence.read_bytes()
        if _sha256_bytes(request_bytes) != request_sha:
            failures.append("retained request preimage does not match the recorded sha256")
    recorded_exe_sha = receipt.get("adjudicator", {}).get("sha256")
    exe = _adjudicator()
    if not exe.is_file():
        failures.append("attested adjudicator unavailable: replay not possible")
    elif _sha256_bytes(exe.read_bytes()) != recorded_exe_sha:
        failures.append(
            "current adjudicator sha256 differs from the recorded one: replay not possible"
        )
    elif request_bytes is not None and not failures:
        proc = subprocess.run([str(exe)], input=request_bytes, capture_output=True,
                              timeout=_TIMEOUT_S)
        if proc.returncode != EXIT_RELEASED or proc.stdout != payload_path.read_bytes():
            failures.append("replay mismatch: adjudicator output differs from release.json")
    return {"ok": not failures, "generation": True, "failures": failures}
