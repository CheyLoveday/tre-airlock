"""io — readers and writers (the imperative shell's filesystem boundary).

The general filesystem boundary (bridge.py additionally owns the canonical release publication;
config.py loads configuration). Readers validate tabular inputs
against the declared column schemas (require_columns) so incoherent data is refused at the edge,
never three stages later. The pure core (qc/classify/sdc/extract/reporting builders) imports none
of this.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol, runtime_checkable

import numpy as np
import pandas as pd

from .models import (
    GENOTYPE_SLICE_COLUMNS,
    PARTICIPANT_COLUMNS,
    SAMPLE_QC_COLUMNS,
    VARIANT_IDENTIFIABILITY_COLUMNS,
    VARIANT_MANIFEST_COLUMNS,
    BatchRequest,
    EpiReturn,
    HumanReviewCheckpoint,
    VariantRequest,
    require_columns,
)

# --- readers -------------------------------------------------------------------------------


def read_request(path: str | Path) -> VariantRequest:
    """Read a single-row variant request (CSV or JSON) into a validated VariantRequest."""
    path = Path(path)
    if path.suffix == ".json":
        data = json.loads(path.read_text())
    else:
        # dtype=str keeps chrom as "10" (not int 10) so the CPRA-consistency check holds;
        # pydantic coerces pos "..." -> int.
        rows = pd.read_csv(path, dtype=str)
        if len(rows) != 1:
            raise ValueError(f"variant request CSV must contain exactly one row, got {len(rows)}")
        data = rows.iloc[0].to_dict()
    return VariantRequest.from_dict(data)


def read_batch_request(path: str | Path) -> BatchRequest:
    """Read a multi-row batch request (one row per CPRA) into a validated BatchRequest."""
    rows = pd.read_csv(path, dtype=str).to_dict("records")
    return BatchRequest.from_rows(rows)


def read_epi_return(path: str | Path) -> EpiReturn:
    """Read the aggregate epidemiology return (JSON) into a validated EpiReturn (Wave 8).

    JSON, not CSV: the return carries a `caveats` list, and JSON is the human+machine-readable
    artefact epidemiology fills from the template. Schema is enforced by the pydantic model.
    """
    return EpiReturn.from_dict(json.loads(Path(path).read_text()))


def read_checkpoints(path: str | Path) -> list[HumanReviewCheckpoint]:
    """Read the human-review checkpoint ledger (JSONL); empty list if absent (Wave 8)."""
    p = Path(path)
    if not p.is_file():
        return []
    return [HumanReviewCheckpoint.from_dict(rec) for rec in read_jsonl(p)]


def read_dictionaries(data_dir: str | Path) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """Read the metadata-first (entity, data, coding) dictionaries that describe the slice."""
    data_dir = Path(data_dir)
    entity = pd.read_csv(data_dir / "entity_dictionary.csv")
    data = pd.read_csv(data_dir / "data_dictionary.csv")
    coding = pd.read_csv(data_dir / "coding_dictionary.csv")
    return entity, data, coding


def read_variant_manifest(data_dir: str | Path) -> pd.DataFrame:
    """Read the variant summary-statistics manifest (availability + INFO); validate columns."""
    df = pd.read_csv(Path(data_dir) / "variant_manifest.csv", dtype=str)
    require_columns(df.columns, VARIANT_MANIFEST_COLUMNS, "variant_manifest")
    return df


def read_variant_identifiability(path: str | Path) -> pd.DataFrame:
    """Read the small public-list-derived identifiability artifact."""
    df = pd.read_csv(path, dtype=str)
    require_columns(df.columns, VARIANT_IDENTIFIABILITY_COLUMNS, "variant_identifiability")
    return df


def default_reference() -> dict:
    """Mock GRCh38/GRCh37 reference-base + panel-MAF stub for the variant pre-flight (Wave 7).

    In the TRE this is replaced by a FASTA lookup (GRCh38, plus GRCh37 for build disambiguation)
    and a reference-panel allele-frequency source behind the same dict contract. Demo values only:
    REF at chr10:119669928 is C on GRCh38 (BAG3), and the same locus sits at ~chr10:121.4Mb on
    GRCh37 — present so a back-formed GRCh37 coordinate is caught rather than silently accepted.
    """
    return {
        "bases": {
            "GRCh38": {
                "10:119669928": "C",
                "10:121000000": "A",
                "22:28695868": "A",
                "22:28725099": "A",
                "17:43044295": "G",
                "13:32316461": "C",
                "16:23614412": "G",
                "11:108236123": "C",
            },
            "GRCh37": {"10:121429351": "C"},
        },
        "panel_maf": {
            "10:119669928:C:G": 0.013,
            "10:121000000:A:T": 0.020,
            "22:28695868:AG:A": 0.004,
            "22:28725099:A:G": 0.025,
            "17:43044295:G:A": 0.018,
            "13:32316461:C:T": 0.016,
            "16:23614412:G:A": 0.020,
            "11:108236123:C:T": 0.022,
        },
    }


def read_participants(data_dir: str | Path) -> pd.DataFrame:
    """Read the participant table (Parquet); validate columns."""
    df = pd.read_parquet(Path(data_dir) / "participant_table.parquet")
    require_columns(df.columns, PARTICIPANT_COLUMNS, "participants")
    return df


def read_genotype_slice(data_dir: str | Path) -> pd.DataFrame:
    """Read the long-form genotype slice (array + imputed rows, Parquet); validate columns."""
    df = pd.read_parquet(Path(data_dir) / "genotype_slice.parquet")
    require_columns(df.columns, GENOTYPE_SLICE_COLUMNS, "genotype_slice")
    return df


def read_sample_qc(data_dir: str | Path) -> pd.DataFrame:
    """Read the sample-level QC metrics (TSV); validate columns."""
    df = pd.read_csv(Path(data_dir) / "sample_qc_metrics.tsv", sep="\t")
    require_columns(df.columns, SAMPLE_QC_COLUMNS, "sample_qc")
    return df


@runtime_checkable
class GenotypeSource(Protocol):
    """Loads the long-form genotype slice (GENOTYPE_SLICE_COLUMNS). A VCF/BGEN-shaped reader can
    replace the CSV/Parquet stand-in behind this one interface — the DAG is the contract, so the
    downstream stages never change."""

    def read_slice(self) -> pd.DataFrame: ...


@dataclass(frozen=True)
class CsvGenotypeSource:
    """Default stand-in: the long-form genotype-slice Parquet."""

    data_dir: str | Path

    def read_slice(self) -> pd.DataFrame:
        return read_genotype_slice(self.data_dir)


_VCF_GT_CODE = {"0/0": 0, "0/1": 1, "1/0": 1, "1/1": 2, "./.": -1, ".": -1}


@dataclass(frozen=True)
class VcfBgenShapedGenotypeSource:
    """VCF/BGEN-shaped reader: array_calls_vcf.tsv (VCF GT strings) + imputed_calls_bgen.tsv (GP
    triple) -> the SAME long-form slice the CSV source yields. Demonstrates a genomic-IO swap."""

    data_dir: str | Path

    def read_slice(self) -> pd.DataFrame:
        d = Path(self.data_dir)
        arr = pd.read_csv(d / "array_calls_vcf.tsv", sep="\t")
        imp = pd.read_csv(d / "imputed_calls_bgen.tsv", sep="\t")
        array_rows = pd.DataFrame({
            "participant_id": arr["participant_id"], "cpra": arr["cpra"], "source": "array",
            "gt_code": arr["gt"].map(_VCF_GT_CODE), "gq": arr["gq"], "call_rate": arr["call_rate"],
            "dosage": np.nan, "max_gp": np.nan,
        })
        imp_rows = pd.DataFrame({
            "participant_id": imp["participant_id"], "cpra": imp["cpra"], "source": "imputed",
            "gt_code": np.nan, "gq": np.nan, "call_rate": np.nan,
            "dosage": imp["dosage"], "max_gp": imp[["gp_00", "gp_01", "gp_11"]].max(axis=1),
        })
        slice_df = pd.concat([array_rows, imp_rows], ignore_index=True)
        slice_df = slice_df[list(GENOTYPE_SLICE_COLUMNS)]
        require_columns(slice_df.columns, GENOTYPE_SLICE_COLUMNS, "genotype_slice(vcf_bgen)")
        return slice_df


def read_parquet(path: str | Path) -> pd.DataFrame:
    """Read a staged intermediate Parquet (our own output; no schema check)."""
    return pd.read_parquet(path)


def read_json(path: str | Path) -> dict:
    """Read a staged intermediate JSON (our own output)."""
    return json.loads(Path(path).read_text())


def read_jsonl(path: str | Path) -> list[dict]:
    """Read an append-only JSONL ledger into a list of events."""
    lines = Path(path).read_text().splitlines()
    return [json.loads(line) for line in lines if line.strip()]


def append_jsonl(obj: object, path: str | Path) -> None:
    """Append one record as a line to a JSONL ledger (creating it if needed)."""
    with _ensure_parent(path).open("a") as fh:
        fh.write(json.dumps(obj) + "\n")


# --- writers -------------------------------------------------------------------------------


def _ensure_parent(path: str | Path) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def write_parquet(df: pd.DataFrame, path: str | Path) -> None:
    """Write a DataFrame to Parquet (internal tabular staging)."""
    df.to_parquet(_ensure_parent(path), index=False)


def write_csv(df: pd.DataFrame, path: str | Path) -> None:
    """Write a DataFrame to CSV (human-readable handoff)."""
    df.to_csv(_ensure_parent(path), index=False)


def write_text(text: str, path: str | Path) -> None:
    """Write a human-readable text artefact (analyst notes, audit roots)."""
    _ensure_parent(path).write_text(text)


def write_json(obj: object, path: str | Path) -> None:
    """Write an object as pretty JSON (the airlock manifest)."""
    _ensure_parent(path).write_text(json.dumps(obj, indent=2))
