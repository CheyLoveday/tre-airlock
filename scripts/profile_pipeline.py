#!/usr/bin/env python3
"""profile_pipeline.py — cohort-size profiling sweep over the feasibility pipeline.

Generates scaled synthetic cohorts ("dummy-data copies" of the seeded N=500 cohort) at several
sizes and profiles `pipeline.orchestrate` at each, capturing wall time, peak RSS, and a per-function
cProfile breakdown — so the **scaling slope** (linear vs super-linear) is measured, not asserted.

Design (mirrors the house rule "no perf claim without a saved profile; broad cProfile -> narrow"):
- The cohort is tiled by a *vectorised* concat with per-copy unique participant IDs (NO big-axis
  Python loop — the only loop is over the handful of sweep sizes). Carrier fraction + edge-case mix
  are held constant across N, so wall-vs-N isolates pure scaling.
- `orchestrate` is the stable public entry (same one run_demo + the CLI use), so this harness is
  robust to internal churn; the cProfile breakdown shows the compute / IO / governance split per N.

Run on a SETTLED (green) tree:
    uv run --extra profile python scripts/profile_pipeline.py \
      --sweep 1000,5000,50000,500000,1000000
    uv run python scripts/profile_pipeline.py --sweep 500,5000,50000
"""

from __future__ import annotations

import argparse
import cProfile
import math
import pstats
import shutil
import threading
import time
from pathlib import Path

import numpy as np
import pandas as pd
import psutil

from ofh_feasibility import io, pipeline
from ofh_feasibility.config import load_config

BASE_DIR = Path("data/synthetic")
ID_COLS = ("participant_id", "pseudo_id")  # suffixed per tile copy so IDs stay unique
KEY = "participant_id"  # the join key shared by participants / genotype_slice / sample_qc


def _tile(df: pd.DataFrame, factor: int, copy_idx: np.ndarray | None = None) -> pd.DataFrame:
    """`factor` vectorised copies of df; participant ids suffixed by copy so joins stay 1:1."""
    out = pd.concat([df] * factor, ignore_index=True)
    idx = np.repeat(np.arange(factor), len(df)).astype(str) if copy_idx is None else copy_idx
    for c in (set(ID_COLS) | {KEY}) & set(out.columns):
        out[c] = out[c].astype(str) + "#" + idx
    return out


def scale_cohort(factor: int, out_dir: Path) -> None:
    """Write a synthetic data dir scaled to `factor`x the base cohort (same distributions)."""
    out_dir.mkdir(parents=True, exist_ok=True)
    participants = pd.read_parquet(BASE_DIR / "participant_table.parquet")
    genotype = pd.read_parquet(BASE_DIR / "genotype_slice.parquet")
    sample_qc = pd.read_csv(BASE_DIR / "sample_qc_metrics.tsv", sep="\t")
    _tile(participants, factor).to_parquet(out_dir / "participant_table.parquet")
    _tile(genotype, factor).to_parquet(out_dir / "genotype_slice.parquet")
    _tile(sample_qc, factor).to_csv(out_dir / "sample_qc_metrics.tsv", sep="\t", index=False)
    # the variant request + manifest are cohort-independent — copy verbatim
    for f in ("variant_request.csv", "variant_manifest.csv"):
        shutil.copy(BASE_DIR / f, out_dir / f)


class _RssPoller:
    """Sample peak RSS (MB) on a background thread while a call runs."""

    def __init__(self, interval: float = 0.02) -> None:
        self._proc = psutil.Process()
        self._interval, self._peak, self._run = interval, 0.0, False

    def __enter__(self) -> _RssPoller:
        self._run = True
        self._t = threading.Thread(target=self._loop, daemon=True)
        self._t.start()
        return self

    def _loop(self) -> None:
        while self._run:
            self._peak = max(self._peak, self._proc.memory_info().rss / 1e6)
            time.sleep(self._interval)

    def __exit__(self, *exc: object) -> None:
        self._run = False
        self._t.join()

    @property
    def peak_mb(self) -> float:
        return self._peak


