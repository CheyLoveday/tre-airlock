"""Shared pytest fixtures."""

import shutil
import subprocess
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

CPRA = "10:119669928:C:G"

_REPO = Path(__file__).resolve().parents[1]
_AIRLOCK_EXE = _REPO / "formal" / ".lake" / "build" / "bin" / "airlock"


@pytest.fixture(scope="session", autouse=True)
def _ensure_airlock_binary():
    """Build the runtime Lean adjudicator once if missing (release-path tests require it).

    The pipeline's release authority is the Lean airlock (bridge.authorize) — there is no Python
    fallback. If `lake` is unavailable the build is skipped silently here and only the tests that
    actually cross the release boundary fail, with the bridge's `make airlock` remediation.
    """
    if _AIRLOCK_EXE.is_file():
        return
    lake = shutil.which("lake") or (
        str(Path.home() / ".elan" / "bin" / "lake")
        if (Path.home() / ".elan" / "bin" / "lake").is_file()
        else None
    )
    if lake:
        subprocess.run([lake, "build"], cwd=_REPO / "formal", capture_output=True, timeout=900)


@pytest.fixture
def tiny_cohort():
    """A tiny deterministic cohort (in-memory) for integration/e2e tests.

    30 participants; carriers at indices {3, 7, 11, 15}. Index 7 is a withdrawn-consent
    carrier (must be excluded); index 15 is imputed-only. Columns match ofh_feasibility.models.
    """
    n = 30
    pids = [f"OFH{100000 + i}" for i in range(n)]
    carriers = {3, 7, 11, 15}
    withdrawn, imputed_only = 7, 15

    participants = pd.DataFrame(
        {
            "participant_id": pids,
            "pseudo_id": [f"PSU-{i:06d}" for i in range(n)],
            "sex": ["F" if i % 2 else "M" for i in range(n)],
            "ancestry_stub": ["EUR"] * n,
            "consent_status": ["withdrawn" if i == withdrawn else "consented" for i in range(n)],
            "baseline_qc_pass": [True] * n,
        }
    )

    cols = ["participant_id", "cpra", "source", "gt_code", "gq", "call_rate", "dosage", "max_gp"]
    rows = []
    for i, pid in enumerate(pids):
        if i != imputed_only:
            rows.append((pid, CPRA, "array", 1 if i in carriers else 0, 40, 0.99, np.nan, np.nan))
        rows.append(
            (pid, CPRA, "imputed", np.nan, np.nan, np.nan, 1.0 if i in carriers else 0.0, 0.95)
        )
    genotype_slice = pd.DataFrame(rows, columns=cols)

    sample_qc = pd.DataFrame(
        {
            "participant_id": pids,
            "array_call_rate": [0.99] * n,
            "het_rate": [0.25] * n,
            "sex_check_pass": [True] * n,
            "ancestry_pc1": [0.0] * n,
            "ancestry_pc2": [0.0] * n,
            "kinship_flag": [False] * n,
        }
    )

    request = {
        "study_id": "TEST",
        "cpra": CPRA,
        "chrom": "10",
        "pos": 119669928,
        "ref": "C",
        "alt": "G",
        "build": "GRCh38",
        "carrier_definition": "het_and_homalt",
        "requested_source": "array_and_imputed",
        "purpose": "test",
    }
    return {
        "participants": participants,
        "genotype_slice": genotype_slice,
        "sample_qc": sample_qc,
        "request": request,
        "expected": {"true_carriers": len(carriers), "withdrawn": pids[withdrawn]},
    }
