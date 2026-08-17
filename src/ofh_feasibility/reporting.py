"""reporting — pure builders for the governed outputs (least-privilege tiers).

Builds the structured FeasibilityResult, the INTERNAL carrier table (participant IDs + full
provenance), the pseudonymised epi handoff (no participant IDs), and the SDC-applied
feasibility note (human-readable; INTERNAL — the airlock export is the Lean-rendered
release payload). The note follows the decision-ready
service-note structure: short at the top, deep underneath, ending in an
explicit go / no-go / go-with-caveats recommendation. Pure; no IO.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Literal

import numpy as np
import pandas as pd

from . import classify, qc
from .models import FeasibilityResult
from .sdc import round_to

_AUTOSOMES = {str(c) for c in range(1, 23)}
_Z95 = 1.959963985  # standard normal quantile for a 95% interval
RECRUITABILITY_RESPONSE_RATES = (0.25, 0.50)

if TYPE_CHECKING:
    from .config import Config
    from .models import BatchRequest, FinalResult, ReleaseCandidate, VariantRequest

Audience = Literal["neutral", "research", "commercial"]

# Internal carrier table column order (participant-level provenance; INTERNAL-TRE-ONLY).
INTERNAL_COLUMNS = [
    "participant_id",
    "pseudo_id",
    "consent_status",
    "sex",
    "ancestry_stub",
    "source",
    "array_gt_code",
    "array_gq",
    "array_call_rate",
    "imputed_dosage",
    "imputed_max_gp",
    "on_array",
    "on_imputed",
    "annotation_reliable",
    "array_source_allowed",
    "imputed_source_allowed",
    "has_array_gt",
    "call_rate_ok",
    "gq_ok",
    "has_imputed_dosage",
    "dr2_ok",
    "max_gp_ok",
    "dosage_ok",
    "consent_ok",
    "sex_check_ok",
    "kinship_ok",
    "array_credible",
    "imputed_credible",
    "included_by_configured_gates",
    "variant_info",
    "confidence",
    "evidence_priority",
    "decision",
    "reason",
    "flags",
]


def build_result(
    request: VariantRequest,
    cells: dict,
    sdc: dict,
    variant_info: float | None,
    cfg: Config,
    ancestry: dict | None = None,
    identifiability_caveats: tuple[str, ...] = (),
    variant_on_array: bool = False,
    variant_on_imputed: bool = True,
) -> FeasibilityResult:
    """Assemble the structured FeasibilityResult (counts + SDC-applied client figure + caveats).

    identifiability_caveats are the variant pre-flight notes (build reference-match, normalization,
    strand resolution for palindromic SNPs); they lead the limitations as feasibility gate #1.
    """
    ancestry = ancestry or {"suppressed": False, "reported": {}}
    assumptions = (
        f"Carrier definition: {request.carrier_definition} (>=1 alt allele '{request.alt}').",
        f"Array QC: call_rate >= {cfg.array_call_rate_min}, GQ >= {cfg.array_gq_min}.",
        "Imputed evidence is used only when the exact CPRA is present in the imputed resource, "
        f"variant dosage r2 (DR2) >= {cfg.imputed_dr2_min}, and per-participant max genotype "
        f"probability >= {cfg.imputed_max_gp_min}.",
        "Consent gate: withdrawn participants excluded from any recontact set.",
    )
    limitations = (
        *identifiability_caveats,
        *_indel_imputation_caveat(request, variant_on_array),
        _dr2_limitation(variant_info, cfg, variant_on_imputed),
        "Genotype feasibility only — ICD-10 phenotype eligibility is assessed downstream by "
        "epidemiology and will reduce the count.",
        "Sample-level flags (sex-check, relatedness) are recorded in the internal table for "
        "review, not silently dropped.",
        "Counts are a feasibility estimate for recruitment planning, not a final invitation list.",
    )
    return FeasibilityResult(
        study_id=request.study_id,
        cpra=request.cpra,
        total_included=cells["total"],
        high_confidence=cells["high_confidence"],
        conditional=cells["conditional"],
        excluded=cells["excluded"],
        flagged=cells["flagged"],
        client_total=sdc["client_total"],
        breakdown_suppressed=sdc["breakdown_suppressed"],
        assumptions=assumptions,
        limitations=limitations,
        ancestry_suppressed=ancestry["suppressed"],
        ancestry_breakdown=tuple(sorted(ancestry["reported"].items())),
        variant_on_array=variant_on_array,
        variant_on_imputed=variant_on_imputed,
    )


def _dr2_limitation(variant_info: float | None, cfg: Config, variant_on_imputed: bool) -> str:
    if not variant_on_imputed:
        return (
            "Exact CPRA is absent from the imputed public variant list; imputed evidence is not "
            "used for this variant."
        )
    if variant_info is None:
        return "Imputed dosage r2 (DR2) is unavailable; imputed evidence is not counted."
    if variant_info < cfg.imputed_dr2_min:
        return (
            f"Imputed dosage r2 (DR2) = {variant_info} (below configured floor "
            f"{cfg.imputed_dr2_min}); imputed evidence is not counted without review or "
            "confirmatory genotyping."
        )
    tier = "high" if variant_info >= cfg.imputed_dr2_high_confidence else "moderate"
    return (
        f"Imputed dosage r2 (DR2) = {variant_info} ({tier}); imputed-only carriers are conditional "
        "and benefit from confirmatory genotyping."
    )


def _indel_imputation_caveat(request: VariantRequest, variant_on_array: bool) -> tuple[str, ...]:
    if variant_on_array or len(request.ref) == len(request.alt):
        return ()
    return (
        "Variant is an indel not directly typed on the array; short frameshift indels can impute "
        "unreliably, so confirm with a targeted assay before recall.",
    )


def _final_recommendation(final_result: FinalResult) -> str:
    if final_result.post_phenotype_eligible == 0:
        return "NO-GO — no phenotype-eligible carriers remain after ICD-10 assessment."
    if final_result.eligible_suppressed:
        return (
            "GO WITH CAVEATS — eligible carriers exist but the count is below the "
            "disclosure-control minimum; treat as a small pool."
        )
    return "GO — a phenotype-eligible carrier pool exists; proceed to recruitment planning."


def build_final_summary(final_result: FinalResult, request: VariantRequest, cfg: Config) -> str:
    """FINAL (post-phenotype) analyst summary, SDC-applied; INTERNAL (release.json is the export).

    Distinguishes explicitly between the GENOTYPE CEILING (upper bound) and the POST-PHENOTYPE
    ELIGIBLE count (the figure for recruitment), so the client always knows which number is which.
    """
    return "\n".join(
        [
            "OUR FUTURE HEALTH — FINAL POST-PHENOTYPE FEASIBILITY SUMMARY "
            "(INTERNAL ANALYST NOTE, SDC)",
            "=" * 78,
            f"1. REQUEST          {request.study_id} | purpose: {request.purpose}",
            f"2. VARIANT          {request.cpra} (build {request.build}); ref {request.ref} / "
            f"alt {request.alt}; carrier = {request.carrier_definition}",
            "3. GENOTYPE FEASIBILITY (upper bound / ceiling) — disclosure-controlled",
            f"  Genotype carrier ceiling: {final_result.client_genotype_ceiling}   "
            "[consented, QC-passed carriers; an UPPER BOUND before phenotype]",
            "4. EPIDEMIOLOGY REVIEW (ICD-10 phenotype eligibility — assessed by epidemiology)",
            f"  Phenotype definition: {final_result.phenotype_definition_id} | ICD-10 code-set: "
            f"{final_result.icd10_codeset_label} {final_result.icd10_codeset_version}",
            f"  Returned + signed off by {final_result.epi_reviewer} at "
            f"{final_result.epi_timestamp}",
            "5. POST-PHENOTYPE ELIGIBLE CARRIERS (the FINAL figure) — disclosure-controlled",
            f"  Eligible count: {final_result.client_eligible}   "
            f"[after ICD-10 assessment; rounded to nearest {cfg.sdc_round_to}; SDC applied]",
            "6. DISCLOSURE CONTROL",
            f"  - min cell size {cfg.sdc_min_cell}, rounding to nearest {cfg.sdc_round_to}; "
            "applied to both the ceiling and the eligible count.",
            "  - The canonical airlock export is the Lean-authorised release.json payload; "
            "this note and all participant-level tables remain internal.",
            "7. CAVEATS",
            _bullets(final_result.caveats),
            "-" * 78,
            f"RECOMMENDATION: {_final_recommendation(final_result)}",
        ]
    )


def build_batch_summary(batch, combined: dict) -> str:
    """INTERNAL combined feasibility note for a multi-variant (composite-profile) request."""
    lines = [
        "OUR FUTURE HEALTH — COMBINED (MULTI-VARIANT) FEASIBILITY SUMMARY (SDC-APPLIED)",
        "=" * 78,
        f"Study: {batch.study_id} | purpose: {batch.purpose}",
        f"Variants assessed: {len(batch.variants)}",
        "",
        f"COMBINED — participants carrying >=1 variant: {combined['combined_client_total']}",
        "  [union across variants; the recall set for a composite risk profile; SDC applied]",
    ]
    if combined.get("breakdown_suppressed", True):
        lines += [
            "",
            "PER-VARIANT / OVERLAP BREAKDOWN: SUPPRESSED",
            "  Per-variant counts and overlap are withheld because they can reveal suppressed",
            "  intersections or complements by differencing against the union total.",
        ]
    else:
        lines += ["", "PER-VARIANT (consented, QC-passed carriers, SDC-applied):"]
        for v in batch.variants:
            lines.append(f"  {v.cpra}: {combined['per_variant'][v.cpra]['client']}")
        if len(batch.variants) > 1:
            lines.append(f"  of which carry >=2 variants: {combined['overlap_client']}")
    return "\n".join(lines)


def _wilson(x: int, n: int) -> tuple[float, float, float]:
    """Point AF + Wilson score 95% interval for x alt alleles out of n callable alleles."""
    if n == 0:
        return (float("nan"), float("nan"), float("nan"))
    p = x / n
    denom = 1 + _Z95**2 / n
    center = (p + _Z95**2 / (2 * n)) / denom
    half = (_Z95 / denom) * np.sqrt(p * (1 - p) / n + _Z95**2 / (4 * n**2))
    return (round(p, 5), round(max(0.0, center - half), 5), round(min(1.0, center + half), 5))


def _af_stratum(g: pd.DataFrame, cfg: Config) -> dict:
    """Per-stratum AF from QC-passing TYPED calls; suppressed below the (internal) min-cell rule."""
    callable_samples = int(g["array_ok"].sum())
    if callable_samples == 0:
        return {"n_callable_samples": 0, "suppressed": True, "reason": "no callable typed samples"}
    if callable_samples < cfg.sdc_min_cell:
        return {
            "n_callable_samples": callable_samples,
            "suppressed": True,
            "reason": "below min cell (internal discipline)",
        }
    alt = int(g.loc[g["array_ok"], "array_gt_code"].sum())  # gt 1/2 among QC-pass (no -1)
    callable_alleles = 2 * callable_samples
    af, lo, hi = _wilson(alt, callable_alleles)
    return {
        "n_callable_samples": callable_samples,
        "alt_alleles": alt,
        "callable_alleles": callable_alleles,
        "af": af,
        "ci95_low": lo,
        "ci95_high": hi,
        "suppressed": False,
    }


def _typed_vs_imputed(df: pd.DataFrame, cfg: Config) -> dict:
    """Discordance cross-check: typed vs imputed carrier call where both are available."""
    both = df[df["array_ok"] & df["imputed_dosage"].notna()]
    typed = both["array_gt_code"] >= 1
    imputed = both["imputed_dosage"] >= cfg.imputed_dosage_carrier_threshold
    return {"n_compared": int(len(both)), "discordant_calls": int((typed != imputed).sum())}


def _bootstrap_af_ci(
    df: pd.DataFrame,
    cfg: Config,
    n_boot: int = 1000,
    max_draw_bytes: int = 8 * 1024 * 1024,
) -> list | None:
    """Seeded (42) bootstrap 95% interval for the overall typed AF (a stability cross-check)."""
    gt = df.loc[df["array_ok"], "array_gt_code"].to_numpy(dtype=np.int8, copy=False)
    if len(gt) < cfg.sdc_min_cell:
        return None
    rng = np.random.default_rng(42)
    chunk = max(1, min(n_boot, max_draw_bytes // max(1, len(gt) * gt.dtype.itemsize)))
    sums = np.empty(n_boot, dtype=np.int64)
    for start in range(0, n_boot, chunk):
        stop = min(n_boot, start + chunk)
        sampled = rng.choice(gt, size=(stop - start, len(gt)), replace=True)
        sums[start:stop] = sampled.sum(axis=1)
    afs = sums / (2 * len(gt))
    lo, hi = np.percentile(afs, [2.5, 97.5])
    return [round(float(lo), 5), round(float(hi), 5)]


def _kinship_stability(df: pd.DataFrame, cfg: Config) -> dict:
    """Full vs unrelated-only AF (+ bootstrap CI): does the estimate hold without related pairs?"""
    related = qc._as_bool(df["kinship_flag"], default=True)
    full_af = _af_stratum(df, cfg).get("af")
    unrelated_af = _af_stratum(df[~related], cfg).get("af")
    delta = None
    note = "AF stability could not be assessed after removing related samples"
    if full_af is not None and unrelated_af is not None:
        delta = round(abs(full_af - unrelated_af), 5)
        if delta == 0:
            note = "AF unchanged when related samples are removed"
        else:
            note = (
                f"AF differs by {delta:.5f} when related samples are removed; "
                "review for possible clustering"
            )
    return {
        "full_af": full_af,
        "unrelated_only_af": unrelated_af,
        "af_delta": delta,
        "n_related_excluded": int(related.sum()),
        "bootstrap_ci95": _bootstrap_af_ci(df, cfg),
        "note": note,
    }


def build_frequency_control(
    candidate: pd.DataFrame, array_mask, request: VariantRequest, cfg: Config
) -> dict:
    """INTERNAL-ONLY variant-frequency control view: per-stratum AF + Wilson 95% intervals, a
    kinship-cluster stability cross-check, and a ploidy guard. A QC/credibility control with its own
    min-cell discipline (sub-min strata suppressed even internally); never airlock-exported."""
    df = candidate.copy()
    df["array_ok"] = np.asarray(array_mask, dtype=bool)
    out = {
        "classification": "INTERNAL-TRE-ONLY",
        "exportable": False,
        "cpra": request.cpra,
        "min_cell": cfg.sdc_min_cell,
        "quality_cutoffs": build_quality_cutoff_facts(cfg),
        "self_reported_missing": {
            "sex": int(df["sex"].isna().sum()),
            "ancestry": int(df["ancestry_stub"].isna().sum()),
        },
    }
    gate_cols = [
        "on_array",
        "on_imputed",
        "annotation_reliable",
        "array_source_allowed",
        "imputed_source_allowed",
        "has_array_gt",
        "call_rate_ok",
        "gq_ok",
        "has_imputed_dosage",
        "dr2_ok",
        "max_gp_ok",
        "dosage_ok",
        "consent_ok",
        "sex_check_ok",
        "kinship_ok",
        "array_credible",
        "imputed_credible",
        "included_by_configured_gates",
    ]
    present_gate_cols = [col for col in gate_cols if col in df.columns]
    if present_gate_cols:
        out["gate_accounting_summary"] = {
            col: int(df[col].astype(bool).sum()) for col in present_gate_cols
        }
    if request.chrom not in _AUTOSOMES:  # ploidy guard: diploid AF is invalid off the autosomes
        out["ploidy_guard"] = True
        out["note"] = (
            f"chrom {request.chrom} is non-autosomal; diploid AF not computed (ploidy guard)"
        )
        return out
    out["ploidy_guard"] = False
    out["overall"] = _af_stratum(df, cfg)
    out["by_sex"] = {str(s): _af_stratum(g, cfg) for s, g in df.groupby("sex")}
    out["by_ancestry"] = {str(a): _af_stratum(g, cfg) for a, g in df.groupby("ancestry_stub")}
    out["typed_vs_imputed"] = _typed_vs_imputed(df, cfg)
    out["kinship_stability"] = _kinship_stability(df, cfg)
    return out


def build_internal_table(classified: pd.DataFrame) -> pd.DataFrame:
    """INTERNAL-TRE-ONLY: every candidate with participant IDs + full QC/decision provenance."""
    cols = [c for c in INTERNAL_COLUMNS if c in classified.columns]
    return classified[cols].copy()


def _caveat(confidence: str, flags: str, variant_info) -> str:
    parts = []
    if confidence == "conditional":
        parts.append(f"imputed-supported, DR2={variant_info} (moderate)")
    if flags:
        parts.append(flags)
    return "; ".join(parts)


def build_epi_handoff(classified: pd.DataFrame) -> pd.DataFrame:
    """Pseudonymised handoff for ICD-10 phenotype eligibility: included carriers only, no IDs."""
    incl = classified[classified["decision"] == "included"]
    return pd.DataFrame(
        {
            "pseudo_id": incl["pseudo_id"].to_numpy(),
            "carrier_status": "carrier",
            "source": incl["source"].to_numpy(),
            "confidence": incl["confidence"].to_numpy(),
            "evidence_priority": incl["evidence_priority"].to_numpy(),  # typed > imputed tier
            "caveat": [
                _caveat(c, f, vi)
                for c, f, vi in zip(
                    incl["confidence"], incl["flags"], incl["variant_info"], strict=True
                )
            ],
        }
    )


def _recommendation(result: FeasibilityResult) -> str:
    if result.total_included == 0:
        return "NO-GO — no eligible consented carriers identified at the applied QC thresholds."
    caveats = []
    if result.conditional > 0:
        caveats.append("part of the pool is imputed-supported (conditional confidence)")
    if result.breakdown_suppressed:
        caveats.append("the subgroup breakdown is suppressed under disclosure control")
    if result.client_total.startswith("<"):
        caveats.append("the total is below the disclosure-control minimum cell size")
    if caveats:
        return "GO WITH CAVEATS — a credible carrier pool exists, but " + "; ".join(caveats) + "."
    return "GO — a credible high-confidence carrier pool exists; proceed to phenotype eligibility."


def _released_or_suppressed(token: str, cfg: Config) -> int | None:
    if not token.startswith("~"):
        return None
    n = int(token[1:])
    return n if n >= cfg.sdc_min_cell else None


def _safe_estimate_from_token(token: str, proportion: float, cfg: Config) -> str:
    n = _released_or_suppressed(token, cfg)
    if n is None:
        return f"<{cfg.sdc_min_cell}"
    estimate = round_to(int(round(n * proportion)), cfg.sdc_round_to)
    return f"<{cfg.sdc_min_cell}" if estimate < cfg.sdc_min_cell else f"~{estimate}"


def _safe_count_token(n: int, cfg: Config) -> str:
    rounded = round_to(n, cfg.sdc_round_to)
    if n < cfg.sdc_min_cell or rounded < cfg.sdc_min_cell:
        return f"<{cfg.sdc_min_cell}"
    return f"~{rounded}"


def build_quality_sensitivity(
    classified: pd.DataFrame, cfg: Config, variant_info: float | None
) -> dict:
    """SDC-safe DR2 sensitivity table over retained carrier evidence.

    The table is withheld if any adjacent threshold movement would expose a non-zero sub-minimum
    delta. That preserves the same secondary-suppression discipline used for subgroup breakdowns.
    """
    midpoint = (cfg.imputed_dr2_min + cfg.imputed_dr2_high_confidence) / 2
    thresholds = sorted({cfg.imputed_dr2_min, midpoint, cfg.imputed_dr2_high_confidence})
    rows = []
    raw_counts = []
    for threshold in thresholds:
        count = classify.project_cells(
            classified, cfg, variant_info=variant_info, imputed_dr2_min=threshold
        )["total"]
        raw_counts.append(count)
        rows.append(
            {
                "threshold": f"DR2 >= {threshold:.2f}",
                "client_total": _safe_count_token(count, cfg),
            }
        )
    deltas = [abs(a - b) for a, b in zip(raw_counts[:-1], raw_counts[1:], strict=True)]
    if any(0 < delta < cfg.sdc_min_cell for delta in deltas):
        return {
            "suppressed": True,
            "reason": "withheld because adjacent thresholds expose a sub-minimum movement",
            "rows": (),
        }
    return {"suppressed": False, "reason": "", "rows": tuple(rows)}


def build_quality_cutoff_facts(cfg: Config) -> tuple[str, ...]:
    """Human-readable configured cut-offs for the client/reviewer summary."""
    return (
        f"Array call rate >= {cfg.array_call_rate_min}",
        f"Array GQ >= {cfg.array_gq_min}",
        f"Imputed variant DR2 >= {cfg.imputed_dr2_min}",
        f"Imputed max GP >= {cfg.imputed_max_gp_min}",
        f"Imputed dosage carrier threshold >= {cfg.imputed_dosage_carrier_threshold}",
    )


def _quality_cutoff_lines(cfg: Config, quality_sensitivity: dict | None = None) -> list[str]:
    lines = [f"  - {fact}" for fact in build_quality_cutoff_facts(cfg)]
    if quality_sensitivity is None:
        return lines
    if quality_sensitivity.get("suppressed"):
        lines.append(f"  - DR2 sensitivity: SUPPRESSED — {quality_sensitivity['reason']}.")
        return lines
    lines.append("  - DR2 sensitivity (SDC-applied):")
    lines.extend(
        f"    * {row['threshold']}: {row['client_total']}"
        for row in quality_sensitivity.get("rows", ())
    )
    return lines


def build_recruitability_funnel(
    result: FeasibilityResult,
    cfg: Config,
    response_rates: tuple[float, ...] = RECRUITABILITY_RESPONSE_RATES,
) -> tuple[dict, ...]:
    """Disclosure-safe recruitment-planning funnel from the released genotype ceiling.

    Response estimates are never allowed to create new sub-minimum numbers. If a derived estimate
    would fall below the configured minimum cell size, it is rendered with the same suppression
    token rather than as an exact or rounded small count.
    """
    rows = [
        {
            "step": "Genotype carrier ceiling",
            "value": result.client_total,
            "basis": "released SDC-applied genotype count",
        },
        {
            "step": "Phenotype eligibility",
            "value": "downstream aggregate return",
            "basis": "ICD-10 / linked-record review, not inferred in the genotype MVP",
        },
    ]
    for rate in response_rates:
        rows.append(
            {
                "step": f"Illustrative response at {int(rate * 100)}%",
                "value": _safe_estimate_from_token(result.client_total, rate, cfg),
                "basis": "planning assumption applied only to the released SDC token",
            }
        )
    return tuple(rows)


def build_data_factsheet(
    result: FeasibilityResult,
    request: VariantRequest,
    cfg: Config,
    release_candidate: ReleaseCandidate | None = None,
) -> dict:
    """Machine-readable, aggregate-only facts for downstream client/report skins."""
    return {
        "study_id": result.study_id,
        "cpra": result.cpra,
        "build": request.build,
        "requested_source": request.requested_source,
        "variant_on_array": result.variant_on_array,
        "variant_on_imputed": result.variant_on_imputed,
        "client_total": result.client_total,
        "breakdown_suppressed": result.breakdown_suppressed,
        "reported_cells": (
            tuple(release_candidate.reported_cells) if release_candidate is not None else ()
        ),
        "min_cell": cfg.sdc_min_cell,
        "round_to": cfg.sdc_round_to,
        "recommendation": _recommendation(result),
        "assumptions": result.assumptions,
        "limitations": result.limitations,
    }


def _safe_breakdown_lines(result: FeasibilityResult, cfg: Config) -> list[str]:
    if result.breakdown_suppressed:
        return [
            "Subgroup breakdown: suppressed under disclosure control; the total is the released "
            "figure."
        ]
    hi = round_to(result.high_confidence, cfg.sdc_round_to)
    conditional = round_to(result.conditional, cfg.sdc_round_to)
    return [
        f"Array-direct high-confidence carriers: ~{hi}",
        f"Imputed-supported conditional carriers: ~{conditional}",
    ]


def build_research_note(
    result: FeasibilityResult,
    request: VariantRequest,
    cfg: Config,
    release_candidate: ReleaseCandidate | None = None,
    quality_sensitivity: dict | None = None,
) -> str:
    """Research-facing note: method, evidence tiers, and caveats foregrounded."""
    facts = build_data_factsheet(result, request, cfg, release_candidate)
    return "\n".join(
        [
            "OFH GENOTYPE FEASIBILITY — RESEARCH NOTE (SDC-APPLIED)",
            "=" * 72,
            f"Study: {facts['study_id']} | Variant: {facts['cpra']} ({facts['build']})",
            f"Purpose: {request.purpose}",
            f"Released genotype carrier ceiling: {facts['client_total']}",
            f"Recommendation: {facts['recommendation']}",
            "",
            "Evidence interpretation",
            *[f"- {line}" for line in _safe_breakdown_lines(result, cfg)],
            f"- Requested source: {request.requested_source}; variant on array: "
            f"{'yes' if result.variant_on_array else 'no'}; variant in imputed resource: "
            f"{'yes' if result.variant_on_imputed else 'no'}",
            "",
            "Configured quality cut-offs",
            *_quality_cutoff_lines(cfg, quality_sensitivity),
            "",
            "Method assumptions",
            _bullets(result.assumptions),
            "",
            "Caveats",
            _bullets(result.limitations),
            "",
            f"Disclosure control: min cell {cfg.sdc_min_cell}; rounded to {cfg.sdc_round_to}.",
        ]
    )


def build_commercial_memo(
    result: FeasibilityResult,
    request: VariantRequest,
    cfg: Config,
    release_candidate: ReleaseCandidate | None = None,
    quality_sensitivity: dict | None = None,
) -> str:
    """INTERNAL planning preview for a commercial-facing conversation (NOT a release artefact).

    Derived planning figures (response-rate scenarios etc.) are Python-rendered analyst material:
    the only client-facing release is the Lean-authorised release.json payload."""
    _ = release_candidate  # kept for API symmetry with the research note.
    funnel = build_recruitability_funnel(result, cfg)
    lines = [
        "OFH GENOTYPE FEASIBILITY — INTERNAL PLANNING PREVIEW "
        "(SDC-APPLIED; NOT A RELEASE ARTEFACT)",
        "=" * 72,
        f"Question: can OFH identify carriers for {request.purpose}?",
        f"Decision signal: {_recommendation(result)}",
        f"Released genotype carrier ceiling: {result.client_total}",
        "",
        "Recruitability planning view",
    ]
    lines.extend(f"- {row['step']}: {row['value']} ({row['basis']})" for row in funnel)
    lines += [
        "",
        "Operational constraints",
        "- Genotype count is a ceiling before phenotype eligibility.",
        "- Participant-level tables and pseudonymised handoff remain internal to the TRE.",
        f"- SDC min cell {cfg.sdc_min_cell}, rounding {cfg.sdc_round_to}; no subgroup is released "
        "when it would enable differencing.",
        "- Configured quality cut-offs: " + "; ".join(build_quality_cutoff_facts(cfg)),
    ]
    if quality_sensitivity is not None:
        if quality_sensitivity.get("suppressed"):
            lines.append(
                "- DR2 sensitivity: suppressed because adjacent thresholds would expose a "
                "sub-minimum movement."
            )
        else:
            sensitivity = "; ".join(
                f"{row['threshold']} -> {row['client_total']}"
                for row in quality_sensitivity.get("rows", ())
            )
            lines.append(f"- DR2 sensitivity: {sensitivity}")
    lines += [
        "",
        "Caveats",
        _bullets(result.limitations),
    ]
    return "\n".join(lines)


def build_portfolio_table(
    items: list[tuple[FeasibilityResult, VariantRequest]], cfg: Config
) -> pd.DataFrame:
    """Aggregate table for comparing several governed requests without exposing hidden cells."""
    return pd.DataFrame(
        [
            {
                "study_id": result.study_id,
                "cpra": result.cpra,
                "purpose": request.purpose,
                "client_total": result.client_total,
                "breakdown": "suppressed" if result.breakdown_suppressed else "shown",
                "variant_on_array": result.variant_on_array,
                "recommendation": _recommendation(result),
                "min_cell": cfg.sdc_min_cell,
            }
            for result, request in items
        ]
    )


def build_audience_summary(
    audience: Audience,
    result: FeasibilityResult,
    request: VariantRequest,
    cfg: Config,
    release_candidate: ReleaseCandidate | None = None,
    quality_sensitivity: dict | None = None,
) -> str:
    """Render the same governed release for the selected audience."""
    if audience == "neutral":
        return build_feasibility_summary(result, request, cfg, quality_sensitivity)
    if audience == "research":
        return build_research_note(
            result, request, cfg, release_candidate, quality_sensitivity
        )
    if audience == "commercial":
        return build_commercial_memo(
            result, request, cfg, release_candidate, quality_sensitivity
        )
    raise ValueError(f"unknown audience: {audience!r}")


def build_batch_summary_for_audience(
    audience: Audience, batch: BatchRequest, combined: dict, cfg: Config
) -> str:
    """Audience rendering for gene/disease/composite requests; releases only the governed union."""
    if audience == "neutral":
        return build_batch_summary(batch, combined)
    heading = (
        "OFH MULTI-VARIANT FEASIBILITY — RESEARCH NOTE (SDC-APPLIED)"
        if audience == "research"
        else "OFH MULTI-VARIANT FEASIBILITY — CLIENT PLANNING MEMO (SDC-APPLIED)"
    )
    lines = [
        heading,
        "=" * 72,
        f"Study: {batch.study_id} | variants assessed: {len(batch.variants)}",
        f"Purpose: {batch.purpose}",
        f"Released union carrier ceiling: {combined['combined_client_total']}",
        "",
        "Disclosure control",
        f"- min cell {cfg.sdc_min_cell}; rounded to {cfg.sdc_round_to}.",
        "- Per-variant and overlap counts are withheld because they can expose intersections or "
        "complements by differencing against the union.",
        "",
        "Interpretation",
        "- The figure is genotype feasibility before phenotype eligibility.",
        "- The pseudonymised carrier set remains internal for epidemiology review.",
    ]
    if audience == "commercial":
        for rate in RECRUITABILITY_RESPONSE_RATES:
            estimate = _safe_estimate_from_token(
                combined["combined_client_total"], rate, cfg
            )
            lines.append(f"- Illustrative response at {int(rate * 100)}%: {estimate}")
    return "\n".join(lines)


def _bullets(items) -> str:
    return "\n".join(f"  - {x}" for x in items)


def _ancestry_line(result: FeasibilityResult) -> str:
    if result.ancestry_suppressed:
        return (
            "  Ancestry breakdown: SUPPRESSED — a per-ancestry stratum is below the minimum\n"
            "  cell size; with the total released, showing the rest would expose it."
        )
    if result.ancestry_breakdown:
        rows = ", ".join(f"{g}: ~{n}" for g, n in result.ancestry_breakdown)
        return f"  Ancestry breakdown (consented carriers): {rows}"
    return "  Ancestry breakdown: n/a"


def render_markdown_report(result: FeasibilityResult, request: VariantRequest, cfg: Config) -> str:
    """A tidy Markdown report of the client feasibility note (for sharing/printing); SDC-applied."""
    lines = [
        f"# Genotype feasibility — {request.study_id}",
        "",
        f"**Variant:** `{request.cpra}` (build {request.build}); "
        f"carrier = {request.carrier_definition}",
        f"**Purpose:** {request.purpose}",
        "",
        "## Recommendation",
        f"> {_recommendation(result)}",
        "",
        "## Eligible genotype carriers (consented, QC-passed)",
        "",
        "| Metric | Value (SDC-applied) |",
        "|---|---|",
        f"| Approximate count | {result.client_total} |",
    ]
    if result.breakdown_suppressed:
        lines.append("| Subgroup breakdown | suppressed (a subgroup below the minimum cell size) |")
    else:
        hi = round_to(result.high_confidence, cfg.sdc_round_to)
        cond = round_to(result.conditional, cfg.sdc_round_to)
        lines.append(f"| Array-direct (high confidence) | ~{hi} |")
        lines.append(f"| Imputed-supported (conditional) | ~{cond} |")
    if result.ancestry_suppressed:
        lines.append(
            "| Ancestry breakdown | suppressed (a per-ancestry stratum below the minimum) |"
        )
    elif result.ancestry_breakdown:
        cells = ", ".join(f"{g}: ~{n}" for g, n in result.ancestry_breakdown)
        lines.append(f"| Ancestry breakdown | {cells} |")
    lines += [
        "",
        "## Method",
        *(f"- {a}" for a in result.assumptions),
        "",
        "## Caveats",
        *(f"- {x}" for x in result.limitations),
        "",
        f"_Disclosure control: min cell {cfg.sdc_min_cell}, rounding to {cfg.sdc_round_to}; "
        "secondary suppression applied. The airlock export is the Lean-authorised release.json._",
    ]
    return "\n".join(lines)


def build_feasibility_summary(
    result: FeasibilityResult,
    request: VariantRequest,
    cfg: Config,
    quality_sensitivity: dict | None = None,
) -> str:
    """SDC-applied feasibility note (human-readable; INTERNAL — release.json is the export)."""
    if result.breakdown_suppressed:
        breakdown = (
            "  Subgroup breakdown (array-direct vs imputed-supported): SUPPRESSED — a subgroup\n"
            f"  is below the minimum cell size ({cfg.sdc_min_cell}); releasing it beside the\n"
            "  total would permit back-calculation of the complement."
        )
    else:
        hi = round_to(result.high_confidence, cfg.sdc_round_to)
        cond = round_to(result.conditional, cfg.sdc_round_to)
        breakdown = (
            f"  Array-direct (high confidence):  ~{hi}\n  Imputed-supported (conditional): ~{cond}"
        )
    return "\n".join(
        [
            "OUR FUTURE HEALTH — GENOTYPE FEASIBILITY SUMMARY "
            "(INTERNAL ANALYST NOTE, SDC-APPLIED)",
            "=" * 78,
            f"1. REQUEST          {request.study_id} | purpose: {request.purpose}",
            f"2. VARIANT          {request.cpra} (build {request.build}); ref {request.ref} / "
            f"alt {request.alt}; carrier = {request.carrier_definition}",
            f"3. SOURCES CHECKED  requested: {request.requested_source}; variant on OFH array: "
            f"{'yes — array-direct evidence available' if result.variant_on_array else 'no'}; "
            "variant in OFH imputed resource: "
            f"{'yes' if result.variant_on_imputed else 'no — imputed evidence unavailable'}",
            "   evidence tiers: array-direct > imputed-high (DR2 high) > imputed-conditional",
            "4. METHOD",
            _bullets(result.assumptions),
            "5. ELIGIBLE GENOTYPE CARRIERS (consented, QC-passed) — disclosure-controlled",
            f"  Approximate count: {result.client_total}   "
            f"[rounded to nearest {cfg.sdc_round_to}; SDC applied]",
            breakdown,
            _ancestry_line(result),
            "6. INTERNAL HANDOFF  pseudonymised carrier set staged for epidemiology (in-TRE)",
            "7. PHENOTYPE         ICD-10 phenotype eligibility assessed downstream by epi",
            "8. QUALITY CUT-OFFS  configured and surfaced, not hidden",
            *_quality_cutoff_lines(cfg, quality_sensitivity),
            "9. DISCLOSURE CONTROL",
            f"  - min cell size {cfg.sdc_min_cell}, rounding to nearest {cfg.sdc_round_to}; "
            "secondary suppression withholds the breakdown if any subgroup is small.",
            "  - The canonical airlock export is the Lean-authorised release.json payload;\n"
            "    this note and all participant-level tables remain internal.",
            "10. CAVEATS",
            _bullets(result.limitations),
            "-" * 78,
            f"RECOMMENDATION: {_recommendation(result)}",
        ]
    )
