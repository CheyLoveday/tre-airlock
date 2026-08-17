"""Unit tests for the Wave 9 OFH real-format readers (pVCF / summary-stats -> our schema).

These exercise genuine bgzip VCFs via pysam (the local-only `ofhgen` extra); skipped when pysam is
absent (e.g. the default CI install), so the allowlist-clean suite is unaffected.
"""
import os
import tempfile

import pytest

pysam = pytest.importorskip("pysam")

from ofh_feasibility import ofh_formats  # noqa: E402
from ofh_feasibility.models import GENOTYPE_SLICE_COLUMNS, VARIANT_MANIFEST_COLUMNS  # noqa: E402

pytestmark = pytest.mark.unit

CPRA = "10:119669928:C:G"

_ARRAY_VCF = """\
##fileformat=VCFv4.1
##reference=GRCh38
##FORMAT=<ID=GT,Number=1,Type=String,Description="Genotype">
##contig=<ID=10>
#CHROM\tPOS\tID\tREF\tALT\tQUAL\tFILTER\tINFO\tFORMAT\tP0\tP1\tP2\tP3
10\t119669928\t10:119669928:C:G\tC\tG\t.\t.\t.\tGT\t0/0\t0/1\t1/1\t./.
"""

_IMPUTED_VCF = """\
##fileformat=VCFv4.2
##reference=GRCh38
##FORMAT=<ID=GT,Number=1,Type=String,Description="Genotype">
##FORMAT=<ID=GP,Number=G,Type=Float,Description="Genotype posterior probabilities">
##contig=<ID=10>
#CHROM\tPOS\tID\tREF\tALT\tQUAL\tFILTER\tINFO\tFORMAT\tP0\tP1
10\t119669928\t10:119669928:C:G\tC\tG\t.\t.\t.\tGT:GP\t0/0:0.97,0.03,0.0\t0/1:0.05,0.9,0.05
"""

_SUMMARY_VCF = """\
##fileformat=VCFv4.2
##reference=GRCh38
##INFO=<ID=DR2,Number=1,Type=Float,Description="Dosage r-squared">
##INFO=<ID=AF,Number=A,Type=Float,Description="ALT allele frequency">
##INFO=<ID=PROP_TYPED,Number=1,Type=Float,Description="Proportion directly typed">
##contig=<ID=10>
#CHROM\tPOS\tID\tREF\tALT\tQUAL\tFILTER\tINFO
10\t119669928\t10:119669928:C:G\tC\tG\t.\t.\tDR2=0.71;AF=0.014;PROP_TYPED=1.0
"""

_EMPTY_SUMMARY_VCF = """\
##fileformat=VCFv4.2
##reference=GRCh38
##INFO=<ID=DR2,Number=1,Type=Float,Description="Dosage r-squared">
##INFO=<ID=AF,Number=A,Type=Float,Description="ALT allele frequency">
##INFO=<ID=PROP_TYPED,Number=1,Type=Float,Description="Proportion directly typed">
##contig=<ID=10>
#CHROM\tPOS\tID\tREF\tALT\tQUAL\tFILTER\tINFO
"""


def _bgzip(text: str, path_gz) -> None:
    """Write VCF text as a real bgzip .vcf.gz (the on-disk OFH format), like the generator does."""
    with tempfile.NamedTemporaryFile("w", suffix=".vcf", delete=False) as tmp:
        tmp.write(text)
        tmp_path = tmp.name
    pysam.tabix_compress(tmp_path, str(path_gz), force=True)
    os.unlink(tmp_path)


def test_parse_array_pvcf_maps_gt_to_gt_code(tmp_path):
    p = tmp_path / "a.vcf.gz"
    _bgzip(_ARRAY_VCF, p)
    df = ofh_formats.parse_array_pvcf(p)
    codes = dict(zip(df["participant_id"], df["gt_code"], strict=True))
    assert codes == {"P0": 0, "P1": 1, "P2": 2, "P3": -1}
    assert set(df["cpra"]) == {CPRA}


