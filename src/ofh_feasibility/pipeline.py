"""pipeline — stage orchestration (imperative shell): read via io -> call pure core -> write.

Three orchestration shapes over the SAME pure core:
- `run_pipeline` — in-memory chain over already-loaded data (no IO).
- `orchestrate` — wraps run_pipeline with the io readers/writers (the run_demo path).
- `stage_*` — file-staged orchestrators (Wave 2); each reads the prior stage's artefact, calls the
  core, writes the next. The Snakemake DAG wires these; they emit one structured log line per stage.

No business logic here — every decision lives in the pure core (qc/classify/sdc/reporting/airlock).
"""

from __future__ import annotations

import hashlib
import json
import logging
import subprocess
import sys
from collections import Counter
from datetime import UTC, datetime
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path
from typing import TYPE_CHECKING

import numpy as np
import pandas as pd

from . import (
    airlock,
    audit,
    bridge,
    classify,
    epi,
    extract,
    io,
    kernels,
    ofh_formats,
    qc,
    reporting,
    sdc,
)
from .models import EpiNotification

if TYPE_CHECKING:
    from .config import Config
    from .models import VariantRequest

logger = logging.getLogger(__name__)

# Output artefacts (relative to cfg.results_dir). The export candidate is staged separately.
INTERNAL_TABLE = "internal_carrier_table.parquet"
HANDOFF = "handoff_to_epi.csv"
SUMMARY = "feasibility_summary.txt"
MANIFEST = "airlock_manifest.json"
FREQ_CONTROL = "frequency_control_view.json"  # INTERNAL-only QC/credibility control
RELEASE_CANDIDATE = "release_candidate.json"  # the aggregate-only release object (Wave 5 gate)
AUDIT_LEDGER = "audit_ledger.jsonl"  # tamper-evident Merkle evidence ledger (hashes + metadata)
AUDIT_ROOT = "audit_root.txt"
AIRLOCK_PENDING = "airlock_pending"  # egress-pending area: the canonical release payload + manifest
RELEASE_PAYLOAD = bridge.RELEASE_PAYLOAD  # the SOLE releasable artefact: exact Lean bytes
# Staged intermediates (file-staged DAG path).
CANDIDATE = "candidate.parquet"
ANNOTATED = "annotated.parquet"
SOURCES = "sources.json"
PREFLIGHT = "variant_preflight.json"  # Wave 7: build reference-match + normalize + strand result
PROVENANCE = "provenance.json"
BATCH_SUMMARY = "batch_feasibility_summary.txt"
BATCH_MANIFEST = "batch_airlock_manifest.json"
# Wave 8 (epidemiology return loop) final post-phenotype artefacts.
FINAL_SUMMARY = "final_feasibility_summary.txt"
FINAL_RELEASE_CANDIDATE = "final_release_candidate.json"
FINAL_MANIFEST = "final_airlock_manifest.json"
CHECKPOINTS = "human_review_checkpoints.jsonl"  # the human-review decision ledger (Wave 8)
EPI_NOTIFICATION = "epi_notification.json"  # internal rapid-turnaround intake/ETA note (Wave 8)
BATCH_RELEASE_CANDIDATE = "batch_release_candidate.json"  # the batch's authorized release object

_INPUT_FILES = {
    "variant_request": "variant_request.csv",
    "variant_manifest": "variant_manifest.csv",
    "participant_table": "participant_table.parquet",
    "genotype_slice": "genotype_slice.parquet",
    "sample_qc_metrics": "sample_qc_metrics.tsv",
}
_OFH_TRE_INPUT_FILES = {
    "variant_request": "variant_request.csv",
    "participant_table": "participant_table.parquet",
    "array_pvcf": "ofh_snv.chr10-b0001.vcf.gz",
    "array_pvcf_index": "ofh_snv.chr10-b0001.vcf.gz.tbi",
    "array_sample": "ofh_snv.chr10-b0001.sample",
    "array_sample_qc": "ofh_sample_qc_metrics.tsv",
    "array_kinship": "ofh_snv_kinship.txt",
    "array_regions": "ofh_snv_regions.bed",
    "imputed_pvcf": "ofh_imputed.v6.chr10-b0001.vcf.gz",
    "imputed_pvcf_index": "ofh_imputed.v6.chr10-b0001.vcf.gz.tbi",
    "imputed_sample": "ofh_imputed.v6.chr10-b0001.sample",
    "imputed_sample_qc": "ofh_imputed_sample_qc_metrics.v6.tsv",
    "imputed_summary_stats": "ofh_imputed_variant_summary_stats.v6.vcf.gz",
    "imputed_summary_stats_index": "ofh_imputed_variant_summary_stats.v6.vcf.gz.tbi",
    "imputed_regions": "ofh_imputed_regions.v6.bed",
}
_PROVENANCE_PKGS = ("numpy", "pandas", "pyarrow", "numba", "pydantic")


def _check_carrier_definition(request: VariantRequest, cfg: Config) -> None:
    # the count (cfg-driven) and the client note (request-driven) must use the same definition.
    if request.carrier_definition != cfg.carrier_definition:
        raise ValueError(
            f"carrier_definition mismatch: request {request.carrier_definition!r} "
            f"vs config {cfg.carrier_definition!r}"
        )


