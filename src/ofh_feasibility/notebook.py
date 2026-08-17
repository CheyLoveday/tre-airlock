"""notebook — thin display helpers for the governed feasibility pipeline.

This module is an imperative shell for notebooks only: load config/request, call the same pipeline,
then render aggregate-only view tables. It deliberately does not duplicate analysis logic.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pandas as pd

from . import io, pipeline, views
from .config import load_config


def _maybe_display(obj: Any) -> Any:
    try:
        from IPython.display import display  # type: ignore[import-not-found]
    except Exception:
        return obj
    display(obj)
    return obj


def run(
    config_path: str | Path = "config.yaml",
    request_path: str | Path | None = None,
    *,
    data_dir: str | Path | None = None,
    results_dir: str | Path | None = None,
    source_format: str | None = None,
    audience: str = "neutral",
) -> dict:
    """Run one governed request for notebook exploration and return the full pipeline bundle."""
    cfg = load_config(config_path)
    updates: dict[str, str] = {}
    if data_dir is not None:
        updates["data_dir"] = str(data_dir)
    if results_dir is not None:
        updates["results_dir"] = str(results_dir)
    if source_format is not None:
        updates["source_format"] = source_format
    if request_path is not None:
        updates["request_path"] = str(request_path)
    cfg = cfg.model_copy(update=updates) if updates else cfg
    request_file = (
        Path(cfg.request_path) if cfg.request_path else Path(cfg.data_dir) / "variant_request.csv"
    )
    request = io.read_request(request_file)
    return pipeline.orchestrate(cfg, request, audience=audience, actor_type="notebook")


def show_funnel(bundle: dict) -> pd.DataFrame:
    """Display/return the governed candidate-to-client-count funnel."""
    return _maybe_display(views.funnel_table(bundle))


def show_sdc(bundle: dict) -> pd.DataFrame:
    """Display/return the release-gate and SDC view."""
    return _maybe_display(views.sdc_table(bundle["result"], bundle["release_candidate"]))


def show_sources(bundle: dict) -> pd.DataFrame:
    """Display/return source availability and evidence-use decisions."""
    return _maybe_display(views.source_decision_table(bundle))


def show_summary(bundle: dict) -> str:
    """Display/return the INTERNAL analyst note (the client artefact is the Lean release.json)."""
    return _maybe_display(bundle["summary"])


def report(bundle: dict) -> dict[str, Any]:
    """Return the aggregate notebook report object without participant-level tables."""
    return {
        "funnel": views.funnel_table(bundle),
        "sources": views.source_decision_table(bundle),
        "classification": views.classification_table(bundle),
        "gate_accounting": views.gate_accounting_table(bundle),
        "qc": views.qc_breakdown_table(bundle),
        "sdc": views.sdc_table(bundle["result"], bundle["release_candidate"]),
        "governance": views.governance_view(bundle),
        "summary": bundle["summary"],
    }