def _top_functions(prof: cProfile.Profile, n: int = 8) -> list[tuple[str, float]]:
    """Top functions by cumulative time, read from the stats dict (robust to text formatting)."""
    stats = pstats.Stats(prof).stats  # {(file,line,func): (cc, nc, tt, ct, callers)}
    items = sorted(stats.items(), key=lambda kv: kv[1][3], reverse=True)
    out: list[tuple[str, float]] = []
    for (fpath, line, fname), (_cc, _nc, _tt, ct, _callers) in items:
        if "ofh_feasibility" not in fpath and fname not in ("orchestrate", "run_pipeline"):
            continue  # focus on our code, skip stdlib/pandas internals
        out.append((f"{Path(fpath).name}:{line}({fname})", ct))
        if len(out) >= n:
            break
    return out


def profile_one(n: int, tmp: Path, repeats: int = 1) -> dict:
    factor = max(1, math.ceil(n / 500))
    actual = factor * 500
    data_dir = tmp / f"data_{actual}"
    results_dir = tmp / f"results_{actual}"
    scale_cohort(factor, data_dir)
    cfg = load_config("config.yaml").model_copy(
        update={
            "data_dir": str(data_dir),
            "results_dir": str(results_dir),
            "source_format": "simplified",
        }
    )
    request = io.read_request(data_dir / "variant_request.csv")

    # Warm: JIT compile + first-touch imports excluded from timing.
    pipeline.orchestrate(cfg, request)
    walls: list[float] = []
    prof = cProfile.Profile()
    peak = 0.0
    for _ in range(repeats):
        with _RssPoller() as poller:
            t0 = time.perf_counter()
            prof.enable()
            pipeline.orchestrate(cfg, request)
            prof.disable()
            walls.append(time.perf_counter() - t0)
        peak = max(peak, poller.peak_mb)
    wall = float(np.median(walls))
    return {
        "n": actual,
        "wall_s": wall,
        "us_per_row": wall * 1e6 / actual,
        "peak_rss_mb": peak,
        "top": _top_functions(prof),
    }


def _slope(ns: list[int], walls: list[float]) -> float:
    """log-log scaling exponent: ~1.0 linear, >1.2 investigate, ~2.0 quadratic."""
    if len(ns) < 2:
        return float("nan")
    a, b = np.polyfit(np.log(ns), np.log(walls), 1)
    return float(a)


def run_sweep(sizes: list[int], tmp: Path, repeats: int) -> str:
    rows = [profile_one(n, tmp, repeats) for n in sizes]
    slope = _slope([r["n"] for r in rows], [r["wall_s"] for r in rows])
    lines = [
        "# Profile sweep (orchestrate, synthetic cohort)",
        "",
        f"Scaling slope (log-log fit of wall vs N): **{slope:.2f}** "
        "(~1.0 linear · >1.2 investigate · ~2.0 quadratic).",
        "",
        "| N | wall (s) | µs/row | peak RSS (MB) |",
        "|---|---|---|---|",
    ]
    lines += [
        (f"| {r['n']:,} | {r['wall_s']:.3f} | {r['us_per_row']:.2f} | {r['peak_rss_mb']:.0f} |")
        for r in rows
    ]
    lines += ["", f"Top cumulative functions @ N={rows[-1]['n']:,}:", ""]
    lines += [f"- `{fn}` — {ct:.3f}s" for fn, ct in rows[-1]["top"]]
    lines += [
        "",
        "Reproduce: `uv run --extra profile python scripts/profile_pipeline.py --sweep "
        + ",".join(str(s) for s in sizes)
        + "` (seed 42; warmed; median of "
        + f"{repeats}).",
        "",
    ]
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> None:
    p = argparse.ArgumentParser(
        description="Cohort-size profiling sweep over the feasibility pipeline."
    )
    p.add_argument(
        "--sweep",
        default="500,5000,50000",
        help="comma-separated cohort sizes, e.g. 1000,5000,50000,500000,1000000",
    )
    p.add_argument("--repeats", type=int, default=1, help="timed repeats per N (median reported)")
    p.add_argument(
        "--out",
        default="results/profiling/profile-sweep.md",
        help="markdown summary path (raw run dir alongside)",
    )
    args = p.parse_args(argv)

    sizes = [int(s) for s in args.sweep.split(",") if s.strip()]
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    tmp = out.parent / "_cohorts"
    try:
        summary = run_sweep(sizes, tmp, args.repeats)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    out.write_text(summary + "\n")
    print(summary)
    print(f"\nWritten: {out}")


if __name__ == "__main__":
    main()