def _pkg_version(name: str) -> str:
    try:
        return version(name)
    except PackageNotFoundError:
        return "not-installed"


def _sha256_file(path: str | Path, chunk_size: int = 1024 * 1024) -> str:
    """Hash a file incrementally so provenance/audit never materializes large inputs."""
    h = hashlib.sha256()
    with Path(path).open("rb") as fh:
        for chunk in iter(lambda: fh.read(chunk_size), b""):
            h.update(chunk)
    return h.hexdigest()


def _provenance_input_files(cfg: Config) -> dict[str, str]:
    """Input files that define a run for provenance / run-id binding."""
    if cfg.source_format == "ofh_tre":
        return _OFH_TRE_INPUT_FILES
    return _INPUT_FILES


def _input_paths(cfg: Config) -> dict[str, Path]:
    data_dir = Path(cfg.data_dir)
    paths = {key: data_dir / fname for key, fname in _provenance_input_files(cfg).items()}
    if cfg.request_path:
        paths["variant_request"] = Path(cfg.request_path)
    if cfg.variant_identifiability_path:
        paths["variant_identifiability"] = Path(cfg.variant_identifiability_path)
    return paths


def _request_path(cfg: Config) -> Path:
    return _input_paths(cfg)["variant_request"]


def required_input_files(cfg: Config) -> dict[str, str]:
    """Files the file-staged workflow must see before extract can run."""
    return {key: str(path) for key, path in _input_paths(cfg).items()}


def _ground_manifest_identifiability(cfg: Config, manifest: pd.DataFrame) -> pd.DataFrame:
    """Apply the small public-list-derived identifiability artifact when configured."""
    if not cfg.variant_identifiability_path:
        return manifest
    artifact = io.read_variant_identifiability(cfg.variant_identifiability_path)
    return extract.apply_identifiability_artifact(manifest, artifact)


def build_provenance(cfg: Config, request: VariantRequest) -> dict:
    """A per-run provenance record: config + input hashes + versions (reproducibility evidence)."""
    inputs = {
        key: _sha256_file(path)
        for key, path in _input_paths(cfg).items()
    }
    cfg_dump = cfg.model_dump()
    cfg_sha = hashlib.sha256(json.dumps(cfg_dump, sort_keys=True).encode()).hexdigest()
    return {
        "generated_utc": datetime.now(UTC).isoformat(timespec="seconds"),
        "study_id": request.study_id,
        "cpra": request.cpra,
        "config": cfg_dump,
        "config_sha256": cfg_sha,
        "input_sha256": inputs,
        "versions": {
            "python": sys.version.split()[0],
            "ofh_feasibility": _pkg_version("ofh_feasibility"),
            **{p: _pkg_version(p) for p in _PROVENANCE_PKGS},
        },
    }


def run_pipeline(
    cfg: Config,
    request: VariantRequest,
    manifest: pd.DataFrame,
    participants: pd.DataFrame,
    genotype_slice: pd.DataFrame,
    sample_qc: pd.DataFrame,
    reference: dict | None = None,
    audience: reporting.Audience = "neutral",
) -> dict:
    """In-memory chain: validate -> slice -> QC -> classify -> report -> airlock (no IO)."""
    _check_carrier_definition(request, cfg)
    manifest = _ground_manifest_identifiability(cfg, manifest)
    manifest_row = extract.validate_variant(manifest, request)  # stage 1: identifiable (manifest)
    # stage 1 pre-flight: reference-match the build, normalize, resolve strand (palindromic SNPs).
    preflight = extract.normalize_and_reference_match(
        request, reference or io.default_reference(), extract.observed_maf(manifest_row)
    )
    preflight = extract.attach_source_availability(preflight, manifest_row, request)
    sources = extract.resolve_sources(manifest_row, request, cfg)  # stage 2: source decision
    variant_info = sources["variant_info"]

    candidate = extract.build_candidate_table(request, participants, genotype_slice, sample_qc)
    accounting = qc.gate_accounting(candidate, cfg, variant_info, sources)
    candidate = pd.concat([candidate, accounting], axis=1)
    # gate BOTH QC masks by source availability (on_array/on_imputed + requested_source). Without
    # the array gate, array carriers would be counted even when the request is imputed-only or the
    # variant is not on the array (on_array=FALSE) — evidence the client did not ask for (F2).
    array_mask = accounting["array_credible"].to_numpy()
    imputed_mask = accounting["imputed_credible"].to_numpy()
    consent_mask = accounting["consent_ok"].to_numpy()
    flags = qc.sample_flag_series(candidate)

    classified = classify.classify_carriers(
        candidate, array_mask, imputed_mask, consent_mask, flags, cfg, variant_info
    )

    cells = classify.project_cells(classified, cfg, variant_info=variant_info)
    kernel = reconcile_array_direct_kernel_count(
        cfg, candidate, array_mask, consent_mask, classified
    )
    quality_sensitivity = reporting.build_quality_sensitivity(classified, cfg, variant_info)
    ancestry = sdc.apply_sdc_strata(
        classify.count_by_ancestry(classified), cfg, expected_total=cells["total"]
    )
    sdc_out = sdc.apply_sdc(cells, cfg)
    result = reporting.build_result(
        request, cells, sdc_out, variant_info, cfg, ancestry, preflight["caveats"],
        variant_on_array=sources["variant_on_array"],
        variant_on_imputed=sources["variant_on_imputed"],
    )
    release_candidate = airlock.build_release_candidate(result, sdc_out, cfg)
    manifest_dict = airlock.build_airlock_manifest(request, airlock.default_airlock_files(), cfg)
    return {
        "result": result,
        "sources": sources,
        "preflight": preflight,
        "cells": cells,
        "sdc": sdc_out,
        "kernel_counts": kernel["counts"],
        "quality_sensitivity": quality_sensitivity,
        "gt_array": kernel["gt_array"],
        "array_mask": kernel["mask"],
        "kernel_include_homalt": kernel["include_homalt"],
        "accounting": accounting,
        "classified": classified,
        "internal": reporting.build_internal_table(classified),
        "handoff": reporting.build_epi_handoff(classified),
        "summary": reporting.build_audience_summary(
            audience, result, request, cfg, release_candidate, quality_sensitivity
        ),
        "frequency_control": reporting.build_frequency_control(candidate, array_mask, request, cfg),
        "release_candidate": release_candidate,
        "airlock_manifest": manifest_dict,
    }


