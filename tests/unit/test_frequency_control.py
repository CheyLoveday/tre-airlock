"""Unit tests for the INTERNAL variant-frequency control view (AF + Wilson CI, ploidy, kinship)."""
import numpy as np
import pandas as pd
import pytest

from ofh_feasibility import reporting
from ofh_feasibility.config import Config
from ofh_feasibility.models import VariantRequest

pytestmark = pytest.mark.unit


def _cfg():
    return Config.from_dict(dict(
        array_call_rate_min=0.98, array_gq_min=20, imputed_info_min=0.30,
        imputed_info_high_confidence=0.80, imputed_dosage_carrier_threshold=0.5,
        imputed_max_gp_min=0.90, carrier_definition="het_and_homalt", require_consent=True,
        sdc_min_cell=10, sdc_round_to=5, data_dir="d", results_dir="r",
    ))


def _request(chrom="10"):
    pos = 119669928
    return VariantRequest.from_dict(dict(
        study_id="S", cpra=f"{chrom}:{pos}:C:G", chrom=chrom, pos=pos, ref="C", alt="G",
        build="GRCh38", carrier_definition="het_and_homalt", requested_source="array_and_imputed",
        purpose="p",
    ))


def _cohort():
    n = 30
    carriers = {0, 2, 4, 6, 8, 10}  # 6 het carriers, all even-index (-> all 'M'), all EUR (<20)
    ancestry = ["EUR"] * 20 + ["SAS"] * 8 + ["AFR"] * 2
    cand = pd.DataFrame({
        "participant_id": [f"P{i}" for i in range(n)],
        "sex": ["M" if i % 2 == 0 else "F" for i in range(n)],
        "ancestry_stub": ancestry,
        "array_gt_code": [1.0 if i in carriers else 0.0 for i in range(n)],
        "imputed_dosage": [1.0 if i in carriers else 0.0 for i in range(n)],
        "kinship_flag": [i in {0, 1} for i in range(n)],
    })
    return cand, np.ones(n, dtype=bool)  # all callable


def test_wilson_point_and_interval():
    af, lo, hi = reporting._wilson(10, 100)  # 10 alt alleles in 100 callable
    assert af == 0.1
    assert lo == pytest.approx(0.0552, abs=1e-3) and hi == pytest.approx(0.1744, abs=1e-3)
    assert 0.0 <= lo < af < hi <= 1.0


def test_overall_af_and_internal_classification():
    cand, mask = _cohort()
    fc = reporting.build_frequency_control(cand, mask, _request(), _cfg())
    assert fc["classification"] == "INTERNAL-TRE-ONLY" and fc["exportable"] is False
    assert fc["ploidy_guard"] is False
    assert fc["overall"]["af"] == 0.1 and fc["overall"]["callable_alleles"] == 60


def test_small_ancestry_strata_suppressed_even_internally():
    cand, mask = _cohort()
    fc = reporting.build_frequency_control(cand, mask, _request(), _cfg())
    assert fc["by_ancestry"]["EUR"]["suppressed"] is False         # 20 callable >= min
    assert fc["by_ancestry"]["SAS"]["suppressed"] is True          # 8 < min cell
    assert fc["by_ancestry"]["AFR"]["suppressed"] is True          # 2 < min cell
    assert fc["by_sex"]["M"]["af"] == 0.2                          # 6 alt / 30 callable alleles


def test_ploidy_guard_for_non_autosomal():
    cand, mask = _cohort()
    fc = reporting.build_frequency_control(cand, mask, _request(chrom="X"), _cfg())
    assert fc["ploidy_guard"] is True and "overall" not in fc and fc["exportable"] is False


def test_kinship_stability_present():
    cand, mask = _cohort()
    ks = reporting.build_frequency_control(cand, mask, _request(), _cfg())["kinship_stability"]
    assert ks["full_af"] == 0.1 and ks["n_related_excluded"] == 2
    assert isinstance(ks["bootstrap_ci95"], list) and len(ks["bootstrap_ci95"]) == 2
    assert ks["unrelated_only_af"] is not None  # AF still computable on the unrelated subset
    assert ks["af_delta"] == pytest.approx(0.01071)
    assert "differs by 0.01071" in ks["note"]


def test_bootstrap_ci_matches_seeded_loop_reference_with_chunked_draws():
    gt = np.array([0, 1, 0, 2, 1, 0, 1, 0, 2, 0, 1, 0], dtype=np.int8)
    df = pd.DataFrame({"array_ok": [True] * len(gt), "array_gt_code": gt})

    rng = np.random.default_rng(42)
    loop_afs = np.array(
        [rng.choice(gt, size=len(gt), replace=True).sum() / (2 * len(gt)) for _ in range(1000)]
    )
    lo, hi = np.percentile(loop_afs, [2.5, 97.5])
    expected = [round(float(lo), 5), round(float(hi), 5)]

    assert reporting._bootstrap_af_ci(df, _cfg(), max_draw_bytes=gt.nbytes * 3) == expected
