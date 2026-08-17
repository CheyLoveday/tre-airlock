# Output review checklist — <STUDY_ID>

> Governance / Safe-Outputs sign-off, completed before any airlock release. Short form of
> `docs/sop-output-checks.md`.

| # | Check | Pass |
|---|---|---|
| 1 | `ruff` + `pytest` green; release gate authorized (`release_candidate.json` present) | ☐ |
| 2 | `ofh-feasibility audit verify` → verify=OK, no_participant_data=OK | ☐ |
| 3 | Client figure is `<min` or a multiple of `sdc_round_to` | ☐ |
| 4 | No released cell below `sdc_min_cell`; small subgroup ⇒ whole breakdown suppressed (secondary) | ☐ |
| 5 | Export contains no participant IDs / pseudo-ids / participant rows (aggregate only) | ☐ |
| 6 | Internal table + epi handoff + frequency control are INTERNAL-TRE-ONLY, not exported | ☐ |
| 7 | Airlock manifest: exactly one `export_to_client=true`, `AIRLOCK-EXPORT-CANDIDATE`, human-readable | ☐ |
| 8 | Variant identifiable in the resource; QC thresholds met; no unexplained count | ☐ |
| 9 | Caveats stated (genotype-only, conditional imputed, estimate-not-list) | ☐ |

## Final post-phenotype release (Wave 8 — when an epi return has come back)
| # | Check | Pass |
|---|---|---|
| 10 | `final_release_candidate.json` present (the final count was authorized through the same gate) | ☐ |
| 11 | `final_feasibility_summary.txt` clearly labels the genotype count as the **ceiling** and the epi-returned count as the **post-phenotype eligible** figure | ☐ |
| 12 | `eligible_count` ≤ the genotype ceiling, and matches the run's `study_id` / `cpra` | ☐ |
| 13 | `final_airlock_manifest.json`: exactly one export = `release.json` (exact Lean-emitted bytes); both analyst summaries are INTERNAL-only | ☐ |
| 14 | Human-review checkpoints (`intake`, `pre_epi_handoff`, `epi_return`, `pre_airlock`) are recorded and not `block`/`query` | ☐ |

**Decision:** ☐ release  ☐ hold  ☐ refuse (escalate)

Reviewer: ____________  Date: ____________  Notes: ____________
