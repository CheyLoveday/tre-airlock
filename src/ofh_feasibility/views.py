"""views — pure, aggregate-only display tables for notebooks and review.

These builders do not read files, rerun analysis, or widen disclosure. They reshape the already
governed pipeline bundle into small tables a reviewer can scan in a notebook or one-page handover.
Participant-level identifiers stay in the internal artefacts and are never returned here.
"""

from __future__ import annotations

from typing import Any

import pandas as pd

from .models import FeasibilityResult, ReleaseCandidate

_ID_COLUMNS = {"participant_id", "pseudo_id"}


def _classified(bundle: dict[str, Any]) -> pd.DataFrame:
    df = bundle.get("classified")
    if not isinstance(df, pd.DataFrame):
        raise ValueError("bundle does not contain a classified DataFrame")
    return df


def _count_rows(df: pd.DataFrame, cols: list[str]) -> pd.DataFrame:
    rows = (
        df.groupby(cols, dropna=False)
        .size()
        .reset_index(name="count")
        .sort_values(["count", *cols], ascending=[False, *([True] * len(cols))])
        .reset_index(drop=True)
    )
    forbidden = _ID_COLUMNS.intersection(rows.columns)
    if forbidden:
        raise ValueError(f"view would expose identifier columns: {sorted(forbidden)}")
    return rows


def funnel_table(bundle: dict[str, Any]) -> pd.DataFrame:
    """Return the high-level candidate -> governed-count funnel."""
    classified = _classified(bundle)
    cells = bundle["cells"]
    result: FeasibilityResult = bundle["result"]
    return pd.DataFrame(
        [
            {
                "step": "Candidate rows",
                "count": int(len(classified)),
                "client_visible": False,
                "note": "Internal slice after request/manifest validation",
            },
            {
                "step": "Excluded before recontact",
                "count": int(cells["excluded"]),
                "client_visible": False,
                "note": "Consent/QC/source failures retained internally as reason codes",
            },
            {
                "step": "Included genotype carriers",
                "count": int(cells["total"]),
                "client_visible": False,
                "note": "Internal exact count before disclosure control",
            },
            {
                "step": "Client count",
                "count": result.client_total,
                "client_visible": True,
                "note": "SDC-applied token in the airlock export candidate",
            },
        ]
    )


def source_decision_table(bundle: dict[str, Any]) -> pd.DataFrame:
    """Summarise source availability and which evidence streams were allowed for the request."""
    sources = bundle["sources"]
    result: FeasibilityResult = bundle["result"]
    return pd.DataFrame(
        [
            {"check": "Requested source", "value": sources.get("requested_source", "n/a")},
            {"check": "Variant on array", "value": bool(result.variant_on_array)},
            {"check": "Array evidence used", "value": bool(sources.get("use_array"))},
            {"check": "Imputed evidence used", "value": bool(sources.get("use_imputed"))},
            {
                "check": "Imputed DR2",
                "value": sources.get("variant_info") if result.variant_on_imputed else "not used",
            },
        ]
    )


def qc_breakdown_table(bundle: dict[str, Any]) -> pd.DataFrame:
    """Aggregate decision/reason counts from the internal classification table."""
    classified = _classified(bundle).copy()
    reason = classified["reason"].replace("", "included")
    tmp = pd.DataFrame({"decision": classified["decision"], "reason": reason})
    return _count_rows(tmp, ["decision", "reason"])


def classification_table(bundle: dict[str, Any]) -> pd.DataFrame:
    """Aggregate evidence/confidence counts without participant-level columns."""
    classified = _classified(bundle)
    tmp = classified[["decision", "confidence", "evidence_priority"]].copy()
    return _count_rows(tmp, ["decision", "confidence", "evidence_priority"])


def gate_accounting_table(bundle: dict[str, Any]) -> pd.DataFrame:
    """Aggregate pass counts for each configured gate; participant rows stay internal."""
    accounting = bundle.get("accounting")
    if not isinstance(accounting, pd.DataFrame):
        classified = _classified(bundle)
        gate_cols = [c for c in classified.columns if c.endswith("_ok") or c.endswith("_credible")]
        accounting = classified[gate_cols]
    rows = []
    for col in accounting.columns:
        if accounting[col].dtype == bool:
            rows.append(
                {
                    "gate": col,
                    "passing_rows": int(accounting[col].sum()),
                    "total_rows": int(len(accounting)),
                }
            )
    return pd.DataFrame(rows)


def sdc_table(result: FeasibilityResult, candidate: ReleaseCandidate) -> pd.DataFrame:
    """Show exactly what the release gate authorised."""
    return pd.DataFrame(
        [
            {"field": "client_total", "value": candidate.client_total},
            {"field": "breakdown_suppressed", "value": bool(candidate.breakdown_suppressed)},
            {"field": "reported_cells", "value": len(candidate.reported_cells)},
            {"field": "min_cell", "value": int(candidate.min_cell)},
            {"field": "round_to", "value": int(candidate.round_to)},
            {"field": "ancestry_suppressed", "value": bool(result.ancestry_suppressed)},
        ]
    )


def governance_view(bundle: dict[str, Any]) -> dict[str, Any]:
    """Small aggregate-only governance summary for notebooks/reviewer pages."""
    candidate: ReleaseCandidate = bundle["release_candidate"]
    manifest = bundle["airlock_manifest"]
    exported = [f for f in manifest["files"] if f.get("export_to_client")]
    return {
        "release_candidate": candidate.model_dump(),
        "airlock_export_files": tuple(f["file"] for f in exported),
        "single_export": len(exported) == 1,
        # Derived from the manifest, not asserted: True if any exported file is not the
        # sanctioned aggregate candidate (an internal/participant-level artefact in the export set).
        "participant_level_outputs_exported": any(
            f.get("classification") != "AIRLOCK-EXPORT-CANDIDATE" for f in exported
        ),
        "audit_actor_type": bundle.get("audit_event", {}).get("actor_type"),
    }