def reconcile_array_direct_kernel_count(
    cfg: Config,
    candidate: pd.DataFrame,
    array_mask,
    consent_mask,
    classified: pd.DataFrame,
) -> dict:
    """Use the Numba kernel as a numeric reconciliation check for array-direct included carriers."""
    gt_array = extract.to_genotype_array(candidate, "array")
    kernel_mask = np.asarray(array_mask, dtype=bool) & np.asarray(consent_mask, dtype=bool)
    kernel_counts = kernels.count_carriers(
        gt_array, kernel_mask, include_homalt=cfg.carrier_definition != "het_only"
    )
    pandas_count = int(
        (
            (classified["decision"] == "included")
            & (classified["evidence_priority"] == "array_direct")
        ).sum()
    )
    if kernel_counts[0] != pandas_count:
        raise RuntimeError(
            "Numba array-direct carrier count diverged from classified table: "
            f"kernel={kernel_counts[0]} pandas={pandas_count}"
        )
    return {
        "counts": kernel_counts,
        "gt_array": gt_array,
        "mask": kernel_mask,
        "include_homalt": cfg.carrier_definition != "het_only",
        "pandas_array_direct": pandas_count,
    }


def write_outputs(
    bundle: dict, cfg: Config, request: VariantRequest | None = None,
    prov: dict | None = None, actor_type: str = "cli",
) -> dict:
    """Write the governed artefacts inside ONE committed-generation release transaction.

    The runtime Lean airlock adjudicates FIRST (fail closed); the internal artefacts AND the
    audit event are written inside the transaction, and the `release.ready` receipt commits the
    generation LAST — so a failure anywhere (including the audit append) leaves no committed
    generation. Only the exact Lean-emitted payload is staged in the egress-pending area; every
    Python-rendered artefact stays INTERNAL.
    """
    results = Path(cfg.results_dir)
    pending = results / AIRLOCK_PENDING
    paths = {
        "internal": results / INTERNAL_TABLE,
        "handoff": results / HANDOFF,
        "summary": results / SUMMARY,
        "frequency_control": results / FREQ_CONTROL,
        "release_candidate": results / RELEASE_CANDIDATE,
        "manifest": results / MANIFEST,
        "release_payload": pending / RELEASE_PAYLOAD,
        "release_ready": pending / bridge.RELEASE_READY,
    }
    candidate = bundle["release_candidate"]
    with bridge.release_transaction(candidate, pending) as decision:
        bundle["airlock_decision"] = decision
        io.write_parquet(bundle["internal"], paths["internal"])  # INTERNAL-TRE-ONLY
        io.write_csv(bundle["handoff"], paths["handoff"])  # INTERNAL-TRE-ONLY (pseudonymised)
        io.write_json(bundle["frequency_control"], paths["frequency_control"])  # INTERNAL-ONLY
        io.write_json(candidate.model_dump(), paths["release_candidate"])
        io.write_text(bundle["summary"], paths["summary"])  # INTERNAL analyst note (SDC-applied)
        io.write_json(bundle["airlock_manifest"], paths["manifest"])
        if request is not None and prov is not None:
            bundle["paths"] = paths
            bundle["audit_event"] = emit_audit_event(
                cfg, request, bundle, prov, actor_type=actor_type
            )
    return paths


def _airlock_audit_record(decision: bridge.AirlockDecision, cfg: Config) -> dict:
    """Audit evidence copied DIRECTLY from the adjudication decision — never reconstructed.

    Identical to the `release.ready` commit receipt: exact request bytes -> policy identity ->
    executable identity -> payload bytes -> canonical file. Digests come from the immutable
    `AirlockDecision` captured at invocation time; the retained request preimage (INTERNAL) is
    what makes byte-for-byte replay possible, while the digests alone support verification.
    """
    return bridge.ready_receipt(decision, cfg.results_dir)


