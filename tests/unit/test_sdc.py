"""SDC tests: specific cases + property tests for the disclosure-control invariants."""

import numpy as np
import pytest

from ofh_feasibility import sdc
from ofh_feasibility.config import Config

pytestmark = pytest.mark.unit


def _cfg(min_cell=10, round_to=5):
    return Config.from_dict(
        dict(
            array_call_rate_min=0.98,
            array_gq_min=20,
            imputed_info_min=0.30,
            imputed_info_high_confidence=0.80,
            imputed_dosage_carrier_threshold=0.5,
            imputed_max_gp_min=0.90,
            carrier_definition="het_and_homalt",
            require_consent=True,
            sdc_min_cell=min_cell,
            sdc_round_to=round_to,
            data_dir="d",
            results_dir="r",
        )
    )


def _cells(high, cond):
    return {
        "high_confidence": high,
        "conditional": cond,
        "total": high + cond,
        "excluded": 0,
        "flagged": 0,
    }


# --- round_to ----------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "n,base,expected",
    [
        (7, 5, 5),
        (8, 5, 10),
        (12, 5, 10),
        (13, 5, 15),
        (25, 5, 25),
        (2, 5, 0),
        (0, 5, 0),
        (10, 0, 10),
    ],
)
def test_round_to(n, base, expected):
    assert sdc.round_to(n, base) == expected


# --- specific cases ----------------------------------------------------------------------------


def test_small_total_and_small_subgroups_suppress_everything():
    out = sdc.apply_sdc(_cells(2, 1), _cfg())  # total 3 < 10
    assert out["client_total"] == "<10"
    assert out["breakdown_suppressed"] and out["reported_cells"] == {}


def test_secondary_suppression_one_small_subgroup_withholds_breakdown():
    out = sdc.apply_sdc(_cells(25, 5), _cfg())  # total 30 ok, but conditional=5 < 10
    assert out["client_total"] == "~30"
    assert out["breakdown_suppressed"] and out["reported_cells"] == {}
    assert out["small_cells"] == ["imputed_supported_conditional"]


def test_breakdown_released_when_all_subgroups_large():
    out = sdc.apply_sdc(_cells(25, 15), _cfg())
    assert not out["breakdown_suppressed"]
    assert out["reported_cells"] == {
        "array_direct_high_confidence": 25,
        "imputed_supported_conditional": 15,
    }
    assert out["client_total"] == "~40"


def test_zero_subgroups_are_not_small():
    out = sdc.apply_sdc(_cells(0, 0), _cfg())
    assert out["total_suppressed"] and out["client_total"] == "<10"
    assert not out["breakdown_suppressed"]  # 0 is a structural zero, not a small cell


def test_apply_sdc_suppresses_when_rounding_would_cross_below_min():
    # Config forbids a non-dividing config, but apply_sdc is robust by itself: with min_cell=12,
    # round_to=5, a raw cell of 12 rounds to 10 (< 12), so it is suppressed rather than released.
    from types import SimpleNamespace

    fake = SimpleNamespace(sdc_min_cell=12, sdc_round_to=5)
    out = sdc.apply_sdc(_cells(12, 12), fake)
    assert out["breakdown_suppressed"] and out["reported_cells"] == {}
    # large cells (round to >= min) are still released
    big = sdc.apply_sdc(_cells(20, 20), fake)
    assert not big["breakdown_suppressed"]
    assert big["reported_cells"]["array_direct_high_confidence"] == 20


# --- per-stratum SDC (ancestry) ----------------------------------------------------------------

def test_apply_sdc_strata_suppresses_whole_breakdown_for_a_small_group():
    out = sdc.apply_sdc_strata({"EUR": 25, "SAS": 3}, _cfg())  # SAS below min
    assert out["suppressed"] and out["reported"] == {} and out["small_strata"] == ["SAS"]


def test_apply_sdc_strata_releases_when_all_groups_large():
    out = sdc.apply_sdc_strata({"EUR": 25, "SAS": 15}, _cfg())
    assert not out["suppressed"] and out["reported"] == {"EUR": 25, "SAS": 15}


def test_apply_sdc_strata_suppresses_when_strata_do_not_sum_to_total():
    out = sdc.apply_sdc_strata({"EUR": 25, "SAS": 15}, _cfg(), expected_total=41)
    assert out["suppressed"] is True
    assert out["reported"] == {}
    assert out["unaccounted"] == 1


# --- property tests: the governance invariants -------------------------------------------------

_CONFIGS = [(10, 5), (5, 5), (20, 10), (15, 5)]  # min_cell a multiple of round_to


def _released_int(token):
    """Parse the int from a '~N' client_total token (None for the '<min' suppression token)."""
    return int(token[1:]) if token.startswith("~") else None


def test_property_invariants_over_random_inputs():
    rng = np.random.default_rng(42)
    for mc, rb in _CONFIGS:
        cfg = _cfg(mc, rb)
        for _ in range(500):
            high, cond = int(rng.integers(0, 60)), int(rng.integers(0, 60))
            out = sdc.apply_sdc(_cells(high, cond), cfg)
            raw = {"array_direct_high_confidence": high, "imputed_supported_conditional": cond}

            # Invariant A — suppression: any subgroup raw count in (0, mc) -> breakdown withheld.
            if any(0 < n < mc for n in raw.values()):
                assert out["breakdown_suppressed"] and out["reported_cells"] == {}

            # Invariant B — secondary suppression / no released cell below min:
            # if the breakdown is shown, every released subgroup is 0 or >= mc, so total minus one
            # subgroup can never expose a sub-min cell.
            if not out["breakdown_suppressed"]:
                for v in out["reported_cells"].values():
                    assert v == 0 or v >= mc

            # Invariant C — rounding: every released count is a multiple of round_to.
            total_int = _released_int(out["client_total"])
            if total_int is not None:
                assert total_int % rb == 0
            for v in out["reported_cells"].values():
                assert v % rb == 0
