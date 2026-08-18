# Platform-owned deployment records (TCB)

This directory is the PLATFORM's, not the analyst's. In a deployed TRE these records live on a
read-only, platform-administered path outside analyst control; in this repo they are the
committed stand-in for that deployment surface.

- `release_policy.json` — the **trusted release policy Γ** (`tre-airlock-policy/v1`). The bridge
  loads Γ from here; the analysis pipeline, its config, and the candidate cannot select or alter
  the policy under which a release is judged. `Policy.Valid` (internal coherence, checked by
  Lean) and policy **authorisation** (this file being the platform's) are distinct conditions.
  - `adjudicator_sha256`: trust anchor for the Lean adjudicator executable. When non-null,
    the bridge refuses to invoke an executable whose SHA-256 differs — before invocation. It is
    null in this repo because the binary is built per-host by `lake build`. **Null means the
    executable is path-bound and MEASURED (its digest recorded), not cryptographically
    AUTHENTICATED.** A production deployment MUST build the executable, hash it, generate this
    record with that exact digest, ship both together, and treat a null pin as a configuration
    error.

Changing this file is a platform governance action: it changes which releases are possible for
every run. The bridge binds the policy's id, version, and file digest into every adjudication
decision and audit record, so any change is attributable.
