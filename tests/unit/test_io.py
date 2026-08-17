"""Unit tests for io readers/writers (self-contained; write to tmp_path, read back)."""
import json

import pandas as pd
import pytest

from ofh_feasibility import io
from ofh_feasibility.models import VariantRequest

pytestmark = pytest.mark.unit

REQUEST = dict(
    study_id="S1", cpra="10:119669928:C:G", chrom="10", pos="119669928", ref="C", alt="G",
    build="GRCh38", carrier_definition="het_and_homalt", requested_source="array_and_imputed",
    purpose="demo",
)


def _write_dataset(d):
    """Write a minimal valid OFH-shaped dataset into directory d."""
    pd.DataFrame([REQUEST]).to_csv(d / "variant_request.csv", index=False)
    pd.DataFrame({
        "cpra": ["10:119669928:C:G"], "chrom": ["10"], "pos": ["119669928"], "ref": ["C"],
        "alt": ["G"], "build": ["GRCh38"], "biallelic": ["TRUE"], "on_array": ["TRUE"],
        "on_imputed": ["TRUE"], "array_maf": ["0.013"], "imputed_maf": ["0.014"],
        "dosage_r2": ["0.71"], "annotation": ["bag3"],
        "inaccurate_annotation": ["FALSE"], "multiallelic_variant": ["FALSE"],
    }).to_csv(d / "variant_manifest.csv", index=False)
    pd.DataFrame({
        "participant_id": ["OFH1"], "pseudo_id": ["PSU-1"], "sex": ["F"], "ancestry_stub": ["EUR"],
        "consent_status": ["consented"], "baseline_qc_pass": [True],
    }).to_parquet(d / "participant_table.parquet", index=False)
    pd.DataFrame({
        "participant_id": ["OFH1"], "cpra": ["10:119669928:C:G"], "source": ["array"],
        "gt_code": [1], "gq": [40], "call_rate": [0.99], "dosage": [float("nan")],
        "max_gp": [float("nan")],
    }).to_parquet(d / "genotype_slice.parquet", index=False)
    pd.DataFrame({
        "participant_id": ["OFH1"], "array_call_rate": [0.99], "het_rate": [0.25],
        "sex_check_pass": [True], "ancestry_pc1": [0.0], "ancestry_pc2": [0.0],
        "kinship_flag": [False],
    }).to_csv(d / "sample_qc_metrics.tsv", sep="\t", index=False)


def test_read_request_csv_parses_and_validates(tmp_path):
    pd.DataFrame([REQUEST]).to_csv(tmp_path / "r.csv", index=False)
    req = io.read_request(tmp_path / "r.csv")
    assert isinstance(req, VariantRequest)
    assert req.pos == 119669928 and req.chrom == "10" and req.cpra == "10:119669928:C:G"


def test_read_request_csv_rejects_multirow_input(tmp_path):
    pd.DataFrame([REQUEST, {**REQUEST, "study_id": "S2"}]).to_csv(
        tmp_path / "r.csv", index=False
    )
    with pytest.raises(ValueError, match="exactly one row"):
        io.read_request(tmp_path / "r.csv")


def test_read_request_json(tmp_path):
    (tmp_path / "r.json").write_text(json.dumps({**REQUEST, "pos": 119669928}))
    assert io.read_request(tmp_path / "r.json").requested_source == "array_and_imputed"


def test_readers_happy_path(tmp_path):
    _write_dataset(tmp_path)
    assert io.read_variant_manifest(tmp_path).loc[0, "dosage_r2"] == "0.71"
    assert io.read_participants(tmp_path).loc[0, "participant_id"] == "OFH1"
    assert io.read_genotype_slice(tmp_path).loc[0, "gt_code"] == 1
    assert io.read_sample_qc(tmp_path).loc[0, "sex_check_pass"]


def test_read_variant_identifiability_validates_schema(tmp_path):
    p = tmp_path / "variant-identifiability.csv"
    pd.DataFrame(
        [
            {
                "cpra": REQUEST["cpra"],
                "on_array": "TRUE",
                "on_imputed": "FALSE",
                "annotation_reliable": "TRUE",
                "source_release": "OFH public Release 14",
                "evidence": "array present; imputed absent",
            }
        ]
    ).to_csv(p, index=False)
    assert io.read_variant_identifiability(p).loc[0, "on_array"] == "TRUE"


def test_reader_rejects_missing_columns(tmp_path):
    pd.DataFrame({"participant_id": ["OFH1"]}).to_parquet(
        tmp_path / "participant_table.parquet", index=False
    )
    with pytest.raises(ValueError, match="participants missing columns"):
        io.read_participants(tmp_path)


def test_write_round_trips(tmp_path):
    df = pd.DataFrame({"a": [1, 2], "b": ["x", "y"]})
    io.write_parquet(df, tmp_path / "sub" / "t.parquet")  # nested dir created
    io.write_csv(df, tmp_path / "t.csv")
    io.write_text("hello", tmp_path / "t.txt")
    io.write_json({"k": 1}, tmp_path / "t.json")
    pd.testing.assert_frame_equal(pd.read_parquet(tmp_path / "sub" / "t.parquet"), df)
    pd.testing.assert_frame_equal(pd.read_csv(tmp_path / "t.csv"), df)
    assert (tmp_path / "t.txt").read_text() == "hello"
    assert json.loads((tmp_path / "t.json").read_text()) == {"k": 1}
