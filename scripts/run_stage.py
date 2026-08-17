#!/usr/bin/env python3
"""Run a single pipeline stage by name — the entrypoint the Nextflow/WDL (and Snakemake) wrappers
call, so every orchestrator drives the SAME pure core.

    uv run python scripts/run_stage.py <extract|qc|classify|report|airlock> [config.yaml]
"""
import logging
import sys

from ofh_feasibility.config import load_config
from ofh_feasibility.pipeline import STAGES


def main() -> None:
    if len(sys.argv) < 2 or sys.argv[1] not in STAGES:
        sys.exit(f"usage: run_stage.py <{'|'.join(STAGES)}> [config.yaml]")
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    cfg = load_config(sys.argv[2] if len(sys.argv) > 2 else "config.yaml")
    STAGES[sys.argv[1]](cfg)


if __name__ == "__main__":
    main()
