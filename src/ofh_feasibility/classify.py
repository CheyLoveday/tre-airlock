"""classify — pure carrier logic: consent gate, evidence combination, confidence, decision.

The governed heart of the pipeline. Combines array vs imputed evidence with the per-row QC masks
and the (hard) consent gate to produce, for each candidate, a decision (included | excluded), a
reason, a confidence tier (high | conditional) and the evidence source — mirroring the proven
reference logic. Pure: no IO, no mutation, deterministic.

Governance invariant: a genotypic carrier who has withdrawn consent is decision=excluded with
reason=consent_withdrawn (auditable in the internal table) and never appears as included.
"""
from __future__ import annotations

from typing import TYPE_CHECKING

import numpy as np
import pandas as pd

if TYPE_CHECKING:
    from .config import Config

_MISSING_GT = -1
_CARRIER_CODES = {"het_and_homalt": (1, 2), "het_only": (1,)}
_HET_DOSAGE_UPPER = 1.5  # imputed het_only: dosage at/above this looks hom-alt, not het
_UNKNOWN_ANCESTRY = "UNKNOWN"

# Columns carried from the candidate table into the classified output (full provenance).
_PROVENANCE = [
    "participant_id", "pseudo_id", "consent_status", "sex", "ancestry_stub",
    "array_gt_code", "array_gq", "array_call_rate", "imputed_dosage", "imputed_max_gp",
    "on_array", "on_imputed", "annotation_reliable", "array_source_allowed",
    "imputed_source_allowed", "has_array_gt", "call_rate_ok", "gq_ok", "has_imputed_dosage",
    "dr2_ok", "max_gp_ok", "dosage_ok", "consent_ok", "sex_check_ok", "kinship_ok",
    "array_credible", "imputed_credible", "included_by_configured_gates",
]


def _source_str(ev_array: bool, ev_imp: bool) -> str:
    parts = []
    if ev_array:
        parts.append("array")
    if ev_imp:
        parts.append("imputed")
    return "+".join(parts) if parts else "none"


def _reason_str(gt_code, call_rate, gq, max_gp, array_alt, array_ok, imputed_alt, consent_ok, cfg):
    """Per-candidate exclusion/QC provenance string (empty for a cleanly included carrier)."""
    parts = []
    # record a missing array genotype for any row that has an array record (gt_code == -1),
    # independent of array_alt (which is False for a missing call) so provenance isn't lost.
    if gt_code == _MISSING_GT:
        parts.append("array_genotype_missing")
    if array_alt and not array_ok:
        if call_rate < cfg.array_call_rate_min:
            parts.append(f"array_call_rate<{cfg.array_call_rate_min}")
        elif gq < cfg.array_gq_min:
            parts.append(f"array_GQ<{cfg.array_gq_min}")
    if imputed_alt and max_gp < cfg.imputed_max_gp_min:  # NaN < x is False -> no spurious reason
        parts.append(f"imputed_max_gp<{cfg.imputed_max_gp_min}")
    if not consent_ok:
        parts.append("consent_withdrawn")
    return ";".join(parts)


def _imputed_alt(dosage: pd.Series, cfg: Config) -> np.ndarray:
    """Imputed carrier indicator. For het_only, exclude the hom-alt dosage range (~2.0); proper
    zygosity from dosage alone is imperfect — genotype probabilities (not in the mock) would be
    exact. See docs/reference/missing-data.md."""
    carrier = dosage >= cfg.imputed_dosage_carrier_threshold
    if cfg.carrier_definition == "het_only":
        carrier = carrier & (dosage < _HET_DOSAGE_UPPER)
    return carrier.to_numpy()


