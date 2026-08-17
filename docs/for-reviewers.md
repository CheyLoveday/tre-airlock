# For Reviewers

This repo is a synthetic, governed **recall-by-genotype feasibility service**. It shows how a
feasibility request — variant, gene, or disease-panel — is translated into tested code with explicit
assumptions, caveats, and governance gates.

## Five-minute path

1. Read the service framing in [`service.md`](service.md): what the client asks, what OFH-like
   feasibility means, and which artefacts are exportable versus internal-only.
2. Run the golden path:

   ```bash
   uv sync --extra dev
   make airlock                        # build the Lean adjudicator (release authority)
   uv run python scripts/generate_synthetic.py
   uv run ofh-feasibility run          # prints the committed release receipt
   uv run ofh-feasibility notes        # INTERNAL analyst note (diagnostics)
   uv run ofh-feasibility audit verify
   ```

3. Inspect the code path, module by module:
   - `src/ofh_feasibility/extract.py` - CPRA/build/ref-alt validation, source decisions, join guards.
   - `src/ofh_feasibility/qc.py` and `classify.py` - QC masks, consent gate, carrier classification,
     and reason codes.
   - `src/ofh_feasibility/sdc.py`, `airlock.py`, and `audit.py` - disclosure control, fail-closed
     release gate, and tamper-evident metadata ledger.
   - `src/ofh_feasibility/pipeline.py` - the imperative shell used by CLI, notebook, and Snakemake.
   - `src/ofh_feasibility/views.py` and `notebook.py` - aggregate-only reviewer/notebook surfaces over
     the same governed bundle.
   - `tests/` - unit, integration, e2e, conformance, and governance-negative tests.
4. Run an expanded case:

   ```bash
   uv run ofh-feasibility run --request data/synthetic/requests/chek2_i157t.csv \
     --results-dir results/chek2_i157t
   uv run ofh-feasibility disease --panel breast_cancer --results-dir results/breast_cancer
   ```

5. Read [`design-decisions.md`](design-decisions.md) for the *why* behind the choices — proportionality,
   governance-by-construction, CI focused on critical guarantees, and a deliberately lean build for an
   early, changing resource like OFH.

## What the client receives

The client-facing output is the committed release generation in `airlock_pending/`:
`release.json` (exact Lean-adjudicated bytes) plus its `release.ready` receipt. Participant IDs,
pseudonymised handoff tables, genotype rows, frequency-control views, and every Python-rendered
summary remain INTERNAL. `--audience neutral|research|commercial` shapes the INTERNAL analyst
note only (view with `ofh-feasibility notes`); no audience skin is a client deliverable.
The underlying result is the same for every audience; only the explanation changes. Technical readers
see derivation and failure modes, product readers see the decision and next step, governance readers
see disclosure boundaries and auditability, and ethics readers see how participant protection is
enforced in the workflow.

## What to look for

- Consent is fail-closed: withdrawn participants never enter a recontact set.
- Source decisions are explicit: array-direct evidence is preferred; imputed evidence is conditional
  and labelled with DR2 caveats.
- Identifiability is grounded in the public Release 14 CPRA lists: the runtime overlays the public-list
  membership fact (e.g. BAG3 array-present, imputed-absent) before source resolution, so the verdict
  follows the real lists even where synthetic fixture rows exist for branch coverage.
- Statistical disclosure control (SDC) uses minimum cell size, rounding, and secondary suppression.
  Subgroups are withheld when they could expose small cells by differencing.
- The Snakemake DAG and CLI call the same functional core.
- The audit ledger records hashes and governance metadata only.

## Known limits

- All participant data are synthetic.
- The OFH-format path is a local stand-in for public file shapes and keeps private TRE implementation
  details separate from the demo.
- The epidemiology step is represented by an aggregate signed return; linked-health phenotyping is
  outside this repo.
- The generic multi-region BGEN/pVCF adapter remains planned work.