def _git_commit() -> str:
    try:
        out = subprocess.run(
            ["git", "rev-parse", "HEAD"], capture_output=True, text=True, timeout=5
        )
        return out.stdout.strip() or "unknown"
    except Exception:
        return "unknown"


def emit_audit_event(
    cfg: Config, request: VariantRequest, bundle: dict, prov: dict, actor_type: str = "cli"
) -> dict:
    """Append a canonical run event (hashes + SDC metadata, no participant data) to the ledger."""
    results = Path(cfg.results_dir)
    ledger = results / AUDIT_LEDGER
    events = io.read_jsonl(ledger) if ledger.exists() else []
    output_sha = {
        name: _sha256_file(p)
        for name, p in bundle["paths"].items()
        if Path(p).is_file()
    }
    sdc_meta = {
        k: bundle["sdc"][k]
        for k in (
            "client_total",
            "breakdown_suppressed",
            "total_suppressed",
            "min_cell",
            "round_to",
        )
    }
    event = audit.build_run_event(
        request_id=request.study_id,
        cpra=request.cpra,
        timestamp=datetime.now(UTC).isoformat(timespec="seconds"),
        git_commit=_git_commit(),
        config_sha256=prov["config_sha256"],
        input_sha256=prov["input_sha256"],
        output_sha256=output_sha,
        sdc=sdc_meta,
        parent_root=audit.root_of_events(events),
        actor_type=actor_type,
        airlock=_airlock_audit_record(bundle["airlock_decision"], cfg),
    )
    io.append_jsonl(event, ledger)
    io.write_text(audit.root_of_events(events + [event]), results / AUDIT_ROOT)
    return event


def emit_stage_event(
    cfg: Config, stage: str, output_files: list, airlock: dict | None = None
) -> dict:
    """Append a per-stage audit event (stage + output hashes, no participant data) to the ledger.

    The file-staged (Snakemake) path emits one event per stage, chained by parent_root, so the
    verifier proves the whole DAG run was not modified, reordered, or truncated. Hashes + metadata
    only — never participant-level data.
    """
    results = Path(cfg.results_dir)
    ledger = results / AUDIT_LEDGER
    events = io.read_jsonl(ledger) if ledger.exists() else []
    request = io.read_request(_request_path(cfg))
    output_sha = {
        Path(f).name: _sha256_file(f)
        for f in output_files
        if Path(f).is_file()
    }
    config_sha = hashlib.sha256(json.dumps(cfg.model_dump(), sort_keys=True).encode()).hexdigest()
    event = {
        "stage": stage,
        "actor_type": "workflow",
        "request_id": request.study_id,
        "cpra": request.cpra,
        "timestamp": datetime.now(UTC).isoformat(timespec="seconds"),
        "git_commit": _git_commit(),
        "config_sha256": config_sha,
        "output_sha256": output_sha,
        "parent_root": audit.root_of_events(events),
    }
    if airlock is not None:
        event["airlock"] = airlock
    io.append_jsonl(event, ledger)
    io.write_text(audit.root_of_events(events + [event]), results / AUDIT_ROOT)
    return event


def orchestrate(
    cfg: Config,
    request: VariantRequest,
    genotype_source: io.GenotypeSource | None = None,
    audience: reporting.Audience = "neutral",
    actor_type: str = "cli",
) -> dict:
    """run_demo path: read inputs via io, run the in-memory chain, write the governed artefacts.

    genotype_source defaults to the CSV/Parquet stand-in; pass a VcfBgenShapedGenotypeSource to run
    the same stages over VCF/BGEN-shaped fixtures (the genomic-IO swap; Wave 3).
    """
    if cfg.source_format == "ofh_tre" and genotype_source is None:
        # native OFH ingest (Wave 9): per-region pVCF + summary-stats VCF + OFH sample-QC TSV.
        source = ofh_formats.OfhTreGenotypeSource(cfg.data_dir, request.cpra)
        manifest = ofh_formats.read_ofh_variant_manifest(cfg.data_dir, request.cpra)
        sample_qc = ofh_formats.read_ofh_sample_qc(cfg.data_dir)
    else:
        source = genotype_source or io.CsvGenotypeSource(cfg.data_dir)
        manifest = io.read_variant_manifest(cfg.data_dir)
        sample_qc = io.read_sample_qc(cfg.data_dir)
    manifest = _ground_manifest_identifiability(cfg, manifest)
    participants = io.read_participants(cfg.data_dir)
    genotype_slice = source.read_slice()
    bundle = run_pipeline(
        cfg, request, manifest, participants, genotype_slice, sample_qc, audience=audience
    )
    prov = build_provenance(cfg, request)
    io.write_json(prov, Path(cfg.results_dir) / PROVENANCE)
    bundle["paths"] = write_outputs(bundle, cfg, request=request, prov=prov, actor_type=actor_type)
    # internal rapid-turnaround note (Wave 8): records the run state alongside the genotype run.
    notification = build_epi_notification(
        request, "genotype_running", run_id=epi.build_run_id(request, prov)
    )
    io.write_json(notification.model_dump(), Path(cfg.results_dir) / EPI_NOTIFICATION)
    bundle["notification"] = notification
    return bundle


