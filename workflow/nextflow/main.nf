// Nextflow (DSL2) PORT SKELETON of the feasibility DAG — mirrors workflow/Snakefile, one process
// per stage, each running the SAME pure core via scripts/run_stage.py (stage logic unchanged).
//
// Why this exists: Nextflow and WDL are the DNAnexus-supported workflow languages, so this shows the
// Snakemake DAG ports cleanly into the OFH execution model. It is a SKELETON for documentation, NOT a
// runnable claim that OFH uses Nextflow. The stages write to the configured results_dir; the channels
// below only enforce ordering (extract -> qc -> classify -> report -> airlock).
//
//   nextflow run workflow/nextflow/main.nf            (illustrative; needs nextflow + the uv env)

nextflow.enable.dsl = 2

params.config = 'config.yaml'
stageScript = "${projectDir}/scripts/run_stage.py"

process extract {
    output: val 'ok'
    script: "uv run python ${stageScript} extract ${params.config}"
}

process qc {
    input: val ready
    output: val 'ok'
    script: "uv run python ${stageScript} qc ${params.config}"
}

process classify {
    input: val ready
    output: val 'ok'
    script: "uv run python ${stageScript} classify ${params.config}"
}

process report {
    input: val ready
    output: val 'ok'
    script: "uv run python ${stageScript} report ${params.config}"
}

process airlock {
    input: val ready
    output: val 'ok'
    script: "uv run python ${stageScript} airlock ${params.config}"
}

workflow {
    // pipe the ordering token through the DAG; the same shape as the Snakemake rule chain.
    extract() | qc | classify | report | airlock
}
