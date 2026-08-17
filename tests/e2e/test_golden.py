"""Golden-file test: the deterministic tiny_cohort run must match committed expected outputs.

The pipeline is deterministic (seed 42, no RNG), so the four governed artefacts are byte-stable.
Provenance is excluded (it records a timestamp). After an INTENTIONAL behaviour change, regenerate
the goldens deliberately and review the diff:

    GOLDEN_REGEN=1 uv run pytest tests/e2e/test_golden.py -q
"""
import json
import os
from pathlib import Path

import pandas as pd
import pytest

from ofh_feasibility import pipeline
from ofh_feasibility.config import Config
from ofh_feasibility.models import VariantRequest

pytestmark = pytest.mark.e2e

GOLDEN = Path(__file__).parent.parent / "fixtures" / "golden"
CPRA = "10:119669928:C:G"
_MANIFEST_ROW = {
    "cpra": CPRA, "chrom": "10", "pos": "119669928", "ref": "C", "alt": "G", "build": "GRCh38",
    "biallelic": "TRUE", "on_array": "TRUE", "on_imputed": "TRUE", "array_maf": "0.013",
    "imputed_maf": "0.014", "dosage_r2": "0.71", "annotation": "bag3",
    "inaccurate_annotation": "FALSE", "multiallelic_variant": "FALSE",
}


def _cfg(data, results):
    return Config.from_dict(dict(
        array_call_rate_min=0.98, array_gq_min=20, imputed_info_min=0.30,
        imputed_info_high_confidence=0.80, imputed_dosage_carrier_threshold=0.5,
        imputed_max_gp_min=0.90, carrier_definition="het_and_homalt", require_consent=True,
        sdc_min_cell=10, sdc_round_to=5, data_dir=str(data), results_dir=str(results),
    ))


def _write_inputs(d, tiny_cohort):
    tiny_cohort["participants"].to_parquet(d / "participant_table.parquet", index=False)
    tiny_cohort["genotype_slice"].to_parquet(d / "genotype_slice.parquet", index=False)
    tiny_cohort["sample_qc"].to_csv(d / "sample_qc_metrics.tsv", sep="\t", index=False)
    pd.DataFrame([tiny_cohort["request"]]).to_csv(d / "variant_request.csv", index=False)
    pd.DataFrame([_MANIFEST_ROW]).to_csv(d / "variant_manifest.csv", index=False)


def _produced(results: Path) -> dict:
    manifest = json.loads((results / "airlock_manifest.json").read_text())
    return {
        "feasibility_summary.txt": (results / "feasibility_summary.txt").read_text(),
        "handoff_to_epi.csv": (results / "handoff_to_epi.csv").read_text(),
        "internal_carrier_table.csv":
            pd.read_parquet(results / "internal_carrier_table.parquet").to_csv(index=False),
        "airlock_manifest.json": json.dumps(manifest, indent=2, sort_keys=True),
        # the canonical release payload: exact Lean-emitted bytes staged for egress
        "release.json": (results / "airlock_pending" / "release.json").read_text(),
    }


def test_golden_outputs(tmp_path, tiny_cohort):
    data = tmp_path / "synthetic"
    data.mkdir()
    _write_inputs(data, tiny_cohort)
    results = tmp_path / "results"
    pipeline.orchestrate(_cfg(data, results), VariantRequest.from_dict(tiny_cohort["request"]))
    produced = _produced(results)

    if os.environ.get("GOLDEN_REGEN"):
        GOLDEN.mkdir(parents=True, exist_ok=True)
        for name, text in produced.items():
            (GOLDEN / name).write_text(text)
        pytest.skip("regenerated golden files (review the git diff before committing)")

    for name, text in produced.items():
        expected = (GOLDEN / name).read_text()
        assert text == expected, f"golden mismatch in {name} — regenerate with GOLDEN_REGEN=1"
