# Human-review checklist — <STUDY_ID>

> Wave 8. The automated gates catch schema / QC / SDC / airlock failures; they do **not** replace a
> named human visually reviewing the request and the outputs. Record a decision (`pass` / `query` /
> `block`) at each pause point. A `query` or `block` **prevents final client release until resolved**
> (`pipeline.finalize_eligible` fails closed on a blocking/query checkpoint). Each decision is recorded
> in `human_review_checkpoints.jsonl` (one `HumanReviewCheckpoint` per line) and audited.

| # | Checkpoint (`checkpoint`) | What the reviewer visually confirms | Decision |
|---|---|---|---|
| 1 | `intake` | CPRA / build / source, requested turnaround, purpose; flag a missing phenotype / ICD-10 definition | ☐ pass ☐ query ☐ block |
| 2 | `pre_epi_handoff` | the handoff is pseudonymised + INTERNAL-only, with the correct ask + ETA | ☐ pass ☐ query ☐ block |
| 3 | `epi_return` | the returned aggregate, phenotype definition, code-set/version, caveats, and sign-off | ☐ pass ☐ query ☐ block |
| 4 | `pre_airlock` | the final client summary, SDC wording, caveats, and the export manifest | ☐ pass ☐ query ☐ block |
| 5 | `escalation` | raised whenever the variant is not identifiable, the count is too small, the source evidence is ambiguous, or governance status is uncertain | ☐ pass ☐ query ☐ block |

For each: **reviewer**, **timestamp**, **artefacts_checked**, **decision**, **notes**, and (if `query`
or `block`) a **follow_up_owner**. A blocked checkpoint must be cleared (re-reviewed to `pass`) before
`ofh-feasibility finalize-eligible` will release the final count.

Reviewer: ____________  Date: ____________  Overall: ☐ release  ☐ hold  ☐ escalate