def build_epi_notification(
    request: VariantRequest, state: str, run_id: str | None = None
) -> EpiNotification:
    """Build the internal rapid-turnaround notification (Wave 8). due_date / eta / owner come from
    the intake system in production; here they carry their model defaults."""
    return EpiNotification(
        study_id=request.study_id,
        cpra=request.cpra,
        run_id=run_id or epi.build_run_id(request),
        received_timestamp=datetime.now(UTC).isoformat(timespec="seconds"),
        workflow_state=state,
    )


# --- batch / multi-variant (composite risk profile) -------------------------------------------


def _client_token(n: int, cfg: Config) -> str:
    mc, rb = cfg.sdc_min_cell, cfg.sdc_round_to
    return f"<{mc}" if (n < mc or sdc.round_to(n, rb) < mc) else f"~{sdc.round_to(n, rb)}"


def combine_feasibility(per_variant: list[dict], cfg: Config) -> dict:
    """Combine per-variant results into the UNION carrier set (participants carrying >=1 variant).

    The client-facing answer for a composite risk profile is the SDC-controlled union total.
    Per-variant and overlap counts remain internal by default because they can reveal suppressed
    cells by differencing.
    """
    included = {
        pv["cpra"]: set(
            pv["classified"].loc[pv["classified"]["decision"] == "included", "participant_id"]
        )
        for pv in per_variant
    }
    combined = set().union(*included.values()) if included else set()
    membership = Counter(pid for s in included.values() for pid in s)
    overlap = sum(1 for n in membership.values() if n >= 2)
    # Conservative SDC for composite requests: the union total is the client answer. Publishing
    # per-variant counts beside the union can reveal suppressed intersections by differencing.
    breakdown_suppressed = len(included) > 1
    return {
        "combined_carriers": len(combined),
        "combined_client_total": _client_token(len(combined), cfg),
        "overlap_carriers": overlap,
        "overlap_client": _client_token(overlap, cfg),
        "breakdown_suppressed": breakdown_suppressed,
        "per_variant": {
            cpra: {"included": len(s), "client": _client_token(len(s), cfg)}
            for cpra, s in included.items()
        },
    }


def orchestrate_batch(
    cfg: Config,
    batch,
    genotype_source: io.GenotypeSource | None = None,
    audience: reporting.Audience = "neutral",
) -> dict:
    """Run each variant in a batch over the same inputs, then combine into the union carrier set."""
    participants = io.read_participants(cfg.data_dir)
    if cfg.source_format == "ofh_tre" and genotype_source is None:
        sample_qc = ofh_formats.read_ofh_sample_qc(cfg.data_dir)
        per_variant = []
        for request in batch.variants:
            manifest = _ground_manifest_identifiability(
                cfg, ofh_formats.read_ofh_variant_manifest(cfg.data_dir, request.cpra)
            )
            genotype_slice = ofh_formats.OfhTreGenotypeSource(
                cfg.data_dir, request.cpra
            ).read_slice()
            per_variant.append(
                {
                    "cpra": request.cpra,
                    "classified": run_pipeline(
                        cfg, request, manifest, participants, genotype_slice, sample_qc
                    )["classified"],
                }
            )
    else:
        source = genotype_source or io.CsvGenotypeSource(cfg.data_dir)
        manifest = _ground_manifest_identifiability(cfg, io.read_variant_manifest(cfg.data_dir))
        genotype_slice = source.read_slice()
        sample_qc = io.read_sample_qc(cfg.data_dir)
        per_variant = [
            {
                "cpra": request.cpra,
                "classified": run_pipeline(
                    cfg, request, manifest, participants, genotype_slice, sample_qc
                )["classified"],
            }
            for request in batch.variants
        ]
    combined = combine_feasibility(per_variant, cfg)
    summary = reporting.build_batch_summary_for_audience(audience, batch, combined, cfg)
    # governed release path (F1): the batch aggregate goes through the SAME runtime Lean airlock
    # as the single-variant release — adjudicate BEFORE writing, then audit the run.
    candidate = airlock.build_batch_release_candidate(batch, combined, cfg)
    results = Path(cfg.results_dir)
    pending = results / AIRLOCK_PENDING
    manifest = airlock.build_batch_airlock_manifest(batch, airlock.batch_airlock_files(), cfg)
    summary_path = results / BATCH_SUMMARY
    candidate_path = results / BATCH_RELEASE_CANDIDATE
    manifest_path = results / BATCH_MANIFEST
    with bridge.release_transaction(candidate, pending) as decision:  # the one release txn
        io.write_text(summary, summary_path)  # INTERNAL analyst note
        io.write_json(candidate.model_dump(), candidate_path)
        io.write_json(manifest, manifest_path)
        io.write_json(manifest, pending / BATCH_MANIFEST)
        emit_batch_audit_event(
            cfg, batch, candidate,
            [summary_path, candidate_path, manifest_path, pending / RELEASE_PAYLOAD],
            decision=decision,
        )
    logger.info(
        "batch: %d variants -> combined carriers (>=1 variant) %s",
        len(batch.variants),
        combined["combined_client_total"],
    )
    return {
        "per_variant": per_variant,
        "combined": combined,
        "summary": summary,
        "release_candidate": candidate,
        "airlock_manifest": manifest,
    }


