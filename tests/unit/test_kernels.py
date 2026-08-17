"""Kernel tests: each @njit kernel asserted against its pure-NumPy reference."""
import numpy as np
import pytest

from ofh_feasibility import kernels

pytestmark = pytest.mark.unit


def _random_gt_mask(rng, n):
    gt = rng.integers(-1, 3, size=n).astype(np.int8)  # values in {-1,0,1,2}
    mask = rng.integers(0, 2, size=n).astype(bool)
    return gt, mask


def test_count_carriers_matches_reference():
    rng = np.random.default_rng(42)
    for n in (0, 1, 7, 50, 1000):
        gt, mask = _random_gt_mask(rng, n)
        assert kernels.count_carriers(gt, mask) == kernels._ref_count_carriers(gt, mask)


def test_count_carriers_carrier_is_het_plus_homalt():
    rng = np.random.default_rng(7)
    gt, mask = _random_gt_mask(rng, 500)
    n_carrier, n_het, n_homalt = kernels.count_carriers(gt, mask)
    assert n_carrier == n_het + n_homalt


def test_count_carriers_ignores_masked_and_missing():
    gt = np.array([1, 2, 1, -1, 1], dtype=np.int8)
    mask = np.array([True, True, False, True, True], dtype=bool)
    # counted: idx0 het, idx1 homalt, idx4 het; idx2 masked out; idx3 missing
    assert kernels.count_carriers(gt, mask) == (3, 2, 1)


def test_count_carriers_can_exclude_homalt_for_het_only():
    gt = np.array([1, 2, 2, 0, -1], dtype=np.int8)
    mask = np.array([True, True, True, True, True], dtype=bool)
    assert kernels.count_carriers(gt, mask, include_homalt=False) == (1, 1, 2)
    assert kernels.count_carriers(gt, mask, include_homalt=False) == kernels._ref_count_carriers(
        gt, mask, include_homalt=False
    )
