#!/usr/bin/env python3
"""run_demo.py — imperative shell for the OFH genotype-feasibility slice.

Loads the config + variant request, runs the in-memory orchestrator over the pure core (with the
Numba carrier-count kernel as a numeric reconciliation check), narrates each stage, instruments that
numeric check with psutil + timing, and reports where the governed artefacts were written.

    uv run python run_demo.py
    uv run python run_demo.py --config configs/examples/single_variant_simplified.yaml
"""

from __future__ import annotations

import argparse
import json
import os
import time
from pathlib import Path

import psutil

from ofh_feasibility import io, kernels, pipeline
from ofh_feasibility.config import load_config


def _banner(title: str) -> None:
    print("\n" + "=" * 78 + "\n  " + title + "\n" + "=" * 78)


def _time_hot_step(bundle: dict) -> None:
    """Profile the Numba array-direct reconciliation kernel with wall time + RSS."""
    proc = psutil.Process(os.getpid())
    gt, mask = bundle["gt_array"], bundle["array_mask"]
    rss0 = proc.memory_info().rss
    t0 = time.perf_counter()
    n_carrier, n_het, n_homalt = kernels.count_carriers(
        gt, mask, include_homalt=bundle.get("kernel_include_homalt", True)
    )
    dt = time.perf_counter() - t0
    rss1 = proc.memory_info().rss
    print(
        f"  numba array-direct reconciliation over {gt.size} array samples: "
        f"{dt * 1e6:.1f} µs | carriers={n_carrier} (het={n_het}, homalt={n_homalt}) | "
        f"RSS {rss1 / 1e6:.1f} MB (Δ {(rss1 - rss0) / 1e3:.0f} kB)"
    )


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run the narrated in-memory genotype-feasibility demo."
    )
    parser.add_argument(
        "--config",
        default="config.yaml",
        help="path to a full config YAML (default: config.yaml)",
    )
    parser.add_argument(
        "--request",
        default=None,
        help="optional single-variant request CSV override",
    )
    return parser


def _request_path(cfg, request_override: str | None) -> Path:
    if request_override:
        return Path(request_override)
    if cfg.request_path:
        return Path(cfg.request_path)
    return Path(cfg.data_dir) / "variant_request.csv"


def main(argv: list[str] | None = None) -> None:
    args = _build_parser().parse_args(argv)
    _banner("STAGE 0  Intake — config + variant request")
    cfg = load_config(args.config)
    request = io.read_request(_request_path(cfg, args.request))
    print(
        f"  Study {request.study_id} | {request.cpra} (build {request.build}) | "
        f"source: {request.requested_source} | carrier: {request.carrier_definition}"
    )
    print(f"  Data dir: {cfg.data_dir}  ->  results dir: {cfg.results_dir}")

    _banner("STAGES 1-9  Validate -> slice -> QC -> classify -> SDC -> report -> airlock")
    bundle = pipeline.orchestrate(cfg, request)
    sources, cells, result = bundle["sources"], bundle["cells"], bundle["result"]
    print(
        f"  Variant DR2 {sources['variant_info']} | use_array={sources['use_array']} "
        f"use_imputed={sources['use_imputed']}"
    )
    print(
        f"  Candidates classified: included={cells['total']} "
        f"(high={cells['high_confidence']}, conditional={cells['conditional']}), "
        f"excluded={cells['excluded']}, flagged={cells['flagged']}"
    )

    _banner("NUMERIC CHECK  Numba array-direct reconciliation kernel (profiled)")
    _time_hot_step(bundle)

    _banner("GOVERNED OUTPUTS  (least privilege; the Lean-emitted release.json is the sole export)")
    for label, path in bundle["paths"].items():
        print(f"  {label:18s} -> {path}")

    _banner("FEASIBILITY SUMMARY — INTERNAL-TRE-ONLY analyst note (release.json is the export)")
    print(bundle["summary"])

    _banner("DONE — COMMITTED RELEASE (the only client-facing artefact)")
    receipt = json.loads(
        (Path(cfg.results_dir) / "airlock_pending" / "release.ready").read_text()
    )
    print(f"  canonical: {Path(cfg.results_dir) / 'airlock_pending' / 'release.json'}")
    print(f"  payload_sha256: {receipt['payload']['sha256']}")
    print(f"  policy: {receipt['policy']['id']} v{receipt['policy']['version']}")
    print(
        f"  [INTERNAL] released total token {result.client_total} "
        f"(breakdown {'suppressed' if result.breakdown_suppressed else 'shown'}); "
        "everything printed above this banner is INTERNAL-TRE-ONLY analyst narration."
    )


if __name__ == "__main__":
    main()
