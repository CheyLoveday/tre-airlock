"""Integration tests for the notebook companion shell."""

import pandas as pd
import pytest

from ofh_feasibility import io, notebook, pipeline

pytestmark = pytest.mark.integration


def _write_input_files(tmp_path, tiny_cohort):
    data = tmp_path / "data"
    results = tmp_path / "results"
    data.mkdir()
    pd.DataFrame([tiny_cohort["request"]]).to_csv(data / "variant_request.csv", index=False)
    pd.DataFrame(
        [
            {
                "cpra": tiny_cohort["request"]["cpra"],
                "chrom": "10",
                "pos": "119669928",
                "ref": "C",
                "alt": "G",
                "build": "GRCh38",
                "biallelic": "TRUE",
                "on_array": "TRUE",
                "on_imputed": "TRUE",
                "array_maf": "0.013",
                "imputed_maf": "0.014",
                "dosage_r2": "0.71",
                "annotation": "bag3",
                "inaccurate_annotation": "FALSE",
                "multiallelic_variant": "FALSE",
            }
        ]
    ).to_csv(data / "variant_manifest.csv", index=False)
    tiny_cohort["participants"].to_parquet(data / "participant_table.parquet", index=False)
    tiny_cohort["genotype_slice"].to_parquet(data / "genotype_slice.parquet", index=False)
    tiny_cohort["sample_qc"].to_csv(data / "sample_qc_metrics.tsv", sep="\t", index=False)
    cfg = tmp_path / "config.yaml"
    cfg.write_text(
        "\n".join(
            [
                "array_call_rate_min: 0.98",
                "array_gq_min: 20",
                "imputed_info_min: 0.30",
                "imputed_info_high_confidence: 0.80",
                "imputed_dosage_carrier_threshold: 0.5",
                "imputed_max_gp_min: 0.90",
                "carrier_definition: het_and_homalt",
                "require_consent: true",
                "sdc_min_cell: 10",
                "sdc_round_to: 5",
                f"data_dir: {data}",
                f"results_dir: {results}",
            ]
        )
    )
    return cfg, results


def test_notebook_run_uses_same_pipeline_and_records_actor_type(tmp_path, tiny_cohort):
    cfg, results = _write_input_files(tmp_path, tiny_cohort)
    bundle = notebook.run(cfg)
    assert bundle["result"].client_total == "<10"
    assert notebook.report(bundle)["governance"]["audit_actor_type"] == "notebook"
    events = io.read_jsonl(results / pipeline.AUDIT_LEDGER)
    assert events[-1]["actor_type"] == "notebook"
