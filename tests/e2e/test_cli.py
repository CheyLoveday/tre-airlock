"""E2E: the `ofh-feasibility` CLI runs a request end-to-end and emits the outputs + report."""

import pandas as pd
import pytest

from ofh_feasibility import cli

pytestmark = pytest.mark.e2e

CPRA = "10:119669928:C:G"
_MANIFEST_ROW = {
    "cpra": CPRA,
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
_CONFIG = """\
array_call_rate_min: 0.98
array_gq_min: 20
imputed_dr2_min: 0.30
imputed_dr2_high_confidence: 0.80
imputed_dosage_carrier_threshold: 0.5
imputed_max_gp_min: 0.90
carrier_definition: het_and_homalt
require_consent: true
sdc_min_cell: 10
sdc_round_to: 5
data_dir: {data}
results_dir: {results}
"""


def _write_dataset(tmp_path, tiny_cohort):
    data = tmp_path / "synthetic"
    data.mkdir()
    tiny_cohort["participants"].to_parquet(data / "participant_table.parquet", index=False)
    tiny_cohort["genotype_slice"].to_parquet(data / "genotype_slice.parquet", index=False)
    tiny_cohort["sample_qc"].to_csv(data / "sample_qc_metrics.tsv", sep="\t", index=False)
    pd.DataFrame([tiny_cohort["request"]]).to_csv(data / "variant_request.csv", index=False)
    pd.DataFrame([_MANIFEST_ROW]).to_csv(data / "variant_manifest.csv", index=False)
    results = tmp_path / "results"
    cfg_path = tmp_path / "config.yaml"
    cfg_path.write_text(_CONFIG.format(data=data, results=results))
    return cfg_path, results


def test_cli_run_emits_outputs_and_receipt_only(tmp_path, tiny_cohort, capsys):
    cfg_path, results = _write_dataset(tmp_path, tiny_cohort)
    cli.main(["run", "--config", str(cfg_path)])
    for name in (
        "feasibility_summary.txt",
        "handoff_to_epi.csv",
        "airlock_manifest.json",
        "internal_carrier_table.parquet",
    ):
        assert (results / name).exists(), name
    # the production release command prints the COMMITTED RECEIPT, never Python-rendered figures.
    out = capsys.readouterr().out
    assert "release: committed" in out
    assert "payload_sha256:" in out and "adjudicator_sha256:" in out and "policy:" in out
    assert "RECOMMENDATION" not in out and "client figure" not in out
    assert "GO" not in out.replace("GOVERNED", "")  # no decision text on the release surface


def test_cli_notes_is_the_explicitly_internal_surface(tmp_path, tiny_cohort, capsys):
    cfg_path, results = _write_dataset(tmp_path, tiny_cohort)
    cli.main(["run", "--config", str(cfg_path)])
    capsys.readouterr()
    cli.main(["notes", "--config", str(cfg_path)])
    out = capsys.readouterr().out
    assert "INTERNAL-TRE-ONLY" in out
    assert "RECOMMENDATION" in out  # the analyst note, shown only behind the internal banner


def test_cli_run_uses_configured_request_path(tmp_path, tiny_cohort):
    cfg_path, results = _write_dataset(tmp_path, tiny_cohort)
    request = {**tiny_cohort["request"], "study_id": "OFH-CONFIGURED-REQUEST"}
    request_path = tmp_path / "configured_request.csv"
    pd.DataFrame([request]).to_csv(request_path, index=False)
    cfg_path.write_text(cfg_path.read_text() + f"request_path: {request_path}\n")

    cli.main(["run", "--config", str(cfg_path)])

    summary = (results / "feasibility_summary.txt").read_text()
    assert "OFH-CONFIGURED-REQUEST" in summary


def test_cli_finalize_eligible_writes_final_summary(tmp_path, tiny_cohort):
    import json

    cfg_path, results = _write_dataset(tmp_path, tiny_cohort)
    cli.main(["run", "--config", str(cfg_path)])
    run_id = json.loads((results / "epi_notification.json").read_text())["run_id"]
    epi_return = tmp_path / "epi_return.json"
    epi_return.write_text(json.dumps(dict(
        study_id=tiny_cohort["request"]["study_id"], cpra=CPRA,
        run_id=run_id, eligible_count=2,
        phenotype_definition_id="PD-HEART-1", icd10_codeset_label="ICD10-HD",
        icd10_codeset_version="2026-01", linked_record_scope="primary_care", reviewer="Dr Epi",
        return_timestamp="2026-06-09T10:00:00", sign_off_status="signed",
    )))
    cli.main(["finalize-eligible", "--config", str(cfg_path), "--epi-return", str(epi_return)])
    summary = (results / "final_feasibility_summary.txt").read_text()
    assert "POST-PHENOTYPE ELIGIBLE CARRIERS (the FINAL figure)" in summary
    assert (results / "final_release_candidate.json").exists()


def test_cli_unknown_template_exits(tmp_path, tiny_cohort):
    cfg_path, _ = _write_dataset(tmp_path, tiny_cohort)
    with pytest.raises(SystemExit):
        cli.main(["run", "--template", "nope", "--config", str(cfg_path)])


def test_cli_gene_uses_configured_catalog(tmp_path, tiny_cohort):
    cfg_path, _ = _write_dataset(tmp_path, tiny_cohort)
    catalog = tmp_path / "catalog.yaml"
    catalog.write_text(f"""\
variants:
  bag3_demo:
    cpra: "{CPRA}"
    chrom: "10"
    pos: 119669928
    ref: "C"
    alt: "G"
genes:
  BAG3:
    chrom: "10"
    start: 119651500
    end: 119677900
    variants: ["bag3_demo"]
panels:
  cardiomyopathy:
    genes: ["BAG3"]
""")
    results = tmp_path / "gene_results"

    cli.main([
        "gene",
        "--symbol",
        "BAG3",
        "--config",
        str(cfg_path),
        "--variant-catalog",
        str(catalog),
        "--results-dir",
        str(results),
    ])

    summary = (results / "batch_feasibility_summary.txt").read_text()
    assert (
        "Study: OFH-CRRS-DEMO-BAG3-GENE | purpose: Recontact feasibility: BAG3 carriers"
        in summary
    )
    assert "Variants assessed: 1" in summary
    assert "CHEK2" not in summary
    assert (results / "batch_airlock_manifest.json").exists()

    disease_results = tmp_path / "disease_results"
    cli.main([
        "disease",
        "--panel",
        "cardiomyopathy",
        "--config",
        str(cfg_path),
        "--variant-catalog",
        str(catalog),
        "--results-dir",
        str(disease_results),
    ])

    disease_summary = (disease_results / "batch_feasibility_summary.txt").read_text()
    assert (
        "Study: OFH-CRRS-DEMO-CARDIOMYOPATHY-PANEL | purpose: "
        "Recontact feasibility: cardiomyopathy panel carriers"
    ) in disease_summary
    assert "breast-cancer" not in disease_summary
    assert "CHEK2" not in disease_summary
    assert (disease_results / "batch_airlock_manifest.json").exists()
