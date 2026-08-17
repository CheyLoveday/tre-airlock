#!/usr/bin/env python3
"""Transcode the simplified synthetic data into OFH-format stand-in files (Wave 9).

Reads data/synthetic/{genotype_slice.parquet, variant_manifest.csv, sample_qc_metrics.tsv,
participant_table.parquet} and re-emits the same synthetic cohort in the public OFH file-shape
documented in docs/reference/ofh_tre_genetic_file_formats.md: per-region pVCF (array GT-only
VCFv4.1; imputed GT:GP VCFv4.2), the variant summary-statistics VCF (INFO DR2/AF/...), the array +
imputed sample-QC TSVs, Oxford .sample files, kinship.txt and regions.bed.

This generator is offline scaffolding (NOT the TRE runtime), so it uses htslib via pysam to write
valid bgzip-compressed .vcf.gz files plus tabix .tbi indexes. The data are synthetic. The files are
stand-ins for the public OFH file mechanics, not a claim of exact private TRE contents. Requires the
`ofhgen` extra (pysam) — local/dev only, never a TRE runtime dependency.

Note: the real OFH array pVCF carries GT only (no per-genotype GQ); QC is sample-level call-rate
from the sample-QC TSV — so array GQ has no real OFH source (the Wave 9 readers reconstruct a
passing sentinel for our QC step).

    uv sync --extra ofhgen
    uv run python scripts/generate_ofh_files.py --in data/synthetic --out data/synthetic/ofh_tre
"""

from __future__ import annotations

import argparse
import os
import tempfile
from pathlib import Path

import pandas as pd
import pysam

_CODE_TO_GT = {0: "0/0", 1: "0/1", 2: "1/1", -1: "./."}
_REGION = "b0001"  # one demo region (chr10); the chrZ-bXXXX scheme generalises
_NOTE = "##source=synthetic_OFH_format_demo_fake_people_public_shape_standin_see_WAVE_9_plan"


def _chrom_key(chrom: str) -> tuple[int, str]:
    return (0, f"{int(chrom):02d}") if str(chrom).isdigit() else (1, str(chrom))


def _chrom_rank(chrom: str) -> int:
    if str(chrom).isdigit():
        return int(chrom)
    return {"X": 23, "Y": 24, "MT": 25}.get(str(chrom), 99)


