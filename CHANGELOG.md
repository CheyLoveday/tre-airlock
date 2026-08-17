# Changelog

All notable changes are documented here. Format: Keep a Changelog; versioning: SemVer.

## [Unreleased]

_Nothing yet._

## [0.1.0] - 2026-08-17

**First public release**: the complete TRE-airlock MVP — an executable Lean 4 adjudicator
formally controls the pre-egress release decision (platform-owned policy, value-closed release
language, committed generations, ledger-bound verification) with the genotype-feasibility
pipeline as the worked producer example. Everything below in this section was developed and
reviewed in the private development repository and ships publicly for the first time here.
### Fixed (TRE-airlock MVP — second-review blockers: policy authority, value closure, committed generations, single client surface, artefact verification)
- **Platform-owned policy Γ:** the trusted release policy now lives in the platform deployment
  record `platform/release_policy.json` (id + version + digest bound into every decision, receipt
  and audit record). The analysis config no longer supplies the policy the airlock judges under;
  a candidate whose declared SDC fields disagree with the authorised policy refuses before
  adjudication. `Policy.Valid` (Lean) and policy authorisation (platform) are distinct, and the
  mandatory adjudicator digest pin moved into the same platform record.
- **Value-closed release language (Lean):** breakdown labels are a finite inductive vocabulary,
  the subject is a parsed (multi-)CPRA reference, the study id is a charset/length-refined
  subtype, counts and list cardinalities are parser-capped — identifier-shaped or free-text
  content can no longer inhabit the released representation (adversarially tested with
  identifier-shaped values, control characters, over-cap payloads, and unknown labels).
- **Committed release generations:** all four egress sites run inside one
  `bridge.release_transaction` — O_EXCL attempt lock, prior-generation rotation, adjudication,
  uncommitted payload placement, internal artefacts + audit event, then the `release.ready`
  receipt as the LAST atomic commit step. Failure of the evidence write, directory fsync,
  internal outputs, or the audit append leaves NO committed generation; a payload without its
  receipt is not transferable and is rotated by the next attempt.
- **Single client surface:** release CLI commands print only the committed receipt (canonical
  path + payload/request/adjudicator digests + policy id); `--report` is gone from the release
  CLI; analyst narration moved to the explicitly-internal `notes` command; the commercial memo is
  relabelled an INTERNAL planning preview; `run_demo` banners mark all narration INTERNAL.
- **Artefact verification:** `ofh-feasibility audit verify` now verifies the ARTEFACTS, not just
  the ledger — receipt-vs-payload digest, retained request preimage digest, adjudicator
  availability/attestation, and byte-for-byte replay of the attested adjudicator. Replay wording
  is scoped to "while an executable matching the recorded digest is available".

