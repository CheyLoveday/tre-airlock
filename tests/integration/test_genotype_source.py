"""Integration: the VCF/BGEN-shaped GenotypeSource yields the same slice (and the same pipeline
result) as the CSV/Parquet stand-in — the DAG is the contract, not the file shape."""
import pandas as pd
import pytest

from ofh_feasibility import io, pipeline
from ofh_feasibility.config import Config
from ofh_feasibility.models import VariantRequest

pytestmark = pytest.mark.integration

CPRA = "10:119669928:C:G"
_VCF = {0: "0/0", 1: "0/1", 2: "1/1", -1: "./."}
_MANIFEST_ROW = {
    "cpra": CPRA, "chrom": "10", "pos": "119669928", "ref": "C", "alt": "G", "build": "GRCh38",
    "biallelic": "TRUE", "on_array": "TRUE", "on_imputed": "TRUE", "array_maf": "0.013",
    "imputed_maf": "0.014", "dosage_r2": "0.71", "annotation": "bag3",
    "inaccurate_annotation": "FALSE", "multiallelic_variant": "FALSE",
}


def _gp(dosage, max_gp):
    idx = min(2, max(0, int(round(dosage))))
    triple = [0.0, 0.0, 0.0]
    triple[idx] = max_gp
    triple[1 if idx != 1 else 0] = round(1.0 - max_gp, 3)
    return triple


def _write_genotype_both_shapes(d, slice_df):
    """Write the long-form Parquet AND the derived vcf/bgen-shaped TSVs for the same genotypes."""
    slice_df.to_parquet(d / "genotype_slice.parquet", index=False)
    arr = slice_df[slice_df["source"] == "array"]
    pd.DataFrame({
        "participant_id": arr["participant_id"], "cpra": arr["cpra"],
        "gt": arr["gt_code"].astype(int).map(_VCF), "gq": arr["gq"], "call_rate": arr["call_rate"],
    }).to_csv(d / "array_calls_vcf.tsv", sep="\t", index=False)
    imp = slice_df[slice_df["source"] == "imputed"]
    gps = [_gp(dz, mz) for dz, mz in zip(imp["dosage"], imp["max_gp"], strict=True)]
    pd.DataFrame({
        "participant_id": imp["participant_id"], "cpra": imp["cpra"], "dosage": imp["dosage"],
        "gp_00": [g[0] for g in gps], "gp_01": [g[1] for g in gps], "gp_11": [g[2] for g in gps],
    }).to_csv(d / "imputed_calls_bgen.tsv", sep="\t", index=False)


def _cfg(data, results):
    return Config.from_dict(dict(
        array_call_rate_min=0.98, array_gq_min=20, imputed_info_min=0.30,
        imputed_info_high_confidence=0.80, imputed_dosage_carrier_threshold=0.5,
        imputed_max_gp_min=0.90, carrier_definition="het_and_homalt", require_consent=True,
        sdc_min_cell=10, sdc_round_to=5, data_dir=str(data), results_dir=str(results),
    ))


@pytest.fixture
def dataset(tmp_path, tiny_cohort):
    data = tmp_path / "synthetic"
    data.mkdir()
    _write_genotype_both_shapes(data, tiny_cohort["genotype_slice"])
    tiny_cohort["participants"].to_parquet(data / "participant_table.parquet", index=False)
    tiny_cohort["sample_qc"].to_csv(data / "sample_qc_metrics.tsv", sep="\t", index=False)
    pd.DataFrame([tiny_cohort["request"]]).to_csv(data / "variant_request.csv", index=False)
    pd.DataFrame([_MANIFEST_ROW]).to_csv(data / "variant_manifest.csv", index=False)
    return tmp_path, data


_KEY_COLS = ["participant_id", "source", "gt_code", "gq", "call_rate", "dosage", "max_gp"]


def _sorted_key(df):
    return df.sort_values(["participant_id", "source"]).reset_index(drop=True)[_KEY_COLS]


def test_vcf_bgen_source_yields_same_slice(dataset):
    _, data = dataset
    csv = io.CsvGenotypeSource(data).read_slice()
    vcf = io.VcfBgenShapedGenotypeSource(data).read_slice()
    pd.testing.assert_frame_equal(_sorted_key(csv), _sorted_key(vcf), check_dtype=False)


def test_pipeline_runs_through_vcf_bgen_source(dataset, tiny_cohort):
    tmp_path, data = dataset
    request = VariantRequest.from_dict(tiny_cohort["request"])
    csv_b = pipeline.orchestrate(_cfg(data, tmp_path / "csv"), request, io.CsvGenotypeSource(data))
    vcf_b = pipeline.orchestrate(
        _cfg(data, tmp_path / "vcf"), request, io.VcfBgenShapedGenotypeSource(data)
    )
    assert csv_b["cells"] == vcf_b["cells"]
    assert csv_b["summary"] == vcf_b["summary"]
    assert (tmp_path / "vcf" / "feasibility_summary.txt").exists()
