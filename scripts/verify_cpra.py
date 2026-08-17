#!/usr/bin/env python3
"""Verify a CPRA against public OFH CPRA lists.

The public array CSV and imputed ZIP contain variant identifiers, not participant genotypes.
This helper streams plain, gzipped, and zipped CPRA inputs.
It does not extract the large imputed list.
"""

from __future__ import annotations

import argparse
import gzip
import io
import zipfile
from collections.abc import Iterator
from pathlib import Path


def iter_lines(path: Path) -> Iterator[tuple[str, str]]:
    """Yield `(member_name, line)` from plain, gzipped, or zipped CPRA resources."""
    lower_name = path.name.lower()
    if lower_name.endswith(".zip"):
        with zipfile.ZipFile(path) as archive:
            for member_name in archive.namelist():
                if member_name.endswith("/"):
                    continue
                with archive.open(member_name) as member:
                    if member_name.lower().endswith(".gz"):
                        stream = io.TextIOWrapper(
                            gzip.GzipFile(fileobj=member), encoding="utf-8", errors="replace"
                        )
                    else:
                        stream = io.TextIOWrapper(member, encoding="utf-8", errors="replace")
                    for line in stream:
                        yield member_name, line
    elif lower_name.endswith(".gz"):
        with gzip.open(path, "rt", encoding="utf-8", errors="replace") as handle:
            for line in handle:
                yield path.name, line
    else:
        with path.open(encoding="utf-8", errors="replace") as handle:
            for line in handle:
                yield path.name, line


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Verify a chrom:pos:ref:alt CPRA against public OFH CPRA lists."
    )
    parser.add_argument("--chrom", default="10")
    parser.add_argument("--pos", required=True)
    parser.add_argument("--ref")
    parser.add_argument("--alt")
    parser.add_argument("files", nargs="+", type=Path)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    pos = str(args.pos)
    exact = f"{args.chrom}:{pos}:{args.ref}:{args.alt}" if args.ref and args.alt else None

    for path in args.files:
        if not path.exists():
            print(f"[skip] not found: {path}")
            continue
        print(f"\n=== {path} ===")
        hits = 0
        exact_hit = 0
        shown = 0
        for member_name, line in iter_lines(path):
            if pos not in line:
                continue
            hits += 1
            if shown < 12:
                print(f"  [{member_name}] {line.rstrip()}")
                shown += 1
            if exact and exact in line.replace("\t", ":").replace(",", ":"):
                exact_hit += 1
        print(f"  -> lines containing position {pos}: {hits}")
        if exact:
            verdict = "YES" if exact_hit else "NO (not in this file as ref/alt given)"
            print(f"  -> exact CPRA {exact} present: {verdict}")
    print(
        "\nReminder: DR2 / AF are not in the CPRA list; confirm them in the TRE "
        "variant summary-statistics file. The CPRA list only answers presence + ref/alt."
    )


if __name__ == "__main__":
    main()
