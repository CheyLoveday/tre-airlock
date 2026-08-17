"""qc — pure QC mask functions over the candidate table.

Each returns a per-row boolean array (or a flag Series). No IO, no mutation. The OFH genotypes
are released UNFILTERED, so QC is owned here: call-rate / GQ / missingness for array, the DR2
floor + per-participant genotype certainty for imputed, the consent gate, and sample-level flags.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import numpy as np
import pandas as pd

if TYPE_CHECKING:
    from .config import Config

_MISSING_GT = -1  # gt_code sentinel for a missing array genotype (./.)
_CARRIER_CODES = {"het_and_homalt": (1, 2), "het_only": (1,)}
_HET_DOSAGE_UPPER = 1.5


def array_qc_mask(candidate: pd.DataFrame, cfg: Config) -> np.ndarray:
    """Per-row: array call present, non-missing, and passing call-rate + GQ thresholds."""
    gt = candidate["array_gt_code"]
    has = gt.notna() & (gt != _MISSING_GT)
    cr_ok = candidate["array_call_rate"] >= cfg.array_call_rate_min
    gq_ok = candidate["array_gq"] >= cfg.array_gq_min
    return (has & cr_ok & gq_ok).to_numpy()


def imputed_qc_mask(candidate: pd.DataFrame, cfg: Config, variant_info: float | None) -> np.ndarray:
    """Per-row: imputed dosage present and per-participant certainty passing, gated on variant DR2.

    No DR2 or DR2 below the floor -> imputed evidence is unusable for every row (all False).
    """
    if variant_info is None or variant_info < cfg.imputed_dr2_min:
        return np.zeros(len(candidate), dtype=bool)
    has = candidate["imputed_dosage"].notna()
    gp_ok = candidate["imputed_max_gp"] >= cfg.imputed_max_gp_min
    return (has & gp_ok).to_numpy()


def gate_accounting(
    candidate: pd.DataFrame, cfg: Config, variant_info: float | None, sources: dict
) -> pd.DataFrame:
    """One boolean column per feasibility gate; internal-only transparency evidence.

    This is explanatory accounting over the same masks the classifier consumes. It does not decide
    release; it makes the configured cut-offs and per-row gate outcomes inspectable in the internal
    table and notebook views.
    """
    gt = candidate["array_gt_code"]
    has_array_gt = gt.notna() & (gt != _MISSING_GT)
    call_rate_ok = candidate["array_call_rate"] >= cfg.array_call_rate_min
    gq_ok = candidate["array_gq"] >= cfg.array_gq_min
    has_imputed_dosage = candidate["imputed_dosage"].notna()
    max_gp_ok = candidate["imputed_max_gp"] >= cfg.imputed_max_gp_min
    dosage_ok = candidate["imputed_dosage"] >= cfg.imputed_dosage_carrier_threshold
    if cfg.carrier_definition == "het_only":
        dosage_ok = dosage_ok & (candidate["imputed_dosage"] < _HET_DOSAGE_UPPER)
    dr2_ok = bool(variant_info is not None and variant_info >= cfg.imputed_dr2_min)
    consent_ok = candidate["consent_status"] == "consented"
    sex_check_ok = _as_bool(candidate["sex_check_pass"], default=False)
    kinship_ok = ~_as_bool(candidate["kinship_flag"], default=True)
    on_array = bool(sources.get("variant_on_array", False))
    on_imputed = bool(sources.get("variant_on_imputed", sources.get("use_imputed", False)))
    annotation_reliable = bool(sources.get("annotation_reliable", True))
    use_array = bool(sources.get("use_array", False))
    use_imputed = bool(sources.get("use_imputed", False))
    array_carrier = gt.isin(_CARRIER_CODES[cfg.carrier_definition])
    array_ok = on_array & annotation_reliable & use_array & has_array_gt & call_rate_ok & gq_ok
    imputed_ok = (
        on_imputed & annotation_reliable & use_imputed & dr2_ok & has_imputed_dosage & max_gp_ok
    )
    included = consent_ok & ((array_ok & array_carrier) | (imputed_ok & dosage_ok))
    return pd.DataFrame(
        {
            "on_array": on_array,
            "on_imputed": on_imputed,
            "annotation_reliable": annotation_reliable,
            "array_source_allowed": use_array,
            "imputed_source_allowed": use_imputed,
            "has_array_gt": has_array_gt,
            "call_rate_ok": call_rate_ok,
            "gq_ok": gq_ok,
            "has_imputed_dosage": has_imputed_dosage,
            "dr2_ok": dr2_ok,
            "max_gp_ok": max_gp_ok,
            "dosage_ok": dosage_ok,
            "consent_ok": consent_ok,
            "sex_check_ok": sex_check_ok,
            "kinship_ok": kinship_ok,
            "array_credible": array_ok,
            "imputed_credible": imputed_ok,
            "included_by_configured_gates": included,
        },
        index=candidate.index,
    )


def consent_mask(candidate: pd.DataFrame, cfg: Config) -> np.ndarray:
    """Hard consent gate: only consented participants may enter a recontact set (non-negotiable).

    Not config-toggleable — Config pins require_consent to True, so withdrawn carriers are always
    excluded from counts and the handoff (and recorded in the internal table for audit). cfg is
    kept for mask-signature uniformity.
    """
    return (candidate["consent_status"] == "consented").to_numpy()


def _flag_str(sex_fail: bool, kin: bool) -> str:
    parts = []
    if sex_fail:
        parts.append("sample_sex_check_fail")
    if kin:
        parts.append("related_pair")
    return ";".join(parts)


def _as_bool(series: pd.Series, default: bool) -> pd.Series:
    """Coerce a QC flag column to bool by MEANING (so string 'FALSE' is not treated as truthy).

    Unknown values take the caller's fail-closed default.
    """
    if series.dtype == bool:
        return series
    mapped = series.astype(str).str.strip().str.lower().map(
        {"true": True, "false": False, "1": True, "0": False}
    )
    return mapped.fillna(default).astype(bool)


def sample_flag_series(candidate: pd.DataFrame) -> pd.Series:
    """Per-row sample flags ('sample_sex_check_fail;related_pair'); kept, never dropped."""
    sex_fail = ~_as_bool(candidate["sex_check_pass"], default=False)
    kin = _as_bool(candidate["kinship_flag"], default=True)
    out = np.full(len(candidate), "", dtype=object)
    out[sex_fail.to_numpy()] = "sample_sex_check_fail"
    kin_arr = kin.to_numpy()
    out[kin_arr] = np.where(out[kin_arr] == "", "related_pair", out[kin_arr] + ";related_pair")
    return pd.Series(out, index=candidate.index)