def classify_carriers(
    candidate: pd.DataFrame,
    array_mask: np.ndarray,
    imputed_mask: np.ndarray,
    consent_mask: np.ndarray,
    flags: pd.Series,
    cfg: Config,
    variant_info: float | None,
) -> pd.DataFrame:
    """Classify each candidate carrier: source, confidence, decision, reason (full provenance)."""
    imp_high = variant_info is not None and variant_info >= cfg.imputed_dr2_high_confidence
    carrier_codes = _CARRIER_CODES[cfg.carrier_definition]

    array_alt = candidate["array_gt_code"].isin(carrier_codes).to_numpy()
    imputed_alt = _imputed_alt(candidate["imputed_dosage"], cfg)
    array_ok = np.asarray(array_mask, dtype=bool)
    consent_ok = np.asarray(consent_mask, dtype=bool)

    ev_array = array_alt & array_ok
    ev_imp = imputed_alt & np.asarray(imputed_mask, dtype=bool)
    cand_mask = array_alt | imputed_alt          # alt evidence by any source -> a candidate
    any_evidence = ev_array | ev_imp
    included = cand_mask & consent_ok & any_evidence
    high = ev_array | (ev_imp & imp_high)

    decision = np.where(included[cand_mask], "included", "excluded")
    confidence = np.where(
        included[cand_mask], np.where(high[cand_mask], "high", "conditional"), "NA"
    )
    # evidence tier (Wave 3): the array-direct vs imputed model, finer than `confidence`
    # (which merges array-direct and high-DR2 imputed). array_direct = directly-typed evidence;
    # imputed_high = imputed-only with high DR2; imputed_conditional = imputed-only, moderate DR2.
    imputed_tier = np.where(imp_high, "imputed_high", "imputed_conditional")
    evidence_priority = np.where(
        ~included[cand_mask],
        "NA",
        np.where(ev_array[cand_mask], "array_direct", imputed_tier),
    )
    candidate_carriers = candidate.loc[cand_mask]
    source = [
        _source_str(a, i) for a, i in zip(ev_array[cand_mask], ev_imp[cand_mask], strict=True)
    ]
    reason = [
        _reason_str(gt, cr, gq, mg, aa, ok, ia, ck, cfg)
        for gt, cr, gq, mg, aa, ok, ia, ck in zip(
            candidate_carriers["array_gt_code"].to_numpy(),
            candidate_carriers["array_call_rate"].to_numpy(),
            candidate_carriers["array_gq"].to_numpy(),
            candidate_carriers["imputed_max_gp"].to_numpy(),
            array_alt[cand_mask],
            array_ok[cand_mask],
            imputed_alt[cand_mask],
            consent_ok[cand_mask],
            strict=True,
        )
    ]

    out = candidate_carriers[[c for c in _PROVENANCE if c in candidate.columns]].copy()
    out["source"] = source
    out["confidence"] = confidence
    out["evidence_priority"] = evidence_priority
    out["decision"] = decision
    out["reason"] = reason
    out["flags"] = flags.to_numpy()[cand_mask]
    out["variant_info"] = variant_info
    return out.reset_index(drop=True)


def count_cells(classified: pd.DataFrame) -> dict:
    """Aggregate the cells report + SDC consume: high / conditional / total / excluded / flagged."""
    included = classified[classified["decision"] == "included"]
    return {
        "high_confidence": int((included["confidence"] == "high").sum()),
        "conditional": int((included["confidence"] == "conditional").sum()),
        "total": int(len(included)),
        "excluded": int((classified["decision"] == "excluded").sum()),
        "flagged": int((included["flags"] != "").sum()),
    }


