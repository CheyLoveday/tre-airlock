# Notebook Companion

The notebook companion is a review surface over the same governed pipeline. It is not a separate
analysis path. `ofh_feasibility.notebook.run()` loads the config and request, calls
`pipeline.orchestrate(..., actor_type="notebook")`, writes the same artefacts, and returns the same
bundle the CLI uses.

## Run

```bash
uv sync --extra dev --extra notebook
uv run python scripts/generate_synthetic.py
make notebook
```

The notebook lives at [`../notebooks/ofh_feasibility_walkthrough.ipynb`](../notebooks/ofh_feasibility_walkthrough.ipynb).
Use `make notebook-render` to re-execute the committed notebook in place.

## What it shows

- candidate to client-count funnel
- source decisions and evidence tiers
- aggregate QC/classification breakdowns
- aggregate pass counts for each configured gate
- release-candidate and SDC metadata
- the exact client summary staged for airlock review

The helper tables are built in `src/ofh_feasibility/views.py`. They are aggregate-only by design:
participant IDs and pseudonymised IDs remain in the internal artefacts and are not returned by the
view builders.

## Audit behaviour

Notebook runs append the same tamper-evident audit event as CLI runs, with `actor_type="notebook"`.
The ledger still records hashes and SDC metadata only.