@pytest.mark.parametrize(
    ("filename", "text", "reader"),
    [
        ("a.vcf.gz", _ARRAY_VCF, ofh_formats.parse_array_pvcf),
        ("i.vcf.gz", _IMPUTED_VCF, ofh_formats.parse_imputed_pvcf),
        (
            "ofh_imputed_variant_summary_stats.v6.vcf.gz",
            _SUMMARY_VCF,
            lambda p, cpra, **kw: ofh_formats.read_ofh_variant_summary_stats(
                p.parent, cpra, **kw
            ),
        ),
    ],
)
def test_cpra_fetch_requires_index_unless_fixture_fallback_enabled(
    tmp_path, filename, text, reader
):
    p = tmp_path / filename
    _bgzip(text, p)
    with pytest.raises(ValueError, match="requires a tabix-indexed VCF"):
        reader(p, CPRA)
    df = reader(p, CPRA, allow_full_scan_fallback=True)
    assert set(df["cpra"]) == {CPRA}


def test_parse_imputed_pvcf_computes_dosage_and_max_gp(tmp_path):
    p = tmp_path / "i.vcf.gz"
    _bgzip(_IMPUTED_VCF, p)
    df = ofh_formats.parse_imputed_pvcf(p).set_index("participant_id")
    # dosage = GP_RA + 2*GP_AA ; P0: 0.03 ; P1: 0.9+0.1 = 1.0
    assert df.loc["P0", "dosage"] == pytest.approx(0.03)
    assert df.loc["P1", "dosage"] == pytest.approx(1.0)
    assert df.loc["P0", "max_gp"] == pytest.approx(0.97)


def test_read_summary_stats_maps_info_to_manifest_schema(tmp_path):
    _bgzip(_SUMMARY_VCF, tmp_path / "ofh_imputed_variant_summary_stats.v6.vcf.gz")
    df = ofh_formats.read_ofh_variant_summary_stats(tmp_path)
    row = df.iloc[0]
    assert set(VARIANT_MANIFEST_COLUMNS).issubset(df.columns)
    assert row["cpra"] == CPRA
    assert float(row["dosage_r2"]) == pytest.approx(0.71)
    assert float(row["imputed_maf"]) == pytest.approx(0.014)
    assert row["on_imputed"] == "TRUE" and row["on_array"] == "TRUE"  # PROP_TYPED=1.0 > 0


def test_read_ofh_variant_manifest_includes_array_only_variant(tmp_path):
    _bgzip(_ARRAY_VCF, tmp_path / "ofh_snv.chr10-b0001.vcf.gz")
    _bgzip(_EMPTY_SUMMARY_VCF, tmp_path / "ofh_imputed_variant_summary_stats.v6.vcf.gz")

    df = ofh_formats.read_ofh_variant_manifest(tmp_path)
    row = df.iloc[0]

    assert row["cpra"] == CPRA
    assert row["on_array"] == "TRUE"
    assert row["on_imputed"] == "FALSE"
    assert row["dosage_r2"] == "NA"
    assert float(row["array_maf"]) == pytest.approx(0.5)


def test_genotype_source_yields_schema_valid_slice(tmp_path):
    _bgzip(_ARRAY_VCF, tmp_path / "ofh_snv.chr10-b0001.vcf.gz")
    _bgzip(_IMPUTED_VCF, tmp_path / "ofh_imputed.v6.chr10-b0001.vcf.gz")
    (tmp_path / "ofh_sample_qc_metrics.tsv").write_text(
        "participant_id\tgenotyping_batch\tmanifest_version\testimated_genetic_sex\tcall_rate\t"
        "het_rate\tsex_check_pass\tancestry_pc1\tancestry_pc2\tkinship_flag\n"
        "P0\tB1\tv2\tM\t0.99\t0.25\tTrue\t0.0\t0.0\tFalse\n"
        "P1\tB1\tv2\tF\t0.99\t0.25\tTrue\t0.0\t0.0\tFalse\n"
        "P2\tB1\tv2\tM\t0.99\t0.25\tTrue\t0.0\t0.0\tFalse\n"
        "P3\tB1\tv2\tF\t0.99\t0.25\tTrue\t0.0\t0.0\tFalse\n"
    )
    slice_df = ofh_formats.OfhTreGenotypeSource(tmp_path).read_slice()
    assert list(slice_df.columns) == list(GENOTYPE_SLICE_COLUMNS)
    array = slice_df[slice_df["source"] == "array"]
    assert (array["gq"] == 99).all()  # OFH array pVCF has no GQ -> passing sentinel
    assert array.set_index("participant_id").loc["P0", "call_rate"] == 0.99  # sample-level join
