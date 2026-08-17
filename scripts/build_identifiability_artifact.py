#!/usr/bin/env python3
"""Build the small Wave 15 identifiability artifact from public OFH CPRA lists.

The raw lists stay local-only. This script streams the array CSV and imputed ZIP, records exact CPRA
resource membership plus annotation-reliability flags, and writes a small CSV/provenance pair
suitable for the clean review snapshot.

The output columns `on_array` and `on_imputed` are resource-membership facts: exact CPRA present in
the public array list or imputed list. They are not claims that evidence was used, that DR2 passed,
or that participant-level genotype data exists in this repository.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import zipfile
from datetime import UTC, datetime
from pathlib import Path


def _sha256(path: Path, chunk_size: int = 1024 * 1024) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(chunk_size), b""):
            h.update(chunk)
    return h.hexdigest()


def _flag_reliable(value: str, *, true_word: str) -> bool:
    return value.strip().upper() != true_word.upper()


def _column_indices(header: bytes, *, cpra_col: str, flag_col: str) -> tuple[int, int]:
    fields = header.decode("utf-8", errors="replace").strip().split(",")
    return fields.index(cpra_col), fields.index(flag_col)


def _scan_binary_lines(
    lines, targets: set[str], *, cpra_col: str, flag_col: str, unreliable_value: str
) -> dict[str, dict]:
    hits: dict[str, dict] = {}
    target_bytes = {target.encode("utf-8"): target for target in targets}
    header = next(lines)
    cpra_idx, flag_idx = _column_indices(header, cpra_col=cpra_col, flag_col=flag_col)
    for line_number, line in enumerate(lines, start=2):
        parts = line.rstrip(b"\r\n").split(b",")
        if len(parts) <= max(cpra_idx, flag_idx):
            continue
        cpra = target_bytes.get(parts[cpra_idx])
        if cpra is None:
            continue
        flag = parts[flag_idx].decode("utf-8", errors="replace")
        hits[cpra] = {
            "line": line_number,
            "flag": flag,
            "reliable": _flag_reliable(flag, true_word=unreliable_value),
        }
        if len(hits) == len(targets):
            break
    return hits


def _scan_csv(
    path: Path, targets: set[str], *, cpra_col: str, flag_col: str, unreliable_value: str
) -> dict[str, dict]:
    with path.open("rb") as fh:
        return _scan_binary_lines(
            fh,
            targets,
            cpra_col=cpra_col,
            flag_col=flag_col,
            unreliable_value=unreliable_value,
        )


def _scan_zipped_csv(
    path: Path, targets: set[str], *, cpra_col: str, flag_col: str, unreliable_value: str
) -> dict[str, dict]:
    with zipfile.ZipFile(path) as archive:
        for member_name in archive.namelist():
            if member_name.endswith("/") or member_name.startswith("__MACOSX"):
                continue
            with archive.open(member_name) as member:
                return _scan_binary_lines(
                    member,
                    targets,
                    cpra_col=cpra_col,
                    flag_col=flag_col,
                    unreliable_value=unreliable_value,
                )
    return {}


def _evidence(cpra: str, array_hit: dict | None, imputed_hit: dict | None) -> str:
    array = (
        f"array resource line {array_hit['line']}: exact CPRA present; "
        f"Inaccurate Call={array_hit['flag']}"
        if array_hit
        else "array resource: no exact CPRA hit"
    )
    imputed = (
        "imputed resource line "
        f"{imputed_hit['line']}: exact CPRA present; "
        f"inaccurate.annotation={imputed_hit['flag']}"
        if imputed_hit
        else "imputed resource: no exact CPRA hit"
    )
    return f"{array}; {imputed}"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Build docs/reference/variant-identifiability.csv from public CPRA lists."
    )
    parser.add_argument("--array-list", required=True, type=Path)
    parser.add_argument("--imputed-list", required=True, type=Path)
    parser.add_argument("--out", required=True, type=Path)
    parser.add_argument("--provenance", required=True, type=Path)
    parser.add_argument(
        "--source-release", default="OFH public Release 14 GRCh38 CPRA lists"
    )
    parser.add_argument("--cpra", action="append", required=True)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    targets = set(args.cpra)
    array_hits = _scan_csv(
        args.array_list,
        targets,
        cpra_col="variant_id",
        flag_col="Inaccurate Call",
        unreliable_value="Yes",
    )
    imputed_hits = _scan_zipped_csv(
        args.imputed_list,
        targets,
        cpra_col="cpra_grch38",
        flag_col="inaccurate.annotation",
        unreliable_value="TRUE",
    )

    args.out.parent.mkdir(parents=True, exist_ok=True)
    rows = []
    for cpra in args.cpra:
        array_hit = array_hits.get(cpra)
        imputed_hit = imputed_hits.get(cpra)
        reliable = all(
            hit["reliable"] for hit in (array_hit, imputed_hit) if hit is not None
        )
        rows.append(
            {
                "cpra": cpra,
                "on_array": str(array_hit is not None).upper(),
                "on_imputed": str(imputed_hit is not None).upper(),
                "annotation_reliable": str(reliable).upper(),
                "source_release": args.source_release,
                "evidence": _evidence(cpra, array_hit, imputed_hit),
            }
        )
    with args.out.open("w", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=list(rows[0]), lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)

    provenance = {
        "artifact": str(args.out),
        "generated_utc": datetime.now(UTC).isoformat(timespec="seconds"),
        "purpose": (
            "Small public-list-derived grounding artifact for variant identifiability; raw public "
            "lists remain local-only and are not committed."
        ),
        "source_release": args.source_release,
        "raw_files_not_committed": True,
        "source_files": [
            {"path_local_only": str(args.array_list), "sha256": _sha256(args.array_list)},
            {"path_local_only": str(args.imputed_list), "sha256": _sha256(args.imputed_list)},
        ],
        "checks": rows,
    }
    args.provenance.parent.mkdir(parents=True, exist_ok=True)
    args.provenance.write_text(json.dumps(provenance, indent=2) + "\n")


if __name__ == "__main__":
    main()