def emit_batch_audit_event(
    cfg: Config, batch, candidate, output_paths: list, decision: bridge.AirlockDecision
) -> dict:
    """Append a canonical batch run event (hashes + SDC metadata, no participant data)."""
    results = Path(cfg.results_dir)
    ledger = results / AUDIT_LEDGER
    events = io.read_jsonl(ledger) if ledger.exists() else []
    data_dir = Path(cfg.data_dir)
    input_sha = {
        key: _sha256_file(data_dir / fname)
        for key, fname in _provenance_input_files(cfg).items()
        if key != "variant_request" and (data_dir / fname).is_file()
    }
    if cfg.variant_identifiability_path:
        input_sha["variant_identifiability"] = _sha256_file(cfg.variant_identifiability_path)
    if cfg.variant_catalog_path:
        input_sha["variant_catalog"] = _sha256_file(cfg.variant_catalog_path)
    output_sha = {
        Path(p).name: _sha256_file(p)
        for p in output_paths
        if Path(p).is_file()
    }
    cfg_sha = hashlib.sha256(json.dumps(cfg.model_dump(), sort_keys=True).encode()).hexdigest()
    event = audit.build_run_event(
        request_id=batch.study_id,
        cpra=candidate.cpra,
        timestamp=datetime.now(UTC).isoformat(timespec="seconds"),
        git_commit=_git_commit(),
        config_sha256=cfg_sha,
        input_sha256=input_sha,
        output_sha256=output_sha,
        sdc={
            "client_total": candidate.client_total,
            "breakdown_suppressed": candidate.breakdown_suppressed,
            "min_cell": candidate.min_cell,
            "round_to": candidate.round_to,
        },
        parent_root=audit.root_of_events(events),
        airlock=_airlock_audit_record(decision, cfg),
    )
    io.append_jsonl(event, ledger)
    io.write_text(audit.root_of_events(events + [event]), results / AUDIT_ROOT)
    return event


# --- Wave 8: epidemiology return loop (finalize the post-phenotype eligible count) ------------


def _checkpoint_gate(checkpoints) -> None:
    """Fail closed if any human-review checkpoint is a block or an unresolved query (Wave 8)."""
    blocked = [c for c in checkpoints if c.decision in ("block", "query")]
    if blocked:
        names = ", ".join(f"{c.checkpoint}={c.decision}" for c in blocked)
        raise ValueError(
            f"final release blocked by human review: {names} — resolve before finalizing"
        )


def emit_finalize_audit_event(
    cfg: Config, request, candidate, output_paths, decision: bridge.AirlockDecision
) -> dict:
    """Append a canonical finalize (post-phenotype) run event — hashes + SDC metadata, no PII."""
    results = Path(cfg.results_dir)
    ledger = results / AUDIT_LEDGER
    events = io.read_jsonl(ledger) if ledger.exists() else []
    data_dir = Path(cfg.data_dir)
    input_sha = {
        key: _sha256_file(data_dir / fname)
        for key, fname in _provenance_input_files(cfg).items()
        if (data_dir / fname).is_file()
    }
    if cfg.variant_identifiability_path:
        input_sha["variant_identifiability"] = _sha256_file(cfg.variant_identifiability_path)
    output_sha = {
        Path(p).name: _sha256_file(p)
        for p in output_paths
        if Path(p).is_file()
    }
    cfg_sha = hashlib.sha256(json.dumps(cfg.model_dump(), sort_keys=True).encode()).hexdigest()
    event = audit.build_run_event(
        request_id=request.study_id,
        cpra=request.cpra,
        timestamp=datetime.now(UTC).isoformat(timespec="seconds"),
        git_commit=_git_commit(),
        config_sha256=cfg_sha,
        input_sha256=input_sha,
        output_sha256=output_sha,
        sdc={
            "stage": "finalize_eligible",
            "client_total": candidate.client_total,
            "min_cell": candidate.min_cell,
            "round_to": candidate.round_to,
        },
        parent_root=audit.root_of_events(events),
        airlock=_airlock_audit_record(decision, cfg),
    )
    io.append_jsonl(event, ledger)
    io.write_text(audit.root_of_events(events + [event]), results / AUDIT_ROOT)
    return event


