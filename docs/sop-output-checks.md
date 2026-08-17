# SOP — output checks (Safe Outputs, before airlock)

Disclosure-control sign-off is a **human gate**. The code enforces the invariants and fails closed,
but a person confirms the release before it leaves the TRE. Run this checklist on every request.

## Automated gates (must all be green)
- [ ] `uv run ruff check` + `uv run pytest` green (the governance invariants are tested).
- [ ] The **runtime Lean airlock** committed the generation (`airlock_pending/release.json` +
      `release.ready` present; the transaction fails closed otherwise). `release_candidate.json`
      is internal review evidence; `lake build` in CI proves the formal project has no proof holes.
- [ ] `ofh-feasibility audit verify` → `verify=OK`, `no_participant_data=OK`.

## Disclosure control (review the export)
- [ ] The client figure is the suppression token (`<min`) **or** a value rounded to `sdc_round_to`.
- [ ] No released subgroup/ancestry cell is below `sdc_min_cell`; if any is, the **whole breakdown is
      suppressed** (secondary suppression — a total beside a suppressed subgroup would leak by
      differencing).
- [ ] The export (`airlock_pending/release.json`) contains **no participant identifiers**, no
      pseudo-ids, no participant-level rows — aggregate only (`schema`, `status`, `policy`,
      `study_id`, `subject_id`, `total`, `breakdown`).
- [ ] `release.ready` exists beside the payload and `ofh-feasibility audit verify` reports
      `release_generation=OK` — this checks the receipt's payload/request digests against the
      artefacts AND replays the attested adjudicator over the retained request preimage
      (byte-for-byte). A payload without a verified receipt is NOT transferable.

## Least privilege (what stays internal)
- [ ] `internal_carrier_table.parquet` (participant IDs) and `handoff_to_epi.csv` (pseudonymised) are
      classified INTERNAL-TRE-ONLY and are NOT in the export set.
- [ ] `frequency_control_view.json` is INTERNAL-only; the airlock manifest blocks it from export.
- [ ] The airlock manifest marks **exactly one** `export_to_client=true` file, classified
      `AIRLOCK-EXPORT-CANDIDATE`, `human_readable=true`.

## Escalate (do not guess)
- [ ] Any uncertain classification, an unexpected count, a variant not in the resource, or a gate
      refusal → escalate for governance review. Fail closed; do not relax a threshold to force a pass.

## Sign-off
Reviewer: ____________  Date: ____________  Request: ____________  Decision: release / hold / refuse
