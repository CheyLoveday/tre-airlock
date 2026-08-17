# Orchestration port — Snakemake → Nextflow / WDL → DNAnexus

**The DAG is the contract.** Every orchestrator drives the SAME pure core (`pipeline.stage_*` via
`scripts/run_stage.py`); only the wiring differs. Swapping Snakemake for Nextflow or WDL does not
touch a line of stage logic — this is the point Wave 3 demonstrates.

**Honesty:** Nextflow and WDL are the **DNAnexus-supported** workflow languages, so this is the
natural port target for the OFH execution model. The skeletons here are for **documentation** — they
show the mapping; they are **not** a claim that OFH runs Snakemake (it doesn't — that's our local
choice) or that this exact pipeline runs in the OFH tenant.

## Stage mapping

| Stage    | Reads                         | Writes                                          | Snakemake rule | Nextflow process | WDL task |
|----------|-------------------------------|-------------------------------------------------|----------------|------------------|----------|
| extract  | request, manifest, slice, qc  | `candidate.parquet`, `sources.json`, provenance | `rule extract` | `process extract`| `task extract` |
| qc       | candidate, sources            | `annotated.parquet`                             | `rule qc`      | `process qc`     | `task qc` |
| classify | annotated, sources            | `internal_carrier_table.parquet`, handoff       | `rule classify`| `process classify`| `task classify` |
| report   | internal table, sources       | `feasibility_summary.txt`                       | `rule report`  | `process report` | `task report` |
| airlock  | summary                       | `airlock_manifest.json`                         | `rule airlock` | `process airlock`| `task airlock` |

The single entrypoint each wrapper calls:
```bash
uv run python scripts/run_stage.py <extract|qc|classify|report|airlock> [config.yaml]
```

## Files
- `workflow/Snakefile` — the local reproducible-DAG path (Wave 2).
- `workflow/nextflow/main.nf` (+ `nextflow.config`) — the Nextflow DSL2 port skeleton.
- WDL equivalent (one `task` per stage, chained by file dependencies). Sketch of a single task:

```wdl
task extract {
  input { File config }
  command { uv run python scripts/run_stage.py extract ~{config} }
  output { File candidate = "results/candidate.parquet" }
}
workflow feasibility {
  input { File config }
  call extract { input: config = config }
  call qc      { input: ready = extract.candidate, config = config }
  # ... classify -> report -> airlock
}
```

## DNAnexus mapping (conceptual)
Inside the DNAnexus execution model, each stage is an **applet** and the DAG is a **workflow** (or a
Nextflow/WDL pipeline run via the platform's support). `dxapp.json`-style I/O specs would declare the
staged Parquet/JSON artefacts as inputs/outputs (this repository specifies that I/O contract through the
staged artefacts and the `pipeline.STAGES` dispatch table, not a shipped platform descriptor). The
governance boundaries — consent gate, SDC, the airlock manifest —
live in the pure core, so they hold identically regardless of the orchestrator.