def finalize_eligible(
    cfg: Config,
    request: VariantRequest,
    genotype_result,
    epi_return,
    checkpoints=(),
    expected_run_id: str | None = None,
) -> dict:
    """Validate the epi return against the genotype run, build + authorize the final post-phenotype
    result, write the governed final artefacts, and audit the round trip.

    Fails closed on a blocking/query human-review checkpoint, an invalid return, or a
    non-compliant final release candidate (the runtime Lean airlock, via the release transaction,
    is the gate). The final figure is released via the Lean airlock (release.json); all
    summaries stay INTERNAL-only.
    """
    _checkpoint_gate(checkpoints)
    epi.validate_epi_return(
        epi_return, genotype_result, request, expected_run_id=expected_run_id
    )
    final = epi.build_final_result(genotype_result, epi_return, cfg)
    candidate = airlock.build_final_release_candidate(final, cfg)
    results = Path(cfg.results_dir)
    pending = results / AIRLOCK_PENDING
    summary = reporting.build_final_summary(final, request, cfg)
    manifest = airlock.build_airlock_manifest(request, airlock.final_airlock_files(), cfg)
    summary_path, candidate_path = results / FINAL_SUMMARY, results / FINAL_RELEASE_CANDIDATE
    manifest_path = results / FINAL_MANIFEST
    # the final generation SUPERSEDES the preliminary one at the canonical path: the transaction
    # rotates the prior payload to INTERNAL history and commits (release.ready) only after the
    # final artefacts AND the audit event are written.
    with bridge.release_transaction(candidate, pending) as decision:
        io.write_text(summary, summary_path)  # INTERNAL analyst note
        io.write_json(candidate.model_dump(), candidate_path)
        io.write_json(manifest, manifest_path)
        io.write_json(manifest, pending / FINAL_MANIFEST)
        emit_finalize_audit_event(
            cfg, request, candidate,
            [summary_path, candidate_path, manifest_path, pending / RELEASE_PAYLOAD],
            decision=decision,
        )
    logger.info(
        "finalize: genotype ceiling %s -> post-phenotype eligible %s",
        final.client_genotype_ceiling,
        final.client_eligible,
    )
    return {
        "final_result": final,
        "final_summary": summary,
        "release_candidate": candidate,
        "airlock_manifest": manifest,
        "paths": {
            "final_summary": summary_path,
            "final_release_candidate": candidate_path,
            "final_manifest": manifest_path,
        },
    }


def orchestrate_finalize(
    cfg: Config, request: VariantRequest, epi_return, checkpoints=()
) -> dict:
    """Run the genotype pipeline for the ceiling, then finalize against the epi return (Wave 8)."""
    genotype = orchestrate(cfg, request)
    bundle = finalize_eligible(
        cfg,
        request,
        genotype["result"],
        epi_return,
        checkpoints,
        expected_run_id=genotype["notification"].run_id,
    )
    bundle["genotype"] = genotype
    return bundle


# --- file-staged orchestrators (the Snakemake DAG path; thin: read -> core -> write) ----------


def stage_extract(cfg: Config) -> None:
    """Validate the variant + build the dataset slice; stage candidate + sources + provenance."""
    results = Path(cfg.results_dir)
    request = io.read_request(_request_path(cfg))
    _check_carrier_definition(request, cfg)
    if cfg.source_format == "ofh_tre":
        manifest = ofh_formats.read_ofh_variant_manifest(cfg.data_dir, request.cpra)
        genotype_slice = ofh_formats.OfhTreGenotypeSource(cfg.data_dir, request.cpra).read_slice()
        sample_qc = ofh_formats.read_ofh_sample_qc(cfg.data_dir)
    else:
        manifest = io.read_variant_manifest(cfg.data_dir)
        genotype_slice = io.read_genotype_slice(cfg.data_dir)
        sample_qc = io.read_sample_qc(cfg.data_dir)
    manifest = _ground_manifest_identifiability(cfg, manifest)
    participants = io.read_participants(cfg.data_dir)

    manifest_row = extract.validate_variant(manifest, request)
    preflight = extract.normalize_and_reference_match(
        request, io.default_reference(), extract.observed_maf(manifest_row)
    )
    preflight = extract.attach_source_availability(preflight, manifest_row, request)
    sources = extract.resolve_sources(manifest_row, request, cfg)
    candidate = extract.build_candidate_table(request, participants, genotype_slice, sample_qc)
    io.write_parquet(candidate, results / CANDIDATE)
    io.write_json(sources, results / SOURCES)
    io.write_json(preflight, results / PREFLIGHT)
    io.write_json(build_provenance(cfg, request), results / PROVENANCE)
    logger.info(
        "extract: %d participants -> %d candidate rows | DR2=%s use_array=%s use_imputed=%s "
        "build=%s strand=%s",
        len(participants),
        len(candidate),
        sources["variant_info"],
        sources["use_array"],
        sources["use_imputed"],
        preflight["build_resolved"],
        preflight["strand"],
    )
    emit_stage_event(
        cfg,
        "extract",
        [results / CANDIDATE, results / SOURCES, results / PREFLIGHT, results / PROVENANCE],
    )


def stage_qc(cfg: Config) -> None:
    """Compute the per-row QC masks over the slice; stage the annotated table."""
    results = Path(cfg.results_dir)
    candidate = io.read_parquet(results / CANDIDATE)
    sources = io.read_json(results / SOURCES)
    # gate both masks by source availability (F2): the staged path mirrors run_pipeline exactly.
    accounting = qc.gate_accounting(candidate, cfg, sources["variant_info"], sources)
    annotated = pd.concat([candidate, accounting], axis=1)
    annotated["array_ok"] = accounting["array_credible"].to_numpy()
    annotated["imputed_ok"] = accounting["imputed_credible"].to_numpy()
    annotated["consent_ok"] = accounting["consent_ok"].to_numpy()
    annotated["flag_str"] = qc.sample_flag_series(candidate).to_numpy()
    io.write_parquet(annotated, results / ANNOTATED)
    logger.info(
        "qc: %d rows | array_ok=%d imputed_ok=%d consent_ok=%d",
        len(annotated),
        int(annotated["array_ok"].sum()),
        int(annotated["imputed_ok"].sum()),
        int(annotated["consent_ok"].sum()),
    )
    emit_stage_event(cfg, "qc", [results / ANNOTATED])


