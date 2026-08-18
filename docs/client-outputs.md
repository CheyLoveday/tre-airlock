# Client Outputs

The pipeline produces one governed client-facing export per run. Everything else is internal support
for reproducibility, epidemiology handoff, or output review.

## Export path

1. The pure core builds exact internal counts.
2. `sdc.py` applies minimum cell size, rounding, and secondary suppression.
3. `airlock.py` builds an aggregate-only `ReleaseCandidate` and maps it into a strict
   `tre-airlock/v2` request under the **platform-owned trusted policy**
   (`platform/release_policy.json` — never the analysis config, never the candidate; a
   disagreement refuses before adjudication).
4. `bridge.py` invokes the **runtime Lean 4 airlock** (`formal/TreAirlock`) — a digest-attested,
   platform-bound executable — over a value-closed release language (finite label vocabulary,
   parsed CPRA subject, bounded counts — no free-form string field; study identity stays in
   internal evidence): only a proof-bearing
   success branch constructs an `AirlockExport` and renders the canonical payload.
5. The release transaction places the **exact Lean-emitted bytes** at
   `results/airlock_pending/release.json` and commits the generation with a `release.ready`
   receipt (payload/request/adjudicator/policy digests) written LAST. A payload without its
   receipt is NOT transferable; `ofh-feasibility audit verify` checks the receipt, the retained
   request preimage, and replays the attested adjudicator.

For every flow (single-variant, gene/disease/batch, final post-phenotype) the export file is
`release.json`. The human-readable analyst summaries (`feasibility_summary.txt`,
`batch_feasibility_summary.txt`, `final_feasibility_summary.txt`) are INTERNAL notes: no
Python-rendered client text is staged for egress.

## Audience skins

The same governed release can be rendered three ways:

```bash
uv run ofh-feasibility run --audience neutral
uv run ofh-feasibility run --audience research
uv run ofh-feasibility run --audience commercial
```

- `neutral` is the default feasibility summary.
- `research` foregrounds method, evidence tiers, and caveats.
- `commercial` foregrounds the decision signal and safe recruitability planning assumptions.

These are skins over the same release candidate. Participant IDs, pseudonymised IDs, raw genotype rows,
and extra subgroup counts stay internal. Derived planning estimates are suppressed whenever a
percentage calculation would create a sub-minimum number.

The communication principle is "same result, different abstraction layer":

- Technical reviewers need derivation, failure modes, and reproducibility evidence.
- Product and service owners need the decision, caveats, and next operational step.
- Governance reviewers need disclosure boundaries, release controls, and auditability.
- Ethics reviewers need to see where participant protection is enforced in execution.
- Scientific and epidemiology reviewers need the distinction between genotype ceiling and downstream
  phenotype eligibility.

The implementation keeps that principle honest by rendering different explanations from the same
authorised aggregate result, with one disclosure boundary for every audience.

Each single-variant summary also surfaces the configured quality cut-offs (array call-rate, GQ,
imputed DR2, max GP, dosage threshold). DR2 sensitivity is SDC-applied and is withheld if adjacent
thresholds would reveal a sub-minimum movement by differencing.

## Internal-only artefacts

- `internal_carrier_table.parquet`: participant-level provenance and reason codes.
- `handoff_to_epi.csv`: pseudonymised included-carrier handoff for phenotype review.
- `frequency_control_view.json`: internal QC/frequency credibility checks.
- `release_candidate.json`: aggregate evidence for output review.
- `audit_ledger.jsonl`: hashes and governance metadata only.

The airlock manifest marks only the Lean-rendered `release.json` as `export_to_client`;
every Python-rendered artefact, including the analyst summaries, is INTERNAL-TRE-ONLY.
