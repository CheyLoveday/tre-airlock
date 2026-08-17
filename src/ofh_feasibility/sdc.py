"""sdc — statistical disclosure control (Safe Outputs).

Two parameters: sdc_min_cell (suppress counts below this) and sdc_round_to (round released counts).
The step people get wrong is SECONDARY suppression: if any reportable subgroup is below the
minimum cell size, the whole breakdown is withheld and only the rounded total is released —
showing a total beside a suppressed subgroup lets the complement be back-calculated. Pure; no IO.

Released cells: high-confidence (array-direct) and conditional (imputed-supported); total = sum.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .config import Config


def round_to(n: int, base: int) -> int:
    """Round n to the nearest multiple of base (banker's rounding); base=0 is a no-op."""
    if not base:
        return int(n)
    return int(base * round(float(n) / base))


def suppress_total(n: int, cfg: Config) -> dict:
    """Suppress + round a single released total: '<min' if below the minimum (raw or rounded),
    else '~rounded'. The Wave 8 post-phenotype eligible count is a single aggregate figure."""
    mc, rb = cfg.sdc_min_cell, cfg.sdc_round_to
    suppressed = n < mc or round_to(n, rb) < mc
    return {
        "client_total": f"<{mc}" if suppressed else f"~{round_to(n, rb)}",
        "suppressed": suppressed,
    }


def apply_sdc_strata(counts: dict, cfg: Config, expected_total: int | None = None) -> dict:
    """Secondary suppression over arbitrary strata (e.g. ancestry groups).

    Because the overall total is released, a single small stratum must withhold the WHOLE
    breakdown — otherwise the suppressed group is `total - sum(shown)`. Releases rounded counts
    only when every stratum is 0 or >= the minimum (raw and rounded). If an expected total is
    provided, any under-count suppresses the breakdown because the missing remainder is itself a
    derivable stratum.
    """
    mc, rb = cfg.sdc_min_cell, cfg.sdc_round_to
    small = [k for k, n in counts.items() if n > 0 and (n < mc or round_to(n, rb) < mc)]
    unaccounted = None if expected_total is None else expected_total - sum(counts.values())
    incomplete = unaccounted is not None and unaccounted != 0
    suppressed = len(small) > 0 or incomplete
    reported = {} if suppressed else {k: round_to(n, rb) for k, n in counts.items()}
    return {
        "suppressed": suppressed,
        "small_strata": small,
        "reported": reported,
        "unaccounted": unaccounted,
    }


def apply_sdc(cells: dict, cfg: Config) -> dict:
    """Apply suppression + secondary suppression + rounding; return what may be released."""
    mc, rb = cfg.sdc_min_cell, cfg.sdc_round_to
    total = cells["total"]
    subgroups = {
        "array_direct_high_confidence": cells["high_confidence"],
        "imputed_supported_conditional": cells["conditional"],
    }
    # Secondary suppression: a single small subgroup withholds the ENTIRE breakdown. A cell is
    # "small" if its RAW count is below the minimum OR its rounded (released) value would be — so
    # rounding-down can never push a released cell under the threshold (config also pins
    # min_cell % round_to == 0, making the rounded clause belt-and-braces).
    small = [name for name, n in subgroups.items() if n > 0 and (n < mc or round_to(n, rb) < mc)]
    breakdown_suppressed = len(small) > 0
    total_suppressed = total < mc or round_to(total, rb) < mc

    client_total = f"<{mc}" if total_suppressed else f"~{round_to(total, rb)}"
    reported_cells = (
        {} if breakdown_suppressed else {name: round_to(n, rb) for name, n in subgroups.items()}
    )
    return {
        "client_total": client_total,
        "breakdown_suppressed": breakdown_suppressed,
        "total_suppressed": total_suppressed,
        "reported_cells": reported_cells,
        "small_cells": small,
        "min_cell": mc,
        "round_to": rb,
    }