### Fixed (TRE-airlock MVP blockers #54 / #55 / #56)
- **Trusted adjudicator binding (#54):** removed the environment override of the airlock
  executable; the adjudicator is one fixed platform-owned path (module constant), with the
  executable's SHA-256 attested on every adjudication and an optional deployment digest pin
  verified before invocation. Tests substitute only through a private seam; static guards reject
  environment/config/argument-based substitution, and a forged exit-0 executable can no longer
  reach the production release path.
- **Transactional publication (#55):** all four egress sites now use one release transaction
  (now `bridge.release_transaction`; `publish_release` is its no-caller-writes wrapper): the canonical `release.json` slot is attempt-scoped — a new attempt
  first rotates any prior payload into internal `release_history/` (keyed by digest), so refusal,
  timeout, crash, or a missing binary leaves the canonical path ABSENT; success publishes
  atomically (same-filesystem staged temp + fsync + `os.replace` + directory fsync). Single
  writer per results directory is a stated precondition. The `success → refusal` stale-payload
  defect is regression-tested in the same results directory, with failure injection.
- **Exact audit binding (#56):** `bridge.authorize` now returns an immutable `AirlockDecision`
  (exact request bytes, exact payload bytes, request/payload/executable SHA-256); audit records
  copy those digests directly — the post-hoc request reconstruction is removed — and the exact
  request preimage is retained under `airlock_evidence/`. Wording now distinguishes verification
  (digests) from replay (retained preimage), and the formal claim from the operational
  effect-binding TCB.

### Added (TRE-airlock MVP — runtime Lean release authority)
- The executable Lean 4 airlock (`formal/TreAirlock`) is now the RUNTIME release authority: every
  release path (single-variant orchestrate + staged report, final post-phenotype, batch) maps its
  aggregate candidate into a strict `tre-airlock/v1` request (`airlock.build_airlock_request` —
  policy never from the candidate; superseded detail: the second-review entry above moves the
  policy source from the analysis config to the platform record; malformed tokens, negative counts, duplicate
  labels, and suppressed-breakdown-with-cells fail fast), adjudicates via the new mechanical
  bridge (`bridge.authorize`), and stages ONLY the exact Lean-emitted bytes at
  `airlock_pending/release.json` — the sole releasable artefact. Lean refusal writes nothing.
- Python-rendered summaries are demoted to INTERNAL analyst notes (no client text is staged for
  egress); `authorize_release` / `release_ok` remain as the reference/preflight predicate and the
  differential-conformance target only, and now also reject duplicate labels and negative cells to
  mirror the Lean judgment exactly.
- Audit events record the adjudication decision's request/payload/executable digests (verification)
  and the retained request preimage path (replay); the staged payload's hash lands in
  `output_sha256`. (Superseded detail: see the #56 entry above — digests alone verify, the
  retained preimage is what enables byte-for-byte replay.)
- Evidence: bridge unit tests, a static no-alternate-writer guard, real-binary integration tests
  (the plan §13 bypass candidate is refused with no file), e2e byte-equality against a fresh
  adjudicator invocation, and a generated 160-case Python/Lean differential grid. Python CI now
  builds the Lean adjudicator (cached elan/lake) before running pytest.

### Changed (MVP close-down / share readiness)
- Split runnable example configs from request templates: executable YAML examples now live under
  `configs/examples/`, the demo variant catalogue lives under `configs/catalogs/`, and `templates/`
  is reserved for request payload templates.
- `docs/` is now the shareable-only documentation tree (internal planning and review notes live
  outside it), guarded by `tests/unit/test_docs_boundary.py`.
- Demo setup is now explicit without making first-run reviewers hit a missing-data failure:
  `data/synthetic/` ships as a small deterministic synthetic fixture, `make demo` is a pure run over
  shipped inputs, and `make gen` / `make fresh-demo` are deliberate refresh paths. `data/raw/`,
  `data/tmp/`, optional OFH-format generated stand-ins, and `results/` remain gitignored.

### Fixed (output derivation / release boundary)
- Gene and disease CLI defaults now derive study IDs and purpose text from the requested symbol or
  panel instead of leaking the original CHEK2 / breast-cancer demo scenario; a BRCA1 e2e regression
  guards against scenario-literal drift.
- Reporting now derives DR2 sensitivity labels from config thresholds, uses one named source for
  illustrative response-rate assumptions, and conditions the internal kinship note on the computed
  full-vs-unrelated allele-frequency delta.
- Output writing now authorizes the `ReleaseCandidate` before any client-shaped summary is written,
  airlock manifest criteria derive from file descriptors, and the unused `classify_genotypes` kernel
  path was removed.

### Fixed (boundary hardening)
- Config validation now rejects sub-minimum SDC floors, out-of-range quality thresholds, negative GQ,
  and inverted DR2 confidence tiers before a run can start.
- `BatchRequest` is now `extra="forbid"` and rejects empty variant tuples; single-variant request CSVs
  now fail unless they contain exactly one row.
- Variant catalogue loading now validates each variant's CPRA against its chrom/pos/ref/alt fields,
  in addition to the configured gene-span guard.
- README/design-decision wording now tags demo carrier counts as synthetic-cohort outputs, keeping them
  separate from published-list identifiability facts.

### Added (preflight tightening)
- Added requested-source availability to `variant_preflight.json`, recording whether the exact CPRA is
  present in the requested array and/or imputed resources before counts are interpreted.
- Added configured gene-span validation to the variant catalogue: catalogue-backed gene/panel requests
  now fail fast if a variant assigned to a gene falls outside that gene's configured GRCh38 span.

### Added (public data snapshot / intake)
- Added `docs/reference/ofh-public-data-snapshot.md`, a concise Release 14 public-data-estate snapshot
  with source links, known public-page count discrepancies, intake field groups, and a suggested
  upstream `FeasibilityIntake` Pydantic shape that compiles into the existing concrete request,
  epidemiology-return, and release models.
- Linked the snapshot from README, `docs/service.md`, and `docs/data-contracts.md` so the service
  framing now shows: public OFH data domains -> intake grammar -> Pydantic boundary models -> governed
  variant/gene/panel execution path.

### Added (Wave 10 — notebook companion)
- Added pure aggregate view builders (`views.py`), a notebook shell (`notebook.py`), and a rendered
  `notebooks/ofh_feasibility_walkthrough.ipynb` that calls the same governed pipeline and records
  notebook runs in the audit ledger with `actor_type="notebook"`.
- Added `docs/notebook-companion.md`, `notebook` / `notebook-render` Makefile targets, and the optional
  `notebook` extra for local JupyterLab + matplotlib use.

### Added (Wave 12 — audience outputs)
- Added neutral / research / commercial output skins over the same authorised release candidate,
  including research notes, commercial planning memos, data factsheets, recruitability funnels, and
  batch/gene/disease audience summaries.
- Added CLI `--audience neutral|research|commercial` for `run`, `batch`, `gene`, and `disease`.

### Added (Wave 15 — transparent grounded gates)
- Added per-gate boolean accounting (`qc.gate_accounting`) carried into staged QC and the internal
  carrier table; client summaries now surface configured quality cut-offs.
- Added SDC-safe DR2 sensitivity: the table is withheld if adjacent thresholds would expose a
  sub-minimum movement by differencing.
- Added a small public-list-derived variant-identifiability artifact plus provenance, wired through
  `variant_identifiability_path` so demo-variant `on_array` / `on_imputed` / annotation reliability are
  grounded before source resolution without shipping raw CPRA lists.
- Added `classify.project_cells` late-bound quality projection, so counts can be re-derived from
  retained evidence and raw QC columns when DR2/max-GP/call-rate/GQ thresholds move.

### Added (configuration polish)
- Added `configs/catalogs/demo_variant_catalog.yaml` plus catalogue-backed gene/panel resolution; `config.yaml`
  now exposes `variant_catalog_path`, and CLI `gene` / `disease` can override it with
  `--variant-catalog`.
- `batch`, `gene`, `disease`, and `finalize-eligible` now accept the same source-format override as
  `run`, and batch/gene/disease execution respects `source_format=ofh_tre`.
- Added three complete example configs under `configs/examples/` for the simplified single-variant
  demo, OFH-format CHEK2 I157T, and catalogue-backed gene/panel runs.
- `run_demo.py` now accepts `--config` and respects `request_path` from the loaded config.

### Changed (finishing pass — profiling / scale)
- Vectorised sample-flag string construction and changed carrier classification to build source/reason
  strings only for rows with carrier evidence.
- Vectorised the internal-only frequency-control AF bootstrap from 1,000 Python resample allocations to
  bounded seeded NumPy draw chunks, preserving the previous seeded loop result by regression test.
- Added `docs/reference/profile-summary.md` with warmed `pipeline.orchestrate()` cProfile evidence and
  bottleneck interpretation.
- Renamed canonical config keys from `imputed_info_*` to `imputed_dr2_*`; historical names remain
  load-compatible aliases.

### Fixed (presentation / docs)
- Added `docs/for-reviewers.md` and `docs/client-outputs.md`; linked the reviewer, notebook, and
  audience-output surfaces from README/docs index.
- Fixed the docs index orchestration link and updated the TRE package cross-check to describe numba as
  the array-direct reconciliation oracle.
- Added stakeholder-communication framing: one governed result can be explained differently to
  technical, product/service, governance, ethics, and scientific/epidemiology audiences without
  changing or widening the authorised answer.
- Reworked share-facing docs around positive service-scope language: feasibility determination, export
  boundary, internal-only artefacts, and labelled synthetic/public evidence.
- Codified the positive scope-language rule in the contributor docs so future documentation reviews
  avoid defensive "not X" framing.

### Fixed (Wave 14 — pre-share hardening)
- Missing/blank ancestry is now an explicit `UNKNOWN` ancestry stratum and ancestry SDC suppresses the
  whole breakdown if strata do not sum to the released total.
- The Numba carrier-count kernel now reconciles the same post-consent array-direct count as the
  readable classifier in both in-memory and staged workflow paths; docs now describe it as numeric
  reconciliation, not a freestanding hot path.
- Kinship stability uses semantic boolean coercion, so string `"FALSE"` is not treated as truthy.
- Array-absent indels now emit the imputation/targeted-assay caveat into the client summary.
- Disease-panel resolution deduplicates overlapping CPRAs while preserving panel order.

### Added (service framing)
- `docs/service.md` now states the wider feasibility request-family surface, intake grammar, and
  disposition model before narrowing to the recall-by-genotype MVP.

### Changed (handoff hygiene)
- Tightened the boundary between the shareable repository surface and local-only working
  material (ignore rules and documentation).

### Added (Wave 11 — CHEK2 / breast-cancer expanded cases)
- Synthetic CHEK2 and demo breast-cancer panel cases: c.1100delC as array-absent/low-DR2,
  I157T as array-direct with released SDC breakdowns, and a five-gene breast-cancer demo panel.
- Pure `resolve.py` gene/disease resolver plus `ofh-feasibility gene --symbol CHEK2` and
  `ofh-feasibility disease --panel breast_cancer`, both reducing to the existing governed batch/union
  path.
- Request-path overrides for CLI/Snakemake so expanded cases can run without hand-editing
  `variant_request.csv`; OFH-format pVCF/tabix stand-ins now support the expanded multi-contig cases.

### Fixed (setup / handoff readiness)
- `numba` moved into runtime dependencies because the pipeline imports the kernel module on every run;
  `uv sync` now installs the hard-required runtime by default.
- `docs/service.md` no longer points `finalize-eligible` at a non-generated checkpoint ledger; it now
  says to pass `--checkpoints` only when a real signed JSONL ledger exists.

### Added (Wave 8 — epidemiology return loop)
- Aggregate-only **epidemiology return loop**: `EpiReturn`, `FinalResult`,
  `HumanReviewCheckpoint`, and `EpiNotification` models; `epi.validate_epi_return`
  fail-closes on study/CPRA/run mismatch, unsigned returns, missing phenotype/ICD-10 metadata,
  eligible counts above the genotype ceiling, or forbidden identifiers.
- `ofh-feasibility finalize-eligible`: reruns the genotype ceiling, accepts the signed epi aggregate,
  applies SDC to the post-phenotype eligible count, and sends the final summary through the same
  release-gate / airlock path as the genotype summary.
- Human review and colleague-communication artefacts: rapid-turnaround notification, epi return
  template, human-review checklist, output-review checklist final section, and service-doc flow that
  distinguishes the genotype ceiling from the final post-phenotype count.

### Fixed (final sign-off sweep)
- Bound `EpiReturn.run_id` to the genotype run's provenance in the orchestrated workflow, so an epi
  return copied from one handoff cannot be silently reused against different inputs/config for the
  same study and CPRA.
- Final airlock manifest notes now name the actual export candidate
  (`final_feasibility_summary.txt`) instead of hard-coding the preliminary genotype summary.
- Historical internal review notes now point readers to current docs before treating old findings as
  still open.
- Batch / multi-variant release now exposes only the SDC-controlled union total by default and stages a
  batch airlock manifest; per-variant and overlap counts are kept internal to avoid differencing leaks.
- Sample-QC joins and unknown sex-check/kinship flags now fail closed instead of silently treating
  missing rows or unparseable values as clean.
- Epi-return aggregate free text now rejects bare identifier-shaped values, while audit hash metadata is
  excluded from that free-text scan to avoid false positives.
- Public BAG3 CPRA verification is reconciled: Release 14 array CPRA list contains
  `10:119669928:C:G` (`Inaccurate Call=No`); the public imputed CPRA list does not contain the exact
  CPRA. Runtime source resolution now treats BAG3 as exact-CPRA present in the array resource and
  absent from the imputed resource; any dummy imputed rows in synthetic fixtures are branch-coverage
  scaffolding, not evidence.

### Added (Wave 9 draft — OFH-format stand-ins)
- Draft faithful-format OFH genetic-file adapter work: a generator for real-named synthetic pVCF /
  sample-QC stand-ins, parsers that map those files back into the existing core schemas, and
  round-trip tests proving the governed result matches the simplified synthetic inputs. The `run` CLI
  can use `--source-format ofh_tre`; generic multi-region resolution remains planned work.

### Added (Wave 5 — formal release gate)
- A **release gate** that makes the airlock export unconstructable without a passing decision: a `ReleaseCandidate` model (aggregate-only — `extra="forbid"` makes a participant-level field structurally impossible), a pure `airlock.release_ok` enforcing the disclosure-control predicates (minimum cell, secondary suppression / no differencing, rounding, least privilege), and `authorize_release` as the **sole, fail-closed path** — the pipeline calls it before staging the export, so a non-compliant summary is never written. (D31, allowlist-clean.)
- **Lean 4 proof** of the same gate (`formal/`): `ReleaseOK` as a decidable proposition, a proof-carrying `AirlockExport` (unconstructable without a `ReleaseOK` witness), machine-checked invariant theorems, and a checker executable. A **conformance test** (`tests/conformance/`) asserts the Python verdict equals the Lean verdict across a battery; a dedicated **Lean CI job** (`lean.yml`) runs `lake build` + conformance. Lean is **CI-only** — never a TRE runtime dependency, never allowlisted; the Python `ruff`/`pytest` job stays pure-Python. The negative test (a sub-min-cell export) demonstrably **fails to compile**. (D32.)

### Changed
- Renamed the manifest imputation-quality field `imputed_info_score` → **`dosage_r2`** and reframed the client note to "dosage r2 (DR2)" — OFH uses dosage-r² (DR2), not a traditional INFO score (the variant summary VCF carries DR2; threshold DR2 ≥ 0.3 at AF > 1%). Config thresholds keep the `imputed_info_*` names but threshold DR2 (a documented choice; see `docs/reference/missing-data.md`).

### Added (Wave 6 — auditability)
- Operational **SOP / governance doc stack**: `docs/feasibility-definition.md`, `docs/sop-feasibility-analysis.md`, `docs/sop-output-checks.md`, `docs/data-contracts.md`; stakeholder templates (`docs/templates/` — feasibility note, epi handoff sheet, output-review checklist); and the build flow docs `docs/playbook.md` and `docs/SOP_DEV_FLOW.md`. Internal engineering controls under OFH governance, not OFH policy.
- The file-staged (Snakemake) path now emits a **per-stage audit event** chained into the Merkle ledger (extract → qc → classify → report → airlock), so a DAG run's whole chain is verifiable (`ofh-feasibility audit verify`). The staged `report` stage also runs the Wave 5 **release gate** (fail-closed), closing that path. `config.yaml` documents `sdc_min_cell` as a comparator (UK Biobank floor 5 vs the repo's deliberate 10), not OFH-confirmed.
- Tamper-evident **Merkle evidence ledger** (`audit.py`, stdlib only — `hashlib`+`json`, allowlist-clean): canonical event serialisation, leaf/`merkle_root` with domain separation, `verify_ledger`, and an append-only `consistency_ok` proof. Every `orchestrate` run appends a canonical event (request id, timestamp, git commit, config + input + output hashes, SDC decision) — **hashes + metadata only, never participant data** — and writes `audit_root.txt`. `ofh-feasibility audit verify` recomputes the root and checks for participant-data leakage, failing closed. Detects modification, reordering, and truncation (tested). (D30; EU AI Act Art. 12 framing, no overclaim.)

### Added (Wave 4 — service)
- `ofh-feasibility` **CLI** (argparse/stdlib — allowlist-clean): `run` (single variant) and `batch` (composite profile), with `--template` (a `templates/` catalogue: `single_variant.json`, `composite_profile.csv` — a new request type is a dropped-in template, not a code change) and `--report`. Console entry point in `pyproject`.
- `reporting.render_markdown_report`: the client feasibility note as a tidy SDC-applied Markdown report.
- Release workflow (`.github/workflows/release.yml`) that fires on a `v`-tag push — re-runs the gates, builds the package, publishes a GitHub release. Dormant until a tag is pushed.
- `docs/service.md`: the service contract — turnaround, what the client does/does not receive, standard caveats, how to run.

### Added (Wave 3 — TRE realism)
- Internal **variant-frequency control view** (`reporting.build_frequency_control`): per-stratum (overall / sex / ancestry) alt-allele frequency with a **Wilson 95% interval** (numpy, no new dep) over honest denominators (callable typed alleles), a typed-vs-imputed discordance cross-check, and a **kinship-cluster stability** check (full vs unrelated-only AF + a seeded bootstrap 95% interval). A **ploidy guard** skips diploid AF off the autosomes. Classified **INTERNAL-TRE-ONLY** (airlock blocks it from export) with its own min-cell discipline — sub-min strata are suppressed even internally.
- Nextflow/WDL **port skeleton** (`workflow/nextflow/main.nf` + `docs/reference/orchestration_port.md`): the DAG is the contract, so swapping Snakemake for Nextflow/WDL (the DNAnexus-supported languages) doesn't touch the stage logic. A `pipeline.STAGES` dispatch table + `scripts/run_stage.py` give every orchestrator one entrypoint into the same core. Documentation skeleton — not a claim OFH runs it.
- Batch / multi-variant (composite risk-profile) requests: `BatchRequest` + `io.read_batch_request`; `pipeline.orchestrate_batch` runs each variant over the same inputs and `combine_feasibility` unions the carriers (participants carrying ≥1 variant). The client note releases the SDC-controlled union total; per-variant and overlap counts are internal unless a future safe-breakdown route is approved. The generator emits a 2nd variant + `batch_request.csv` (additive; the BAG3 single-variant outputs are untouched).
- Ancestry stratification with **per-group SDC**: included carriers counted per `ancestry_stub`; `sdc.apply_sdc_strata` applies secondary suppression across the strata (a single small group withholds the whole breakdown, since the released total would otherwise expose it); the client note gains an ancestry section (`FeasibilityResult.ancestry_breakdown`). The internal table now carries `sex` + `ancestry_stub` (ancestry stays internal — never in the handoff or as an exact small cell).
- `io.GenotypeSource` interface with `CsvGenotypeSource` (long-form Parquet) and `VcfBgenShapedGenotypeSource` (VCF GT + BGEN genotype-probability fixtures) implementations: the same downstream stages run over either on-disk shape (the DAG is the contract). The generator now also emits `array_calls_vcf.tsv` + `imputed_calls_bgen.tsv`; `orchestrate` accepts an optional `genotype_source`.

### Added (Wave 2 — hardening)
- Thin **Snakemake** workflow (`workflow/Snakefile`): one rule per stage over the same core; `snakemake --cores 1` reproduces the run, re-runs are no-ops, and the DAG renders to `docs/reference/dag.png` (also a mermaid diagram in the README). Snakemake is a **local-only** `workflow` extra — not allowlisted, never runs in the TRE (D26).
- File-staged `stage_*` orchestrators in `pipeline.py` (extract → qc → classify → report → airlock) over the same pure core, each emitting one structured log line per stage (row counts); the file-staged path reproduces the in-memory run byte-for-byte (integration test).
- `provenance.json` written every run: config + SHA-256 of each input + package versions (reproducibility evidence); the config/input hashes are deterministic for the same inputs.
- Generic `io.read_parquet` / `io.read_json` for staged intermediates.

### Changed (governance hardening, from the Wave 1 adversarial review — D24)
- Consent gate is now a hard control: `require_consent` is validated to be `true` and `qc.consent_mask` is unconditional (the `require_consent=false` bypass is removed); withdrawn carriers can no longer be configured into counts/handoff.
- SDC cannot release a sub-min cell: `Config` requires `sdc_min_cell % sdc_round_to == 0`, and `apply_sdc` suppresses cells whose raw *or* rounded value is below the minimum.
- Airlock ties export to classification: the single export must be classified `AIRLOCK-EXPORT-CANDIDATE`.

### Changed (metadata)
- Synthetic dictionaries now mirror the real OFH `v14` column shape (D23): data dictionary uses `entity, name, type, primary_key_type, coding_name, title, units, description`; codings use `coding_name, code, meaning, display_order, parent_code` with the OFH special-value codes (`-999 Suppressed`, `-1/-3`); a `genetic_data` entity is added. (`docs/reference/missing-data.md` §4.)

### Fixed (correctness, from the Wave 1 adversarial review — D25)
- `pipeline` fails fast if `request.carrier_definition` diverges from the config's (the count and the client note can no longer silently disagree).
- `het_only` is honoured on the imputed-dosage path (hom-alt-range dosages excluded; proper zygosity needs genotype probabilities the mock doesn't carry — noted in `docs/reference/missing-data.md`).
- A missing array genotype (`gt_code == -1`) is recorded in the internal-table `reason` even when the carrier is rescued by imputed evidence (previously an unreachable branch).
- `qc.sample_flag_series` coerces flag columns to bool by meaning, so a sex-check fail stored as the string `"FALSE"` is no longer mis-read as a pass.

## [0.1.0-dev.1] - 2026-06-09

_Internal Wave 1 milestone in the private development repository (its local `v0.1.0` tag);
superseded by the public 0.1.0 above._
The Wave 1 MVP: the OFH-shaped genotype-feasibility vertical slice, runnable end-to-end on
synthetic data with the governance invariants tested.

### Added
- **Vertical slice** (`run_demo.py` → `pipeline.orchestrate` over a pure functional core):
  - `io` readers/writers (the filesystem boundary; schema-validated inputs).
  - `extract` — variant validation (the *identifiable* check), source decision, dataset-slice pivot.
  - `qc` — pure per-row masks (array call-rate/GQ/missingness, imputed DR2 floor + max_gp, consent gate, sample flags).
  - `kernels` — Numba `@njit` carrier-count reconciliation with pure-NumPy references.
  - `classify` — consent gate, evidence combination, confidence (high|conditional), decisions + reasons.
  - `sdc` — suppression + **secondary suppression** + rounding.
  - `reporting` — least-privilege output tiers + the decision-ready, SDC-applied client note (go/no-go/with-caveats).
  - `airlock` — transfer manifest enforcing exactly one human-readable export candidate.
- Governance tests: consent exclusion, SDC invariants (property-tested), kernel-vs-reference, single airlock export; full unit + integration + e2e pyramid (70 tests).
- Wave 0 foundations: project scaffold, dictionary-driven synthetic data generator, typed config and models (pydantic), test/profiling structure, dependency policy, and the internal rulebooks.
- `variant_manifest.csv` in the synthetic generator: variant availability + imputation DR2 / AF
  stand-ins (the OFH variant summary-statistics input; D21).
- `docs/reference/BAG3_VERIFICATION.md` and `docs/reference/missing-data.md`: honest record of real CPRA-list status
  and synthetic gaps (D22, D23).

### Changed
- Default data location is now `data/synthetic/` (config `data_dir` and the generator `--out`), separating generated mock data from `data/raw/` reference material.