def project_cells(
    classified: pd.DataFrame,
    cfg: Config,
    *,
    variant_info: float | None = None,
    imputed_dr2_min: float | None = None,
    imputed_dr2_high_confidence: float | None = None,
    imputed_max_gp_min: float | None = None,
    array_call_rate_min: float | None = None,
    array_gq_min: float | None = None,
    imputed_info_min: float | None = None,
    imputed_info_high_confidence: float | None = None,
) -> dict:
    """Late-bind the count projection from retained evidence and configured thresholds.

    Classification keeps all rows with carrier evidence. This projection recomputes which retained
    carriers count under a selected quality policy, so threshold movements do not require rerunning
    extract/QC or losing the evidence trail.
    """
    if classified.empty:
        return {"high_confidence": 0, "conditional": 0, "total": 0, "excluded": 0, "flagged": 0}

    if (
        imputed_info_min is not None
        and imputed_dr2_min is not None
        and imputed_info_min != imputed_dr2_min
    ):
        raise ValueError("set only one of imputed_info_min or imputed_dr2_min")
    if (
        imputed_info_high_confidence is not None
        and imputed_dr2_high_confidence is not None
        and imputed_info_high_confidence != imputed_dr2_high_confidence
    ):
        raise ValueError(
            "set only one of imputed_info_high_confidence or imputed_dr2_high_confidence"
        )

    info = _project_variant_info(classified, variant_info)
    dr2_min = imputed_dr2_min if imputed_dr2_min is not None else imputed_info_min
    dr2_high = (
        imputed_dr2_high_confidence
        if imputed_dr2_high_confidence is not None
        else imputed_info_high_confidence
    )
    info_min = cfg.imputed_dr2_min if dr2_min is None else dr2_min
    high_cut = (
        cfg.imputed_dr2_high_confidence
        if dr2_high is None
        else dr2_high
    )
    gp_min = cfg.imputed_max_gp_min if imputed_max_gp_min is None else imputed_max_gp_min
    cr_min = cfg.array_call_rate_min if array_call_rate_min is None else array_call_rate_min
    gq_min = cfg.array_gq_min if array_gq_min is None else array_gq_min

    carrier_codes = _CARRIER_CODES[cfg.carrier_definition]
    array_gt = classified["array_gt_code"]
    array_alt = array_gt.isin(carrier_codes)
    has_array_gt = array_gt.notna() & (array_gt != _MISSING_GT)
    array_ok = (
        _bool_col(classified, "array_source_allowed", _bool_col(classified, "on_array", True))
        & _bool_col(classified, "annotation_reliable", True)
        & has_array_gt
        & (classified["array_call_rate"] >= cr_min)
        & (classified["array_gq"] >= gq_min)
    )

    dosage = classified["imputed_dosage"]
    imputed_alt = dosage >= cfg.imputed_dosage_carrier_threshold
    if cfg.carrier_definition == "het_only":
        imputed_alt = imputed_alt & (dosage < _HET_DOSAGE_UPPER)
    imputed_ok = (
        _bool_col(
            classified, "imputed_source_allowed", _bool_col(classified, "on_imputed", True)
        )
        & _bool_col(classified, "annotation_reliable", True)
        & bool(info is not None and info >= info_min)
        & dosage.notna()
        & (classified["imputed_max_gp"] >= gp_min)
    )

    ev_array = array_alt & array_ok
    ev_imputed = imputed_alt & imputed_ok
    consent_ok = _bool_col(
        classified,
        "consent_ok",
        classified["consent_status"].astype(str).str.lower().eq("consented"),
    )
    included = consent_ok & (ev_array | ev_imputed)
    high = ev_array | (ev_imputed & bool(info is not None and info >= high_cut))
    flags = classified["flags"].fillna("").astype(str) if "flags" in classified else ""
    return {
        "high_confidence": int((included & high).sum()),
        "conditional": int((included & ~high).sum()),
        "total": int(included.sum()),
        "excluded": int((~included).sum()),
        "flagged": int((included & (flags != "")).sum()),
    }


def _project_variant_info(classified: pd.DataFrame, variant_info: float | None) -> float | None:
    if variant_info is not None:
        return float(variant_info)
    if "variant_info" not in classified:
        return None
    vals = pd.to_numeric(classified["variant_info"], errors="coerce").dropna()
    return None if vals.empty else float(vals.iloc[0])


def _bool_col(classified: pd.DataFrame, column: str, default) -> pd.Series:
    if isinstance(default, pd.Series):
        fallback = default.reindex(classified.index)
    else:
        fallback = pd.Series(default, index=classified.index)
    if column not in classified:
        return _coerce_bool_series(fallback, default=False)
    return _coerce_bool_series(classified[column].fillna(fallback), default=False)


def _coerce_bool_series(series: pd.Series, default: bool) -> pd.Series:
    if series.dtype == bool:
        return series
    text = series.astype(str).str.strip().str.upper()
    out = pd.Series(default, index=series.index)
    out[text.isin({"TRUE", "T", "YES", "Y", "1"})] = True
    out[text.isin({"FALSE", "F", "NO", "N", "0"})] = False
    return out


def count_by_ancestry(classified: pd.DataFrame) -> dict:
    """Included-carrier counts per ancestry group (the strata the per-group SDC then controls)."""
    included = classified[classified["decision"] == "included"]
    groups = included["ancestry_stub"].map(_ancestry_stratum)
    return {str(group): int(n) for group, n in groups.groupby(groups, sort=True).size().items()}


def _ancestry_stratum(value) -> str:
    """Map missing/blank ancestry to a real releasable stratum, never to a dropped groupby key."""
    if pd.isna(value):
        return _UNKNOWN_ANCESTRY
    text = str(value).strip()
    return text if text else _UNKNOWN_ANCESTRY
