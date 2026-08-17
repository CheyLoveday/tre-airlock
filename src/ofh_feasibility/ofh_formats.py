"""ofh_formats — read the real OFH TRE genetic file formats into our core schemas (Wave 9).

Parsers for the genuine OFH-format files written by scripts/generate_ofh_files.py: the array pVCF
(bgzip VCFv4.1, GT only), the imputed pVCF (bgzip VCFv4.2, GT:GP), the variant
summary-statistics VCF, and the sample-QC TSVs. The combined manifest reader merges imputed summary
stats with array pVCF presence so array-only variants remain identifiable.
Each reader returns a frame satisfying the EXISTING schema tuples in models, so the rest of the
pipeline is unchanged — an input adapter behind the io.GenotypeSource Protocol.

The files are REAL bgzip(BGZF)/tabix VCFs read with pysam (htslib) — the same way tabix/bcftools
read them in the TRE. pysam is the local-only `ofhgen` extra, imported lazily so the package (and
the allowlist-clean simplified path) import fine without it; only the OFH-format readers need it.

The real OFH array pVCF carries GT only (no per-genotype GQ) and call-rate is sample-level in the QC
TSV — so this reconstructs a passing GQ sentinel for our QC step and joins the sample call-rate onto
the array rows. See docs/reference/ofh_tre_genetic_file_formats.md.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd

from .models import (
    GENOTYPE_SLICE_COLUMNS,
    SAMPLE_QC_COLUMNS,
    VARIANT_MANIFEST_COLUMNS,
    require_columns,
)

_GQ_SENTINEL = 99  # OFH array pVCF has no GQ; reconstruct a passing value (QC is sample call-rate)
_ARRAY_PVCF = "ofh_snv.chr10-b0001.vcf.gz"
_IMPUTED_PVCF = "ofh_imputed.v6.chr10-b0001.vcf.gz"
_SUMMARY_STATS = "ofh_imputed_variant_summary_stats.v6.vcf.gz"


def _cpra_parts(cpra: str) -> tuple[str, int, str, str]:
    chrom, pos, ref, alt = cpra.split(":")
    return chrom, int(pos), ref, alt


def _cpra_region(cpra: str) -> tuple[str, int]:
    chrom, pos, *_ = _cpra_parts(cpra)
    return chrom, pos


def _variant_file(path: str | Path):
    """Open a (bgzip) VCF with pysam — lazy import so the package loads without the ofhgen extra."""
    import pysam  # local-only ofhgen extra (htslib); never a TRE runtime dependency

    return pysam.VariantFile(str(path))


def _records(vf, cpra: str | None = None, *, allow_full_scan_fallback: bool = False):
    """Yield records, using tabix by CPRA when supplied.

    Full scans are allowed only when no CPRA is supplied, or when a fixture/helper explicitly opts
    into fallback. The real OFH ingest path must not silently scan region files at cohort scale.
    """
    if cpra is None:
        yield from vf
        return
    chrom, pos = _cpra_region(cpra)
    if chrom not in vf.header.contigs:
        return
    try:
        iterator = vf.fetch(chrom, pos - 1, pos)
    except (OSError, ValueError) as exc:
        if not allow_full_scan_fallback:
            raise ValueError(
                f"ofh_tre CPRA lookup for {cpra} requires a tabix-indexed VCF; "
                "refusing full-scan fallback"
            ) from exc
        iterator = vf
    for rec in iterator:
        if rec.id == cpra:
            yield rec


def _gt_code(gt: tuple) -> int:
    """VCF GT tuple -> our hardcall code: missing -> -1, else the alt-allele count (0/1/2)."""
    if not gt or any(a is None for a in gt):
        return -1
    return int(sum(gt))


def parse_array_pvcf(
    path: str | Path, cpra: str | None = None, *, allow_full_scan_fallback: bool = False
) -> pd.DataFrame:
    """Array pVCF (GT only) -> long-form rows, tabix-fetching the requested CPRA when supplied."""
    rows = []
    with _variant_file(path) as vf:
        for rec in _records(vf, cpra, allow_full_scan_fallback=allow_full_scan_fallback):
            for pid, data in rec.samples.items():
                rows.append(
                    {"participant_id": pid, "cpra": rec.id, "gt_code": _gt_code(data["GT"])}
                )
    return pd.DataFrame(rows, columns=["participant_id", "cpra", "gt_code"])


def parse_imputed_pvcf(
    path: str | Path, cpra: str | None = None, *, allow_full_scan_fallback: bool = False
) -> pd.DataFrame:
    """Imputed pVCF (GT:GP) -> dosage rows, tabix-fetching the requested CPRA when supplied."""
    rows = []
    with _variant_file(path) as vf:
        for rec in _records(vf, cpra, allow_full_scan_fallback=allow_full_scan_fallback):
            for pid, data in rec.samples.items():
                gp = [float(x) for x in data["GP"]]
                rows.append({
                    "participant_id": pid, "cpra": rec.id,
                    "dosage": round(gp[1] + 2 * gp[2], 4), "max_gp": max(gp),
                })
    return pd.DataFrame(rows, columns=["participant_id", "cpra", "dosage", "max_gp"])


def read_ofh_sample_qc(data_dir: str | Path) -> pd.DataFrame:
    """Read ofh_sample_qc_metrics.tsv into our SAMPLE_QC_COLUMNS schema (Wave 9)."""
    df = pd.read_csv(Path(data_dir) / "ofh_sample_qc_metrics.tsv", sep="\t")
    out = df.rename(columns={"call_rate": "array_call_rate"})[list(SAMPLE_QC_COLUMNS)]
    require_columns(out.columns, SAMPLE_QC_COLUMNS, "ofh_sample_qc")
    return out


def read_ofh_genotype_slice(
    data_dir: str | Path, cpra: str | None = None, *, allow_full_scan_fallback: bool = False
) -> pd.DataFrame:
    """Combine the array + imputed pVCFs into our long-form GENOTYPE_SLICE_COLUMNS frame.

    GQ has no OFH source -> a passing sentinel; call-rate is sample-level (joined from the QC TSV).
    """
    d = Path(data_dir)
    arr = parse_array_pvcf(
        d / _ARRAY_PVCF, cpra, allow_full_scan_fallback=allow_full_scan_fallback
    )
    imp = parse_imputed_pvcf(
        d / _IMPUTED_PVCF, cpra, allow_full_scan_fallback=allow_full_scan_fallback
    )
    qc = read_ofh_sample_qc(d).set_index("participant_id")["array_call_rate"]
    array_rows = pd.DataFrame({
        "participant_id": arr["participant_id"], "cpra": arr["cpra"], "source": "array",
        "gt_code": arr["gt_code"], "gq": _GQ_SENTINEL,
        "call_rate": arr["participant_id"].map(qc), "dosage": np.nan, "max_gp": np.nan,
    })
    imp_rows = pd.DataFrame({
        "participant_id": imp["participant_id"], "cpra": imp["cpra"], "source": "imputed",
        "gt_code": np.nan, "gq": np.nan, "call_rate": np.nan,
        "dosage": imp["dosage"], "max_gp": imp["max_gp"],
    })
    slice_df = pd.concat([array_rows, imp_rows], ignore_index=True)[list(GENOTYPE_SLICE_COLUMNS)]
    require_columns(slice_df.columns, GENOTYPE_SLICE_COLUMNS, "genotype_slice(ofh_tre)")
    return slice_df


def read_ofh_variant_summary_stats(
    data_dir: str | Path, cpra: str | None = None, *, allow_full_scan_fallback: bool = False
) -> pd.DataFrame:
    """Read the bgzip variant summary-stats VCF into our VARIANT_MANIFEST_COLUMNS schema.

    INFO only, no sample columns; DR2->dosage_r2, AF->imputed_maf, PROP_TYPED>0 -> on_array. Models
    the documented OFH workflow: query the summary-stats VCF by CPRA before pulling a region file.
    """
    rows = []
    with _variant_file(Path(data_dir) / _SUMMARY_STATS) as vf:
        for rec in _records(vf, cpra, allow_full_scan_fallback=allow_full_scan_fallback):
            info = rec.info
            prop_typed = float(info.get("PROP_TYPED", 0.0) or 0.0)
            af = info.get("AF")
            if isinstance(af, tuple):  # AF is declared Number=A -> pysam returns a per-alt tuple
                af = af[0] if af else None
            dr2 = info.get("DR2")
            rows.append({
                "cpra": rec.id, "chrom": str(rec.chrom), "pos": str(rec.pos),
                "ref": rec.ref, "alt": rec.alts[0], "build": "GRCh38", "biallelic": "TRUE",
                "on_array": "TRUE" if prop_typed > 0 else "FALSE", "on_imputed": "TRUE",
                # %g trims float32 noise from pysam (0.7099999.. -> 0.71) so the manifest frame
                # carries clean string values like the CSV manifest does.
                "array_maf": "NA" if af is None else f"{float(af):.6g}",
                "imputed_maf": "NA" if af is None else f"{float(af):.6g}",
                "dosage_r2": "NA" if dr2 is None else f"{float(dr2):.6g}",
                "annotation": "from_summary_stats",
                "inaccurate_annotation": "FALSE", "multiallelic_variant": "FALSE",
            })
    df = pd.DataFrame(rows, columns=list(VARIANT_MANIFEST_COLUMNS))
    require_columns(df.columns, VARIANT_MANIFEST_COLUMNS, "ofh_variant_summary_stats")
    return df


def _array_af(array_rows: pd.DataFrame) -> str:
    called = array_rows[array_rows["gt_code"] >= 0]
    if called.empty:
        return "NA"
    af = float(called["gt_code"].sum()) / (2 * len(called))
    return f"{af:.6g}"


def _array_manifest_rows(
    data_dir: str | Path, cpra: str | None = None, *, allow_full_scan_fallback: bool = False
) -> pd.DataFrame:
    """Build manifest rows from array pVCF presence, covering array-only variants."""
    array = parse_array_pvcf(
        Path(data_dir) / _ARRAY_PVCF,
        cpra,
        allow_full_scan_fallback=allow_full_scan_fallback,
    )
    rows = []
    for variant_cpra, rows_for_variant in array.groupby("cpra", sort=False):
        chrom, pos, ref, alt = _cpra_parts(variant_cpra)
        rows.append({
            "cpra": variant_cpra, "chrom": chrom, "pos": str(pos),
            "ref": ref, "alt": alt, "build": "GRCh38", "biallelic": "TRUE",
            "on_array": "TRUE", "on_imputed": "FALSE",
            "array_maf": _array_af(rows_for_variant), "imputed_maf": "NA", "dosage_r2": "NA",
            "annotation": "from_array_pvcf",
            "inaccurate_annotation": "FALSE", "multiallelic_variant": "FALSE",
        })
    return pd.DataFrame(rows, columns=list(VARIANT_MANIFEST_COLUMNS))


def read_ofh_variant_manifest(
    data_dir: str | Path, cpra: str | None = None, *, allow_full_scan_fallback: bool = False
) -> pd.DataFrame:
    """Combined OFH-format manifest: imputed summary stats plus array pVCF presence.

    Public BAG3 evidence is array-present and imputed-absent. A manifest built only from the imputed
    summary-statistics VCF would wrongly fail that real source verdict, so array pVCF records are
    merged in as `on_array=TRUE, on_imputed=FALSE` rows when the summary stats lack the CPRA.
    """
    summary = read_ofh_variant_summary_stats(
        data_dir, cpra, allow_full_scan_fallback=allow_full_scan_fallback
    )
    array = _array_manifest_rows(
        data_dir, cpra, allow_full_scan_fallback=allow_full_scan_fallback
    )
    if summary.empty:
        df = array
    else:
        df = summary.copy()
        if not array.empty:
            array_by_cpra = array.set_index("cpra")
            for idx, row in df.iterrows():
                variant_cpra = row["cpra"]
                if variant_cpra in array_by_cpra.index:
                    df.loc[idx, "on_array"] = "TRUE"
                    df.loc[idx, "array_maf"] = array_by_cpra.loc[variant_cpra, "array_maf"]
            missing = array[~array["cpra"].isin(set(df["cpra"]))]
            df = pd.concat([df, missing], ignore_index=True)
    df = df[list(VARIANT_MANIFEST_COLUMNS)]
    require_columns(df.columns, VARIANT_MANIFEST_COLUMNS, "ofh_variant_manifest")
    return df


@dataclass(frozen=True)
class OfhTreGenotypeSource:
    """Reads the real OFH per-region bgzip pVCF files into the long-form slice — a drop-in
    GenotypeSource (io.GenotypeSource Protocol) over the real files. The native OFH ingest path."""

    data_dir: str | Path
    cpra: str | None = None
    allow_full_scan_fallback: bool = False

    def read_slice(self) -> pd.DataFrame:
        return read_ofh_genotype_slice(
            self.data_dir,
            self.cpra,
            allow_full_scan_fallback=self.allow_full_scan_fallback,
        )
