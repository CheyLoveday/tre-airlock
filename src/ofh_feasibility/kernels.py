"""kernels — Numba @njit numeric hot loops (+ pure-NumPy references for tests).

The ONLY module that imports numba. Inputs/outputs are numeric NumPy arrays (int8 genotype
hardcalls, bool masks) — no pandas, strings, IO, or Python objects inside the JIT boundary; the
orchestrator converts pandas <-> NumPy at the edge. Each kernel has a `_ref_*` NumPy oracle that
tests assert against, so the fast path is provably equivalent to the obvious slow path.

Genotype hardcall codes: 0=hom-ref, 1=het, 2=hom-alt, -1=missing.
"""
from __future__ import annotations

import numpy as np
from numba import njit


@njit(cache=True)
def count_carriers(
    gt: np.ndarray, mask: np.ndarray, include_homalt: bool = True
) -> tuple[int, int, int]:
    """Count carriers over QC-passing int8 hardcalls: (n_carrier, n_het, n_homalt)."""
    n_het = 0
    n_homalt = 0
    for i in range(gt.shape[0]):
        if not mask[i]:
            continue
        g = gt[i]
        if g == 1:
            n_het += 1
        elif g == 2:
            n_homalt += 1
    n_carrier = n_het + n_homalt if include_homalt else n_het
    return n_carrier, n_het, n_homalt

def _ref_count_carriers(
    gt: np.ndarray, mask: np.ndarray, include_homalt: bool = True
) -> tuple[int, int, int]:
    """Pure-NumPy reference for count_carriers (test oracle)."""
    g = gt[mask.astype(bool)]
    n_het = int(np.sum(g == 1))
    n_homalt = int(np.sum(g == 2))
    n_carrier = n_het + n_homalt if include_homalt else n_het
    return n_carrier, n_het, n_homalt
