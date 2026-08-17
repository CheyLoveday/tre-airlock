# Runtime Lean airlock

The **formal runtime core** of the TRE-airlock MVP — and the release authority
on the pipeline's actual egress path: `ofh_feasibility.bridge.authorize` invokes
this executable, and the exact stdout bytes are the ONLY content ever written to
`results/airlock_pending/release.json` (the sole releasable artefact). Refusal
returns no bytes and stages nothing. There is no Python fallback.

The existing `releasecheck` binary remains the Wave-5 CI precursor; the Python
`release_ok` predicate remains as reference/preflight and a differential-
conformance target. Neither carries release authority.

## Build

```bash
cd formal && lake build          # precursor + airlock
./.lake/build/bin/airlock        # reads one JSON request on stdin
```

## Request (stdin)

One JSON object. Unknown fields, missing fields, and unknown schemas are refused.

```json
{
  "schema": "tre-airlock/v1",
  "policy": { "min_cell": 10, "round_to": 5 },
  "candidate": {
    "study_id": "demo",
    "subject_id": "10:119669928:C:G",
    "total": { "tag": "shown", "n": 70 },
    "breakdown": { "tag": "suppressed" }
  }
}
```

`total` / `breakdown` tags: `suppressed` or `shown`. Shown breakdowns carry
`cells: [{ "label", "count" }]`. Counts are natural numbers (negatives are
malformed). Policy is **not** a field of the candidate.

## Success (stdout)

Exit `0`. Compact JSON, fixed key order, one trailing newline. Example:

```json
{"schema":"tre-airlock/v1","status":"released","policy":{"min_cell":10,"round_to":5},"study_id":"demo","subject_id":"10:119669928:C:G","total":"~70","breakdown":null}
```

Display tokens (`<k`, `~N`) are created by the renderer from `Γ`.

## Refusal

Empty stdout. Reason on stderr. Non-zero exit:

| Code | Meaning |
|---:|---|
| 1 | candidate rejected (`ReleaseOK` false) |
| 2 | malformed input |
| 3 | invalid policy (`Policy.Valid` false) |

## Modules

| File | Role |
|---|---|
| `TreAirlock/Policy.lean` | `Policy`, `Policy.Valid` |
| `TreAirlock/Candidate.lean` | structural total / breakdown |
| `TreAirlock/Judgment.lean` | `ReleaseOK Γ c`, `AirlockExport`, theorems |
| `TreAirlock/Authorize.lean` | proof-bearing `authorize` |
| `TreAirlock/Parse.lean` | strict JSON decoder |
| `TreAirlock/Render.lean` | canonical bytes |
| `TreAirlockMain.lean` | CLI |

## Effect binding (Steps B / C — implemented)

- `src/ofh_feasibility/bridge.py` invokes this executable and captures one
  immutable `AirlockDecision` per success: exact request bytes, exact payload
  bytes, and SHA-256 digests of request, payload, and the executable invoked.
  Every non-zero exit raises `AirlockRefusal` with no payload bytes.
- All four release paths (single-variant orchestrate + staged report, final
  post-phenotype, batch) run inside `bridge.release_transaction` — the single
  release transaction: rotate the prior generation out of the canonical slot →
  adjudicate → place the payload + evidence → internal artefacts + audit event
  → commit `release.ready` atomically last. Python `authorize_release` is
  preflight/reference only.
- Evidence: `tests/unit/test_bridge.py`, `tests/unit/test_no_alternate_release_writer.py`
  (static bypass + substitution guards), `tests/integration/test_lean_bridge.py`
  (plan §13 bypass refused; success→refusal→success transaction; failure
  injection), `tests/e2e/test_release_payload.py` (byte-for-byte equality;
  audit-digest binding; refusal stages nothing),
  `tests/conformance/test_generated_differential.py` (generated agreement grid).

## Platform trust root (TCB)

BOTH authority inputs are platform-owned deployment records, deliberately NOT
configurable by analysts:

- **Policy Γ** comes from `platform/release_policy.json` (id, version, digest
  bound into every decision, receipt, and audit record). The analysis config
  cannot supply it; a candidate whose declared SDC fields disagree with the
  authorised policy refuses before adjudication. `Policy.Valid` (checked by
  Lean) and policy AUTHORISATION (platform ownership) are separate conditions.
- **The adjudicator** is a fixed constant in `bridge.py` (in a deployed TRE, a
  platform-managed read-only absolute path), never read from the environment,
  the analysis config, or the candidate. Every adjudication records the
  SHA-256 of the executable actually invoked; the policy record's
  `adjudicator_sha256` field is the mandatory production trust anchor —
  when set, a mismatch refuses before invocation. It is null in this repo
  only because the binary is built per-host.

Lean formally guarantees payload construction from a proof-indexed
`AirlockExport` over a value-closed release language (finite label
vocabulary, parsed CPRA subject, charset-capped study reference, bounded
counts — free text cannot inhabit the released representation). The bridge,
publisher, bindings, and filesystem are the operational half — disciplined
and tested Python, attested by digest, not proved in Lean. In-process Python
has no memory isolation: analyst code running in the SAME interpreter could
monkeypatch any of it, so production deployments must run adjudication and
publication as a separate platform-owned process (read-only executable,
pinned digest, no test seams, narrowly permissioned filesystem).

## Committed generations, replay, and verification

- The canonical path `airlock_pending/release.json` is the slot for the
  CURRENT attempt: any new attempt first rotates a prior payload into
  `release_history/` (keyed by content digest) and clears stale receipts and
  manifests. Refusal, timeout, crash, or a missing binary leaves the slot
  absent — never a stale or partial file.
- A generation is COMMITTED only when its `release.ready` receipt (payload +
  request + adjudicator + policy digests) lands — atomically, LAST, after the
  internal artefacts and the audit event. A payload without its receipt is
  NOT transferable: `verify_release_generation` fails it, transfer consumers
  must check it, and the next attempt rotates it away. Failure of the
  evidence write, directory fsync, internal outputs, or the audit append
  therefore leaves no committed generation.
- The single-writer rule is ENFORCED by an O_EXCL attempt lock
  (`.release_attempt.lock` in the results directory) held per transaction; a
  hard crash leaves it in place deliberately, for operator review.
- The exact request bytes are retained under `airlock_evidence/` (a closed
  aggregate + policy — no participant data), keyed by digest. Re-running the
  attested adjudicator over that preimage and comparing output bytes is
  **replay** — available only while an executable matching the recorded
  digest is available; comparing recorded digests against retained artefacts
  is **verification**. The ledger's digests alone support verification only.
- `ofh-feasibility audit verify` checks the ledger (Merkle root + PII scan)
  AND the committed generation: receipt-vs-payload digest, retained preimage
  digest, adjudicator attestation, and byte-for-byte replay.
