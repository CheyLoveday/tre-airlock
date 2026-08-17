#!/usr/bin/env python3
"""Generate OFH-shaped dummy inputs for the feasibility MVP (deterministic, seed 42).

Mirrors the OFH access pattern: a metadata-first dataset (entity/data/coding dictionaries)
plus a request-driven genotype slice, participant table, and sample QC. Deliberate edge
cases are seeded so the QC/consent/SDC logic has something real to handle.
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import random

import numpy as np
import pandas as pd

from ofh_feasibility import resolve

CPRA = "10:119669928:C:G"
N = 500

# gt_code -> VCF GT string (the vcf/bgen-shaped fixtures demonstrate a different on-disk shape
# behind the same GenotypeSource interface; see src/ofh_feasibility/io.py).
_VCF_GT = {0: "0/0", 1: "0/1", 2: "1/1", -1: "./."}


def _gp_triple(dosage: float, max_gp: float) -> list[float]:
    """A plausible BGEN genotype-probability triple whose max == max_gp and modal index ~ dosage."""
    idx = min(2, max(0, int(round(dosage))))
    triple = [0.0, 0.0, 0.0]
    triple[idx] = max_gp
    triple[1 if idx != 1 else 0] = round(1.0 - max_gp, 3)  # remainder on a non-modal genotype
    return [round(x, 3) for x in triple]


def write_variant_manifest(out: str) -> None:
    """Variant summary-statistics manifest: resource membership + per-variant dosage-r2 (DR2).

    OFH-native home for the imputation quality metric — OFH uses dosage-r2 (DR2), not a
    traditional INFO score (the CPRA lists carry presence + ref/alt only; DR2 lives in the TRE
    variant summary-statistics VCF). Drives stage-1 validation and the array-vs-imputed source
    decision.

    In this synthetic manifest, `on_array` / `on_imputed` mean "this fixture contains that source
    row." In the runtime path, `variant_identifiability.csv` overlays those fields with public
    Release 14 resource-membership facts before source resolution. For BAG3, that means exact CPRA
    present in the array resource and absent from the imputed resource. The fixture still keeps
    historical dummy imputed rows for branch coverage; see docs/reference/BAG3_VERIFICATION.md.
    """
    with open(os.path.join(out, "variant_manifest.csv"), "w", newline="") as f:
        w = csv.writer(f, lineterminator="\n")
        w.writerow(
            [
                "cpra",
                "chrom",
                "pos",
                "ref",
                "alt",
                "build",
                "biallelic",
                "on_array",
                "on_imputed",
                "array_maf",
                "imputed_maf",
                "dosage_r2",
                "annotation",
                "inaccurate_annotation",
                "multiallelic_variant",
            ]
        )
        w.writerow(
            [
                CPRA,
                "10",
                "119669928",
                "C",
                "G",
                "GRCh38",
                "TRUE",
                "TRUE",
                "TRUE",
                "0.013",
                "0.014",
                "0.71",
                "pathogenic_BAG3_dilated_cardiomyopathy",
                "FALSE",
                "FALSE",
            ]
        )
        # wrong-alt distractor: same position, different alt -> a different variant, absent.
        w.writerow(
            [
                "10:119669928:C:T",
                "10",
                "119669928",
                "C",
                "T",
                "GRCh38",
                "FALSE",
                "FALSE",
                "FALSE",
                "NA",
                "NA",
                "NA",
                "wrong_alt_not_in_resource",
                "FALSE",
                "FALSE",
            ]
        )
        for variant in WAVE11_VARIANTS:
            w.writerow(_manifest_row(variant))


CPRA2 = "10:121000000:A:T"  # an illustrative SECOND variant for the batch/multi-variant demo

WAVE11_VARIANTS = [
    {
        "cpra": resolve.CHEK2_C1100DELC,
        "chrom": "22",
        "pos": "28695868",
        "ref": "AG",
        "alt": "A",
        "on_array": "FALSE",
        "on_imputed": "TRUE",
        "array_maf": "NA",
        "imputed_maf": "0.004",
        "dosage_r2": "0.18",
        "annotation": "CHEK2_c1100delC_array_absent_low_DR2_demo",
    },
    {
        "cpra": resolve.CHEK2_I157T,
        "chrom": "22",
        "pos": "28725099",
        "ref": "A",
        "alt": "G",
        "on_array": "TRUE",
        "on_imputed": "TRUE",
        "array_maf": "0.025",
        "imputed_maf": "0.026",
        "dosage_r2": "0.92",
        "annotation": "CHEK2_I157T_array_direct_demo",
    },
    {
        "cpra": resolve.BRCA1_DEMO,
        "chrom": "17",
        "pos": "43044295",
        "ref": "G",
        "alt": "A",
        "on_array": "TRUE",
        "on_imputed": "TRUE",
        "array_maf": "0.018",
        "imputed_maf": "0.018",
        "dosage_r2": "0.95",
        "annotation": "BRCA1_demo_panel_variant",
    },
    {
        "cpra": resolve.BRCA2_DEMO,
        "chrom": "13",
        "pos": "32316461",
        "ref": "C",
        "alt": "T",
        "on_array": "TRUE",
        "on_imputed": "TRUE",
        "array_maf": "0.016",
        "imputed_maf": "0.016",
        "dosage_r2": "0.93",
        "annotation": "BRCA2_demo_panel_variant",
    },
    {
        "cpra": resolve.PALB2_DEMO,
        "chrom": "16",
        "pos": "23614412",
        "ref": "G",
        "alt": "A",
        "on_array": "TRUE",
        "on_imputed": "TRUE",
        "array_maf": "0.020",
        "imputed_maf": "0.020",
        "dosage_r2": "0.94",
        "annotation": "PALB2_demo_panel_variant",
    },
    {
        "cpra": resolve.ATM_DEMO,
        "chrom": "11",
        "pos": "108236123",
        "ref": "C",
        "alt": "T",
        "on_array": "TRUE",
        "on_imputed": "TRUE",
        "array_maf": "0.022",
        "imputed_maf": "0.022",
        "dosage_r2": "0.91",
        "annotation": "ATM_demo_panel_variant",
    },
]


def _manifest_row(v: dict) -> list[str]:
    return [
        v["cpra"],
        v["chrom"],
        v["pos"],
        v["ref"],
        v["alt"],
        "GRCh38",
        "TRUE",
        v["on_array"],
        v["on_imputed"],
        v["array_maf"],
        v["imputed_maf"],
        v["dosage_r2"],
        v["annotation"],
        "FALSE",
        "FALSE",
    ]


def write_batch_second_variant(out: str) -> None:
    """Append a 2nd variant (manifest + slice rows) + batch_request.csv for the multi-variant demo.

    Additive: the BAG3 single-variant outputs are untouched (BAG3 is generated in full first).
    CPRA2 is synthetic, not a real OFH variant.
    """
    pd.DataFrame(
        [
            {
                "study_id": "OFH-CRRS-DEMO-BATCH-001",
                "cpra": CPRA,
                "chrom": "10",
                "pos": 119669928,
                "ref": "C",
                "alt": "G",
                "build": "GRCh38",
                "carrier_definition": "het_and_homalt",
                "requested_source": "array_and_imputed",
                "purpose": "Composite recall: BAG3 + 2nd variant",
            },
            {
                "study_id": "OFH-CRRS-DEMO-BATCH-001",
                "cpra": CPRA2,
                "chrom": "10",
                "pos": 121000000,
                "ref": "A",
                "alt": "T",
                "build": "GRCh38",
                "carrier_definition": "het_and_homalt",
                "requested_source": "array_and_imputed",
                "purpose": "Composite recall: BAG3 + 2nd variant",
            },
        ]
    ).to_csv(os.path.join(out, "batch_request.csv"), index=False)

    with open(os.path.join(out, "variant_manifest.csv"), "a", newline="") as f:
        csv.writer(f, lineterminator="\n").writerow(
            [
                CPRA2,
                "10",
                "121000000",
                "A",
                "T",
                "GRCh38",
                "TRUE",
                "TRUE",
                "TRUE",
                "0.020",
                "0.021",
                "0.88",
                "illustrative_second_variant",
                "FALSE",
                "FALSE",
            ]
        )

    pids = pd.read_parquet(os.path.join(out, "participant_table.parquet"))[
        "participant_id"
    ].tolist()
    v2 = set(
        random.sample(range(len(pids)), 18)
    )  # a different carrier set (some overlap with BAG3)
    rows = []
    for i, pid in enumerate(pids):
        c = i in v2
        gt = 2 if (c and random.random() < 0.1) else (1 if c else 0)
        rows.append(
            dict(
                participant_id=pid,
                cpra=CPRA2,
                source="array",
                gt_code=gt,
                gq=random.randint(30, 60),
                call_rate=round(random.uniform(0.985, 0.999), 4),
                dosage=np.nan,
                max_gp=np.nan,
            )
        )
        dos, mg = (
            (round(random.uniform(0.9, 1.1), 3), 0.96)
            if c
            else (round(random.uniform(0.0, 0.05), 3), 0.985)
        )
        rows.append(
            dict(
                participant_id=pid,
                cpra=CPRA2,
                source="imputed",
                gt_code=np.nan,
                gq=np.nan,
                call_rate=np.nan,
                dosage=dos,
                max_gp=mg,
            )
        )
    existing = pd.read_parquet(os.path.join(out, "genotype_slice.parquet"))
    combined = pd.concat([existing, pd.DataFrame(rows)], ignore_index=True)
    combined.to_parquet(os.path.join(out, "genotype_slice.parquet"), index=False)


def _request_row(study_id: str, variant: dict, purpose: str) -> dict:
    return {
        "study_id": study_id,
        "cpra": variant["cpra"],
        "chrom": variant["chrom"],
        "pos": int(variant["pos"]),
        "ref": variant["ref"],
        "alt": variant["alt"],
        "build": "GRCh38",
        "carrier_definition": "het_and_homalt",
        "requested_source": "array_and_imputed",
        "purpose": purpose,
    }


def write_wave11_requests(out: str) -> None:
    """Write explicit request files so CLI/Snakemake can run each expanded case by path."""
    req_dir = os.path.join(out, "requests")
    os.makedirs(req_dir, exist_ok=True)
    by_cpra = {v["cpra"]: v for v in WAVE11_VARIANTS}
    pd.DataFrame(
        [
            {
                "study_id": "OFH-CRRS-DEMO-001",
                "cpra": CPRA,
                "chrom": "10",
                "pos": 119669928,
                "ref": "C",
                "alt": "G",
                "build": "GRCh38",
                "carrier_definition": "het_and_homalt",
                "requested_source": "array_and_imputed",
                "purpose": "Recontact feasibility: BAG3 carriers for external cardiology study",
            }
        ]
    ).to_csv(os.path.join(req_dir, "bag3.csv"), index=False)
    pd.DataFrame(
        [
            _request_row(
                "OFH-CRRS-DEMO-CHEK2-1100DELC",
                by_cpra[resolve.CHEK2_C1100DELC],
                "Recontact feasibility: CHEK2 c.1100delC carriers for breast-cancer study",
            )
        ]
    ).to_csv(os.path.join(req_dir, "chek2_c1100delc.csv"), index=False)
    pd.DataFrame(
        [
            _request_row(
                "OFH-CRRS-DEMO-CHEK2-I157T",
                by_cpra[resolve.CHEK2_I157T],
                "Recontact feasibility: CHEK2 I157T carriers for breast-cancer study",
            )
        ]
    ).to_csv(os.path.join(req_dir, "chek2_i157t.csv"), index=False)


def _consented_indices(parts: list[dict], ancestry: str | None = None) -> list[int]:
    return [
        p["i"]
        for p in parts
        if p["consent_status"] == "consented"
        and (ancestry is None or p["ancestry_stub"] == ancestry)
    ]


def _pick_by_ancestry(parts: list[dict], targets: dict[str, int], *, offset: int = 0) -> set[int]:
    chosen: set[int] = set()
    for ancestry, n in targets.items():
        pool = _consented_indices(parts, ancestry)
        if len(pool) < n:
            raise ValueError(f"not enough {ancestry} participants for WAVE_11 synthetic carriers")
        start = min(offset, max(0, len(pool) - n))
        chosen.update(pool[start : start + n])
    return chosen


def _append_variant_genotypes(
    rows: list[dict],
    vcf_array: list[dict],
    bgen_imputed: list[dict],
    parts: list[dict],
    variant: dict,
    carrier_indices: set[int],
) -> None:
    on_array = variant["on_array"] == "TRUE"
    on_imputed = variant["on_imputed"] == "TRUE"
    for p in parts:
        carrier = p["i"] in carrier_indices
        if on_array:
            gt = 1 if carrier else 0
            if carrier and p["i"] % 17 == 0:
                gt = 2
            gq = 55 if carrier else 50
            cr = 0.996
            rows.append(
                dict(
                    participant_id=p["participant_id"],
                    cpra=variant["cpra"],
                    source="array",
                    gt_code=gt,
                    gq=gq,
                    call_rate=cr,
                    dosage=np.nan,
                    max_gp=np.nan,
                )
            )
            vcf_array.append(
                dict(
                    participant_id=p["participant_id"],
                    cpra=variant["cpra"],
                    gt=_VCF_GT[gt],
                    gq=gq,
                    call_rate=cr,
                )
            )
        if on_imputed:
            dos, mg = ((1.0, 0.97) if carrier else (0.02, 0.985))
            if variant["cpra"] == resolve.CHEK2_C1100DELC and carrier:
                dos, mg = 1.0, 0.93
            rows.append(
                dict(
                    participant_id=p["participant_id"],
                    cpra=variant["cpra"],
                    source="imputed",
                    gt_code=np.nan,
                    gq=np.nan,
                    call_rate=np.nan,
                    dosage=dos,
                    max_gp=mg,
                )
            )
            gp = _gp_triple(dos, mg)
            bgen_imputed.append(
                dict(
                    participant_id=p["participant_id"],
                    cpra=variant["cpra"],
                    dosage=dos,
                    gp_00=gp[0],
                    gp_01=gp[1],
                    gp_11=gp[2],
                )
            )


def append_wave11_genotypes(
    rows: list[dict], vcf_array: list[dict], bgen_imputed: list[dict], parts: list[dict]
) -> None:
    """Add deterministic CHEK2 and breast-cancer panel cases.

    I157T is deliberately large enough, in every ancestry stratum, to show released breakdowns. The
    c.1100delC stand-in is array-absent and low-DR2, so it remains identifiable but not credible for
    recall without a targeted assay.
    """
    carriers_by_cpra = {
        resolve.CHEK2_C1100DELC: set(_consented_indices(parts)[:8]),
        resolve.CHEK2_I157T: _pick_by_ancestry(
            parts, {"EUR": 36, "SAS": 12, "AFR": 12, "EAS": 10}
        ),
        resolve.BRCA1_DEMO: _pick_by_ancestry(parts, {"EUR": 24, "SAS": 10, "AFR": 10, "EAS": 10}),
        resolve.BRCA2_DEMO: _pick_by_ancestry(
            parts, {"EUR": 26, "SAS": 10, "AFR": 10, "EAS": 10}, offset=12
        ),
        resolve.PALB2_DEMO: _pick_by_ancestry(
            parts, {"EUR": 22, "SAS": 10, "AFR": 10, "EAS": 10}, offset=24
        ),
        resolve.ATM_DEMO: _pick_by_ancestry(
            parts, {"EUR": 24, "SAS": 10, "AFR": 10, "EAS": 10}, offset=36
        ),
    }
    for variant in WAVE11_VARIANTS:
        _append_variant_genotypes(
            rows, vcf_array, bgen_imputed, parts, variant, carriers_by_cpra[variant["cpra"]]
        )


def write_dictionaries(out: str) -> None:
    """Metadata-first dictionaries shaped to the real OFH v14 conventions (D23).

    Mirrors the v14 data-dictionary columns (entity, name, type, primary_key_type, coding_name,
    title, units, description) and codings columns (coding_name, code, meaning, display_order,
    parent_code), incl. the OFH special-value codes (-999 Suppressed; -1/-3 Do-not-know /
    Prefer-not). Field names stay as our actual data columns; see
    docs/reference/missing-data.md sec 4.
    """
    with open(os.path.join(out, "entity_dictionary.csv"), "w", newline="") as f:
        w = csv.writer(f, lineterminator="\n")
        w.writerow(["entity", "description", "primary_key"])
        w.writerow(["participant", "Consented participant baseline", "participant_id"])
        w.writerow(["genotype", "Per-variant genotype slice (array + imputed)", "participant_id"])
        w.writerow(["sample_qc", "Sample-level QC metrics", "participant_id"])
        w.writerow(["genetic_data", "Variant summary statistics (availability + DR2)", "cpra"])

    with open(os.path.join(out, "data_dictionary.csv"), "w", newline="") as f:
        w = csv.writer(f, lineterminator="\n")
        w.writerow(
            [
                "entity",
                "name",
                "type",
                "primary_key_type",
                "coding_name",
                "title",
                "units",
                "description",
            ]
        )
        rows = [
            (
                "participant",
                "participant_id",
                "string",
                "global",
                "",
                "Participant ID",
                "",
                "Internal participant identifier",
            ),
            (
                "participant",
                "pseudo_id",
                "string",
                "",
                "",
                "Pseudo ID",
                "",
                "Pseudonymised ID for the epi handoff",
            ),
            ("participant", "sex", "categorical", "", "SEX", "Reported sex", "", "Reported sex"),
            (
                "participant",
                "ancestry_stub",
                "categorical",
                "",
                "ANC",
                "Ancestry group",
                "",
                "Genetically-inferred ancestry group",
            ),
            (
                "participant",
                "consent_status",
                "categorical",
                "",
                "CONSENT",
                "Consent status",
                "",
                "Recontact consent state",
            ),
            (
                "participant",
                "baseline_qc_pass",
                "boolean",
                "",
                "",
                "Baseline QC pass",
                "",
                "Passed baseline QC",
            ),
            ("genotype", "cpra", "string", "", "", "Variant CPRA", "", "Chrom:Pos:Ref:Alt"),
            ("genotype", "source", "categorical", "", "SOURCE", "Source", "", "array or imputed"),
            (
                "genotype",
                "gt_code",
                "integer",
                "",
                "GT",
                "Hardcall genotype",
                "",
                "Array hardcall genotype code",
            ),
            (
                "genotype",
                "gq",
                "integer",
                "",
                "",
                "Genotype quality",
                "Phred",
                "Array genotype quality",
            ),
            (
                "genotype",
                "call_rate",
                "float",
                "",
                "",
                "Call rate",
                "proportion",
                "Per-sample array call rate",
            ),
            (
                "genotype",
                "dosage",
                "float",
                "",
                "",
                "Alt dosage",
                "alleles",
                "Imputed alt-allele dosage (0-2)",
            ),
            (
                "genotype",
                "max_gp",
                "float",
                "",
                "",
                "Max genotype prob",
                "probability",
                "Imputed max genotype probability",
            ),
            (
                "sample_qc",
                "array_call_rate",
                "float",
                "",
                "",
                "Array call rate",
                "proportion",
                "Sample array call rate",
            ),
            (
                "sample_qc",
                "het_rate",
                "float",
                "",
                "",
                "Heterozygosity",
                "proportion",
                "Heterozygosity rate",
            ),
            (
                "sample_qc",
                "sex_check_pass",
                "boolean",
                "",
                "",
                "Sex check pass",
                "",
                "Genetic sex matches reported",
            ),
            (
                "sample_qc",
                "ancestry_pc1",
                "float",
                "",
                "",
                "Ancestry PC1",
                "",
                "Genetic ancestry principal component 1",
            ),
            (
                "sample_qc",
                "ancestry_pc2",
                "float",
                "",
                "",
                "Ancestry PC2",
                "",
                "Genetic ancestry principal component 2",
            ),
            (
                "sample_qc",
                "kinship_flag",
                "boolean",
                "",
                "",
                "Kinship flag",
                "",
                "In a related pair",
            ),
            (
                "genetic_data",
                "cpra",
                "string",
                "global",
                "",
                "Variant CPRA",
                "",
                "Variant identifier",
            ),
            (
                "genetic_data",
                "dosage_r2",
                "float",
                "",
                "",
                "Imputation DR2",
                "",
                "Variant-level imputation quality (dosage r2)",
            ),
        ]
        w.writerows(rows)

    with open(os.path.join(out, "coding_dictionary.csv"), "w", newline="") as f:
        w = csv.writer(f, lineterminator="\n")
        w.writerow(["coding_name", "code", "meaning", "display_order", "parent_code"])
        rows = [
            ("SEX", "M", "Male", "1", ""),
            ("SEX", "F", "Female", "2", ""),
            ("CONSENT", "consented", "Consented", "1", ""),
            ("CONSENT", "withdrawn", "Withdrawn", "2", ""),
            ("SOURCE", "array", "Array direct call", "1", ""),
            ("SOURCE", "imputed", "Imputed dosage", "2", ""),
            ("ANC", "EUR", "European-like", "1", ""),
            ("ANC", "SAS", "South Asian-like", "2", ""),
            ("ANC", "AFR", "African-like", "3", ""),
            ("ANC", "EAS", "East Asian-like", "4", ""),
            ("GT", "0", "Homozygous reference", "1", ""),
            ("GT", "1", "Heterozygous", "2", ""),
            ("GT", "2", "Homozygous alternate", "3", ""),
            ("GT", "-1", "Missing", "4", ""),
            # OFH special-value conventions, mirrored from the real v14 codings
            ("SPECIAL", "-999", "Suppressed", "1", ""),
            ("SPECIAL", "-1", "Do not know", "2", ""),
            ("SPECIAL", "-3", "Prefer not to provide", "3", ""),
        ]
        w.writerows(rows)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="data/synthetic")
    args = ap.parse_args()
    out = args.out
    os.makedirs(out, exist_ok=True)
    random.seed(42)
    np.random.seed(42)

    write_dictionaries(out)
    write_variant_manifest(out)

    # the request
    pd.DataFrame(
        [
            {
                "study_id": "OFH-CRRS-DEMO-001",
                "cpra": CPRA,
                "chrom": "10",
                "pos": 119669928,
                "ref": "C",
                "alt": "G",
                "build": "GRCh38",
                "carrier_definition": "het_and_homalt",
                "requested_source": "array_and_imputed",
                "purpose": "Recontact feasibility: BAG3 carriers for external cardiology study",
            }
        ]
    ).to_csv(os.path.join(out, "variant_request.csv"), index=False)
    write_wave11_requests(out)

    # carriers + special cases
    carrier_idx = sorted(random.sample(range(N), 22))
    S = {
        "withdrawn": carrier_idx[0],
        "lowcall": [carrier_idx[1], carrier_idx[2]],
        "lowgq": carrier_idx[3],
        "missing": carrier_idx[4],
        "imputed_only": [carrier_idx[5], carrier_idx[6], carrier_idx[7]],
        "borderline": carrier_idx[8],
        "sexfail": carrier_idx[9],
        "kinpair": [carrier_idx[10], carrier_idx[11]],
    }
    imp_only = set(S["imputed_only"]) | {S["borderline"]}
    carriers = set(carrier_idx)

    parts = []
    for i in range(N):
        parts.append(
            dict(
                i=i,
                participant_id=f"OFH{100000 + i}",
                pseudo_id=f"PSU-{random.randrange(16**6):06x}",
                sex=random.choice(["M", "F"]),
                ancestry_stub=random.choices(["EUR", "SAS", "AFR", "EAS"], weights=[70, 12, 10, 8])[
                    0
                ],
                consent_status=("withdrawn" if i == S["withdrawn"] else "consented"),
                baseline_qc_pass=True,
                carrier=(i in carriers),
            )
        )

    pd.DataFrame(
        [
            {
                k: p[k]
                for k in [
                    "participant_id",
                    "pseudo_id",
                    "sex",
                    "ancestry_stub",
                    "consent_status",
                    "baseline_qc_pass",
                ]
            }
            for p in parts
        ]
    ).to_parquet(os.path.join(out, "participant_table.parquet"), index=False)

    # genotype slice (long-form: array rows + imputed rows) + vcf/bgen-shaped fixtures (same data)
    g, vcf_array, bgen_imputed = [], [], []
    for p in parts:
        if p["i"] not in imp_only:  # array row
            gt = 2 if (p["carrier"] and random.random() < 0.1) else (1 if p["carrier"] else 0)
            gq, cr = random.randint(30, 60), round(random.uniform(0.985, 0.999), 4)
            if p["i"] == S["missing"]:
                gt, gq, cr = -1, 0, round(random.uniform(0.90, 0.95), 4)
            if p["i"] in S["lowcall"]:
                cr = round(random.uniform(0.93, 0.975), 4)
            if p["i"] == S["lowgq"]:
                gq = 15
            g.append(
                dict(
                    participant_id=p["participant_id"],
                    cpra=CPRA,
                    source="array",
                    gt_code=gt,
                    gq=gq,
                    call_rate=cr,
                    dosage=np.nan,
                    max_gp=np.nan,
                )
            )
            vcf_array.append(
                dict(
                    participant_id=p["participant_id"],
                    cpra=CPRA,
                    gt=_VCF_GT[gt],
                    gq=gq,
                    call_rate=cr,
                )
            )
        # imputed row (everyone)
        if p["carrier"]:
            if random.random() < 0.1:
                dos, mg = round(random.uniform(1.9, 2.0), 3), 0.95
            else:
                dos, mg = round(random.uniform(0.9, 1.1), 3), 0.94
        else:
            dos, mg = round(random.uniform(0.0, 0.05), 3), 0.985
        if p["i"] == S["borderline"]:
            dos, mg = round(random.uniform(0.5, 0.65), 3), 0.62
        g.append(
            dict(
                participant_id=p["participant_id"],
                cpra=CPRA,
                source="imputed",
                gt_code=np.nan,
                gq=np.nan,
                call_rate=np.nan,
                dosage=dos,
                max_gp=mg,
            )
        )
        gp = _gp_triple(dos, mg)
        bgen_imputed.append(
            dict(
                participant_id=p["participant_id"],
                cpra=CPRA,
                dosage=dos,
                gp_00=gp[0],
                gp_01=gp[1],
                gp_11=gp[2],
            )
        )
    append_wave11_genotypes(g, vcf_array, bgen_imputed, parts)
    pd.DataFrame(g).to_parquet(os.path.join(out, "genotype_slice.parquet"), index=False)
    # vcf/bgen-shaped stand-ins: same genotypes, different on-disk shape (read via GenotypeSource)
    pd.DataFrame(vcf_array).to_csv(os.path.join(out, "array_calls_vcf.tsv"), sep="\t", index=False)
    pd.DataFrame(bgen_imputed).to_csv(
        os.path.join(out, "imputed_calls_bgen.tsv"), sep="\t", index=False
    )

    # sample QC
    kin = set(S["kinpair"])
    q = []
    for p in parts:
        acr = round(random.uniform(0.985, 0.999), 4)
        if p["i"] in S["lowcall"]:
            acr = round(random.uniform(0.93, 0.975), 4)
        q.append(
            dict(
                participant_id=p["participant_id"],
                array_call_rate=acr,
                het_rate=round(random.uniform(0.18, 0.34), 3),
                sex_check_pass=(p["i"] != S["sexfail"]),
                ancestry_pc1=round(random.uniform(-0.02, 0.02), 4),
                ancestry_pc2=round(random.uniform(-0.02, 0.02), 4),
                kinship_flag=(p["i"] in kin),
            )
        )
    pd.DataFrame(q).to_csv(os.path.join(out, "sample_qc_metrics.tsv"), sep="\t", index=False)

    write_batch_second_variant(out)

    print(f"Wrote OFH-shaped inputs to {out}/  (true carriers: {len(carriers)})")
    print(
        "Special cases:",
        json.dumps(
            {
                "withdrawn": parts[S["withdrawn"]]["participant_id"],
                "lowcall": [parts[i]["participant_id"] for i in S["lowcall"]],
                "lowgq": parts[S["lowgq"]]["participant_id"],
                "missing": parts[S["missing"]]["participant_id"],
                "imputed_only": [parts[i]["participant_id"] for i in S["imputed_only"]],
                "borderline": parts[S["borderline"]]["participant_id"],
                "sexfail": parts[S["sexfail"]]["participant_id"],
                "kinpair": [parts[i]["participant_id"] for i in S["kinpair"]],
            },
            indent=2,
        ),
    )


if __name__ == "__main__":
    main()