def stage_classify(cfg: Config) -> None:
    """Classify candidates (consent gate + confidence); stage the internal table + epi handoff."""
    results = Path(cfg.results_dir)
    annotated = io.read_parquet(results / ANNOTATED)
    sources = io.read_json(results / SOURCES)
    classified = classify.classify_carriers(
        annotated,
        annotated["array_ok"].to_numpy(),
        annotated["imputed_ok"].to_numpy(),
        annotated["consent_ok"].to_numpy(),
        annotated["flag_str"],
        cfg,
        sources["variant_info"],
    )
    kernel = reconcile_array_direct_kernel_count(
        cfg,
        annotated,
        annotated["array_ok"].to_numpy(),
        annotated["consent_ok"].to_numpy(),
        classified,
    )
    io.write_parquet(reporting.build_internal_table(classified), results / INTERNAL_TABLE)
    io.write_csv(reporting.build_epi_handoff(classified), results / HANDOFF)
    cells = classify.project_cells(classified, cfg, variant_info=sources["variant_info"])
    logger.info(
        "classify: %d candidates -> included=%d (high=%d conditional=%d) excluded=%d "
        "array_direct_reconciled=%d",
        len(classified),
        cells["total"],
        cells["high_confidence"],
        cells["conditional"],
        cells["excluded"],
        kernel["pandas_array_direct"],
    )
    emit_stage_event(cfg, "classify", [results / INTERNAL_TABLE, results / HANDOFF])


def stage_report(cfg: Config) -> None:
    """Aggregate + SDC + the client feasibility note; stage the summary (+ airlock-pending copy)."""
    results = Path(cfg.results_dir)
    classified = io.read_parquet(results / INTERNAL_TABLE)
    annotated = io.read_parquet(results / ANNOTATED)
    request = io.read_request(_request_path(cfg))
    sources = io.read_json(results / SOURCES)
    preflight = io.read_json(results / PREFLIGHT)
    cells = classify.project_cells(classified, cfg, variant_info=sources["variant_info"])
    ancestry = sdc.apply_sdc_strata(
        classify.count_by_ancestry(classified), cfg, expected_total=cells["total"]
    )
    sdc_out = sdc.apply_sdc(cells, cfg)
    quality_sensitivity = reporting.build_quality_sensitivity(
        classified, cfg, sources["variant_info"]
    )
    result = reporting.build_result(
        request, cells, sdc_out, sources["variant_info"], cfg, ancestry,
        tuple(preflight.get("caveats", ())),
        variant_on_array=sources.get("variant_on_array", False),
        variant_on_imputed=sources.get("variant_on_imputed", False),
    )
    summary = reporting.build_feasibility_summary(result, request, cfg, quality_sensitivity)
    freq = reporting.build_frequency_control(
        annotated, annotated["array_ok"].to_numpy(), request, cfg
    )
    io.write_json(freq, results / FREQ_CONTROL)  # INTERNAL-only QC/credibility control
    # runtime release gate: the Lean airlock adjudicates BEFORE any client-shaped artefact lands;
    # the stage's artefacts + audit event sit inside the transaction, committed by release.ready.
    candidate = airlock.build_release_candidate(result, sdc_out, cfg)
    with bridge.release_transaction(candidate, results / AIRLOCK_PENDING) as decision:
        io.write_json(candidate.model_dump(), results / RELEASE_CANDIDATE)
        io.write_text(summary, results / SUMMARY)  # INTERNAL analyst note
        emit_stage_event(
            cfg, "report",
            [results / SUMMARY, results / FREQ_CONTROL, results / RELEASE_CANDIDATE,
             results / AIRLOCK_PENDING / RELEASE_PAYLOAD],
            airlock=_airlock_audit_record(decision, cfg),
        )
    logger.info(
        "report: total=%d -> client=%s breakdown_suppressed=%s",
        cells["total"],
        result.client_total,
        result.breakdown_suppressed,
    )


def stage_airlock(cfg: Config) -> None:
    """Build the airlock manifest (governed transfer request); stage it for review."""
    results = Path(cfg.results_dir)
    request = io.read_request(_request_path(cfg))
    manifest_dict = airlock.build_airlock_manifest(request, airlock.default_airlock_files(), cfg)
    io.write_json(manifest_dict, results / MANIFEST)
    io.write_json(manifest_dict, results / AIRLOCK_PENDING / MANIFEST)
    exports = sum(f["export_to_client"] for f in manifest_dict["files"])
    logger.info(
        "airlock: %d files staged, %d export candidate(s)", len(manifest_dict["files"]), exports
    )
    emit_stage_event(cfg, "airlock", [results / MANIFEST])


# Stage dispatch table — one entry per file-staged stage. Used by the stage CLI
# (scripts/run_stage.py) that the Snakemake / Nextflow / WDL wrappers call, driving the SAME core.
STAGES = {
    "extract": stage_extract,
    "qc": stage_qc,
    "classify": stage_classify,
    "report": stage_report,
    "airlock": stage_airlock,
}
