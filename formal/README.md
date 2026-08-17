# Formal release-boundary gate (Wave 5) — Lean 4

> **Two Lean components live here.** `TreAirlock/` + the `airlock` executable are the RUNTIME release authority — every release is adjudicated by that binary on the actual pre-egress path (protocol: [`AIRLOCK_RUNTIME.md`](AIRLOCK_RUNTIME.md)); there is no Python fallback. `Release.lean` + the `releasecheck` executable below are the retained Wave-5 CI precursor, kept as the differential-conformance target for the Python reference predicate.

A decidable type calculus at the release boundary: the terminal `AirlockExport` is **unconstructable
without a machine-checked proof** that every disclosure-control requirement holds, so a non-compliant
release does not get rejected at runtime — it **fails to compile** when one attempts to construct such
a static Lean value. The executable checker below evaluates the same decidable proposition for dynamic
candidates. "Does the proof term exist?" is the formal gate.

## Layout
- `Release.lean` — the calculus: the aggregate-only `ReleaseCandidate`, `ReleaseOK : Prop` (+ a
  `Decidable` instance), the proof-carrying `AirlockExport` (its constructor demands a `ReleaseOK`
  witness), and the machine-checked invariant theorems (minimum cell, secondary suppression,
  rounding, no sub-minimum cell). Deleting or weakening a conjunct of `ReleaseOK` breaks these
  proofs and `lake build` goes red.
- `Main.lean` — the checker executable (`releasecheck`): reads release candidates on stdin and emits
  the `ReleaseOK` decision per line. Used by the current conformance tests.

```bash
cd formal && lake build                 # proves the invariants; builds the checker
echo '10|5|~40|false|25,5' | ./.lake/build/bin/releasecheck   # -> false (sub-min cell)
```

## Current bridge to running code
- `Release.lean` proves the gate algebra in CI (`.github/workflows/lean.yml`).
- Current Python (`airlock.release_ok` / `authorize_release`) enforces the same predicates in the
  existing feasibility pipeline.
- `tests/conformance/test_lean_conformance.py` runs both checkers over a battery and asserts the
  Python verdict equals the Lean verdict, failing CI on divergence within that battery.

That precursor is retained as conformance evidence only. The completed system is the runtime
boundary below.

## The runtime bridge — implemented

Release authority is the executable Lean boundary, live on every egress path:

```text
ReleaseCandidate + trusted Policy Γ (platform record)
              ↓
       Lean runtime authorize
              ↓
    proof-indexed AirlockExport
              ↓
       Lean canonical render
              ↓
        exact output bytes
              ↓
   committed generation: release.json + release.ready
```

`lake build` produces `./.lake/build/bin/airlock` — the strict JSON runtime adjudicator
(`TreAirlock/`). Protocol, exit codes, TCB, and verification semantics:
[`AIRLOCK_RUNTIME.md`](AIRLOCK_RUNTIME.md). The Python bridge
(`src/ofh_feasibility/bridge.py`) invokes it inside one release transaction per attempt and
writes only its exact emitted bytes; there is no Python fallback. Runtime contract tests:
`tests/conformance/test_airlock_runtime_cli.py`; effect binding:
`tests/integration/test_lean_bridge.py` and `tests/e2e/test_release_payload.py`.

## Boundaries
- The formal gate certifies the closed released **object** against the stated policy; it does not prove
  that the upstream scientific count is correct.
- The first MVP does not formalise arbitrary notebooks, plots, models, cross-request differencing, or
  the upstream `apply_sdc` transformation.
- Human governance criteria remain separate assurance objects.

## Negative construction example
`Release.lean` carries a commented `badExport` that tries to build an `AirlockExport` from a
sub-minimum-cell candidate; uncommenting it makes `lake build` fail because the required `ReleaseOK`
proof cannot be discharged.