def _sort_locus(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return df
    ranked = df.copy()
    ranked["_chrom_rank"] = ranked["chrom"].astype(str).map(_chrom_rank)
    ranked["_pos_rank"] = ranked["pos"].astype(int)
    ranked = ranked.sort_values(["_chrom_rank", "_pos_rank", "cpra"])
    return ranked.drop(columns=["_chrom_rank", "_pos_rank"])


def _contig_headers(df: pd.DataFrame) -> list[str]:
    chroms = sorted({str(c) for c in df["chrom"].dropna().unique()}, key=_chrom_key)
    return [f"##contig=<ID={chrom}>" for chrom in chroms]


def _write_bgzipped_vcf(lines: list[str], path_gz: Path) -> None:
    """Write VCF text as valid bgzip .vcf.gz + tabix .tbi via htslib."""
    with tempfile.NamedTemporaryFile("w", suffix=".vcf", delete=False) as tmp:
        tmp.write("\n".join(lines) + "\n")
        tmp_path = tmp.name
    try:
        pysam.tabix_compress(tmp_path, str(path_gz), force=True)
        pysam.tabix_index(str(path_gz), preset="vcf", force=True)
    finally:
        os.unlink(tmp_path)


def _gp_triplet(dosage: float, max_gp: float) -> list[float]:
    """A GP triplet (P(RR),P(RA),P(AA)) whose max == max_gp and modal index ~ dosage."""
    idx = min(2, max(0, int(round(dosage))))
    t = [0.0, 0.0, 0.0]
    t[idx] = round(max_gp, 3)
    t[1 if idx != 1 else 0] = round(1.0 - max_gp, 3)  # remainder on a non-modal genotype
    return [round(x, 3) for x in t]


def _variant_meta(manifest: pd.DataFrame) -> list[dict]:
    """One dict per variant (cpra, chrom, pos, ref, alt) for the VCF #CHROM..ALT columns."""
    return manifest[["cpra", "chrom", "pos", "ref", "alt"]].to_dict("records")


def write_array_pvcf(slice_df: pd.DataFrame, out: Path) -> None:
    """ofh_snv.chr10-b0001.vcf.gz — array pVCF, VCFv4.1, FORMAT=GT only (no GQ, per OFH)."""
    arr = slice_df[slice_df["source"] == "array"]
    samples = sorted(arr["participant_id"].unique())
    gt_by = {(r.participant_id, r.cpra): _CODE_TO_GT[int(r.gt_code)] for r in arr.itertuples()}
    variants = _sort_locus(arr.drop_duplicates("cpra"))
    lines = [
        "##fileformat=VCFv4.1",
        "##reference=GRCh38",
        *_contig_headers(variants),
        _NOTE,
        '##FORMAT=<ID=GT,Number=1,Type=String,Description="Genotype">',
    ]
    header_cols = ["CHROM", "POS", "ID", "REF", "ALT", "QUAL", "FILTER", "INFO"]
    if samples:
        header_cols += ["FORMAT", *samples]
    lines.append("#" + "\t".join(header_cols))
    for v in variants.itertuples():
        calls = [gt_by.get((s, v.cpra), "./.") for s in samples]
        lines.append("\t".join(
            [str(v.chrom), str(v.pos), v.cpra, v.ref, v.alt, ".", ".", ".", "GT", *calls]
        ))
    _write_bgzipped_vcf(lines, out / "ofh_snv.chr10-b0001.vcf.gz")


def write_imputed_pvcf(slice_df: pd.DataFrame, out: Path) -> None:
    """ofh_imputed.v6.chr10-b0001.vcf.gz — imputed pVCF, VCFv4.2, FORMAT=GT:GP."""
    imp = slice_df[slice_df["source"] == "imputed"]
    samples = sorted(imp["participant_id"].unique())
    rows = {(r.participant_id, r.cpra): (r.dosage, r.max_gp) for r in imp.itertuples()}
    variants = _sort_locus(imp.drop_duplicates("cpra"))
    lines = [
        "##fileformat=VCFv4.2",
        "##reference=GRCh38",
        *_contig_headers(variants),
        _NOTE,
        '##FORMAT=<ID=GT,Number=1,Type=String,Description="Genotype">',
        '##FORMAT=<ID=GP,Number=G,Type=Float,Description="Genotype posterior probabilities">',
    ]
    header_cols = ["CHROM", "POS", "ID", "REF", "ALT", "QUAL", "FILTER", "INFO"]
    if samples:
        header_cols += ["FORMAT", *samples]
    lines.append("#" + "\t".join(header_cols))
    for v in variants.itertuples():
        calls = []
        for s in samples:
            dosage, max_gp = rows.get((s, v.cpra), (0.0, 1.0))
            gp = _gp_triplet(dosage, max_gp)
            gt = _CODE_TO_GT[min(2, max(0, int(round(dosage))))]
            calls.append(f"{gt}:{gp[0]},{gp[1]},{gp[2]}")
        lines.append("\t".join(
            [str(v.chrom), str(v.pos), v.cpra, v.ref, v.alt, ".", ".", ".", "GT:GP", *calls]
        ))
    _write_bgzipped_vcf(lines, out / "ofh_imputed.v6.chr10-b0001.vcf.gz")


def write_variant_summary_stats(manifest: pd.DataFrame, out: Path) -> None:
    """ofh_imputed_variant_summary_stats.v6.vcf.gz — variant-level INFO only, no sample columns."""
    lines = [
        "##fileformat=VCFv4.2",
        "##reference=GRCh38",
        *_contig_headers(manifest),
        _NOTE,
        '##INFO=<ID=DR2,Number=1,Type=Float,Description="Dosage r-squared">',
        '##INFO=<ID=AF,Number=A,Type=Float,Description="ALT allele frequency">',
        '##INFO=<ID=RAF,Number=A,Type=Float,Description="REF allele frequency">',
        '##INFO=<ID=PROP_TYPED,Number=1,Type=Float,Description="Proportion directly typed">',
        "#" + "\t".join(["CHROM", "POS", "ID", "REF", "ALT", "QUAL", "FILTER", "INFO"]),
    ]
    for r in _sort_locus(manifest).itertuples():
        on_imp = str(r.on_imputed).upper() == "TRUE"
        if not on_imp:
            continue  # the summary-stats VCF lists imputed variants only
        dr2 = "." if r.dosage_r2 in ("NA", "", None) else r.dosage_r2
        af = "." if r.imputed_maf in ("NA", "", None) else r.imputed_maf
        raf = "." if af == "." else round(1.0 - float(af), 4)
        prop_typed = "1.0" if str(r.on_array).upper() == "TRUE" else "0.0"
        info = f"DR2={dr2};AF={af};RAF={raf};PROP_TYPED={prop_typed}"
        lines.append("\t".join([str(r.chrom), str(r.pos), r.cpra, r.ref, r.alt, ".", ".", info]))
    _write_bgzipped_vcf(lines, out / "ofh_imputed_variant_summary_stats.v6.vcf.gz")


def write_sample_qc(sample_qc: pd.DataFrame, participants: pd.DataFrame, out: Path) -> None:
    """ofh_sample_qc_metrics.tsv (array) + ofh_imputed_sample_qc_metrics.v6.tsv (imputed)."""
    sex = participants.set_index("participant_id")["sex"]
    base = pd.DataFrame({
        "participant_id": sample_qc["participant_id"],
        "genotyping_batch": "BATCH_DEMO_A01",
        "manifest_version": "v2",  # C2 manifest, all samples from Release 13 onward
        "estimated_genetic_sex": [
            "F" if sex.get(p, "M") == "F" else "M" for p in sample_qc["participant_id"]
        ],
        "call_rate": sample_qc["array_call_rate"],
        # preserved so the Wave 9 readers can reconstruct OUR existing sample-QC schema losslessly
        "het_rate": sample_qc["het_rate"],
        "sex_check_pass": sample_qc["sex_check_pass"],
        "ancestry_pc1": sample_qc["ancestry_pc1"],
        "ancestry_pc2": sample_qc["ancestry_pc2"],
        "kinship_flag": sample_qc["kinship_flag"],
    })
    base.to_csv(out / "ofh_sample_qc_metrics.tsv", sep="\t", index=False)
    imp = base.copy()
    imp.insert(2, "imputation_group", "IMPGRP_DEMO_01")
    imp.to_csv(out / "ofh_imputed_sample_qc_metrics.v6.tsv", sep="\t", index=False)


def write_sample_files(slice_df: pd.DataFrame, participants: pd.DataFrame, out: Path) -> None:
    """Oxford .sample files (ID_1 ID_2 missing sex) for the array + imputed regions."""
    sex = participants.set_index("participant_id")["sex"]
    for src, name in [("array", "ofh_snv.chr10-b0001.sample"),
                      ("imputed", "ofh_imputed.v6.chr10-b0001.sample")]:
        samples = sorted(slice_df[slice_df["source"] == src]["participant_id"].unique())
        rows = ["ID_1 ID_2 missing sex", "0 0 0 D"]
        for p in samples:
            rows.append(f"{p} {p} 0 {1 if sex.get(p, 'M') == 'M' else 2}")
        (out / name).write_text("\n".join(rows) + "\n")


def write_kinship(sample_qc: pd.DataFrame, out: Path) -> None:
    """ofh_snv_kinship.txt — pairwise kinship; flagged samples appear as a related pair."""
    flagged = sorted(sample_qc.loc[sample_qc["kinship_flag"].astype(bool), "participant_id"])
    lines = ["ID1\tID2\tKINSHIP"]
    for a, b in zip(flagged[0::2], flagged[1::2], strict=False):
        lines.append(f"{a}\t{b}\t0.25")  # ~1st-degree
    (out / "ofh_snv_kinship.txt").write_text("\n".join(lines) + "\n")


def write_regions_bed(manifest: pd.DataFrame, out: Path) -> None:
    """ofh_snv_regions.bed — region code -> chr:start-end (CPRA -> region-file lookup)."""
    pos = manifest["pos"].astype(int)
    start, end = max(0, int(pos.min()) - 1000), int(pos.max()) + 1000
    (out / "ofh_snv_regions.bed").write_text(f"10\t{start}\t{end}\t{_REGION}\n")
    (out / "ofh_imputed_regions.v6.bed").write_text(f"10\t{start}\t{end}\t{_REGION}\n")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--in", dest="src", default="data/synthetic", help="simplified synthetic dir")
    ap.add_argument("--out", default="data/synthetic/ofh_tre", help="real-format output dir")
    args = ap.parse_args()
    src, out = Path(args.src), Path(args.out)
    out.mkdir(parents=True, exist_ok=True)

    slice_df = pd.read_parquet(src / "genotype_slice.parquet")
    manifest = pd.read_csv(src / "variant_manifest.csv", dtype=str)
    sample_qc = pd.read_csv(src / "sample_qc_metrics.tsv", sep="\t")
    participants = pd.read_parquet(src / "participant_table.parquet")
    # attach chrom/pos/ref/alt to the slice from the manifest (the VCF needs them per variant)
    coords = manifest.set_index("cpra")[["chrom", "pos", "ref", "alt"]]
    slice_df = slice_df.join(coords, on="cpra")
    slice_df = slice_df[slice_df["chrom"].notna()]  # only variants present in the manifest

    on_array = set(manifest.loc[manifest["on_array"].str.upper() == "TRUE", "cpra"])
    on_imputed = set(manifest.loc[manifest["on_imputed"].str.upper() == "TRUE", "cpra"])
    write_array_pvcf(slice_df[slice_df["cpra"].isin(on_array)], out)
    write_imputed_pvcf(slice_df[slice_df["cpra"].isin(on_imputed)], out)
    write_variant_summary_stats(manifest, out)
    write_sample_qc(sample_qc, participants, out)
    write_sample_files(slice_df, participants, out)
    write_kinship(sample_qc, out)
    write_regions_bed(manifest, out)
    # make the OFH dir a self-contained runnable input dir (participant/consent entity + the request
    # are not OFH *genetic* files; they come from the cohort browser — copied here for the demo).
    participants.to_parquet(out / "participant_table.parquet", index=False)
    if (src / "variant_request.csv").is_file():
        (out / "variant_request.csv").write_text((src / "variant_request.csv").read_text())
    n_variants = slice_df.drop_duplicates("cpra").shape[0]
    print(f"Wrote OFH-format stand-ins for {n_variants} variant(s) to {out}/")


if __name__ == "__main__":
    main()
