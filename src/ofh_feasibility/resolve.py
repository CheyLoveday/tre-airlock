"""resolve — pure WAVE_11 gene/disease request resolution.

Gene and disease requests reduce to an existing `BatchRequest`: a curated set of variant CPRAs
whose union is counted by the already-governed batch path. The default catalogue is a demo
dictionary, not a validated clinical gene panel, and can be replaced through
`Config.variant_catalog_path`.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from .models import BatchRequest, DiseaseRequest, GeneRequest, VariantRequest

CHEK2_C1100DELC = "22:28695868:AG:A"
CHEK2_I157T = "22:28725099:A:G"
BRCA1_DEMO = "17:43044295:G:A"
BRCA2_DEMO = "13:32316461:C:T"
PALB2_DEMO = "16:23614412:G:A"
ATM_DEMO = "11:108236123:C:T"

DEFAULT_CATALOG_PATH = (
    Path(__file__).resolve().parents[2] / "configs" / "catalogs" / "demo_variant_catalog.yaml"
)


def _as_list(value: Any, *, key: str) -> list[str]:
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        raise ValueError(f"catalog key {key!r} must be a list of strings")
    return value


def load_catalog(path: str | Path | None = None) -> dict:
    """Load and validate the configurable variant/gene/panel catalogue."""
    catalog_path = Path(path) if path is not None else DEFAULT_CATALOG_PATH
    with catalog_path.open() as fh:
        raw = yaml.safe_load(fh) or {}
    variants_raw = raw.get("variants")
    genes_raw = raw.get("genes")
    panels_raw = raw.get("panels")
    if not isinstance(variants_raw, dict) or not variants_raw:
        raise ValueError("catalog must define at least one variant")
    if not isinstance(genes_raw, dict) or not genes_raw:
        raise ValueError("catalog must define at least one gene")
    if not isinstance(panels_raw, dict) or not panels_raw:
        raise ValueError("catalog must define at least one panel")

    variants: dict[str, dict] = {}
    for variant_id, item in variants_raw.items():
        if not isinstance(item, dict):
            raise ValueError(f"catalog variant {variant_id!r} must be a mapping")
        missing = {"cpra", "chrom", "pos", "ref", "alt"} - set(item)
        if missing:
            raise ValueError(f"catalog variant {variant_id!r} missing {sorted(missing)}")
        variant = {
            "cpra": str(item["cpra"]),
            "chrom": str(item["chrom"]),
            "pos": int(item["pos"]),
            "ref": str(item["ref"]),
            "alt": str(item["alt"]),
            "annotation": str(item.get("annotation", "")),
        }
        try:
            VariantRequest.from_dict(
                {
                    "study_id": "CATALOG_VALIDATION",
                    "cpra": variant["cpra"],
                    "chrom": variant["chrom"],
                    "pos": variant["pos"],
                    "ref": variant["ref"],
                    "alt": variant["alt"],
                    "build": "GRCh38",
                    "carrier_definition": "het_and_homalt",
                    "requested_source": "array_and_imputed",
                    "purpose": "catalog validation",
                }
            )
        except ValueError as exc:
            raise ValueError(f"catalog variant {variant_id!r} invalid: {exc}") from exc
        variants[str(variant_id)] = variant

    genes: dict[str, tuple[str, ...]] = {}
    gene_spans: dict[str, dict] = {}
    for symbol, item in genes_raw.items():
        if not isinstance(item, dict):
            raise ValueError(f"catalog gene {symbol!r} must be a mapping")
        missing_span = {"chrom", "start", "end"} - set(item)
        if missing_span:
            raise ValueError(f"catalog gene {symbol!r} missing {sorted(missing_span)}")
        span = {
            "chrom": str(item["chrom"]),
            "start": int(item["start"]),
            "end": int(item["end"]),
        }
        if span["start"] < 1 or span["end"] < span["start"]:
            raise ValueError(f"catalog gene {symbol!r} has invalid span {span}")
        refs = tuple(_as_list(item.get("variants"), key=f"genes.{symbol}.variants"))
        unknown = [ref for ref in refs if ref not in variants]
        if unknown:
            raise ValueError(f"catalog gene {symbol!r} references unknown variants {unknown}")
        outside = [
            ref for ref in refs
            if variants[ref]["chrom"] != span["chrom"]
            or not (span["start"] <= variants[ref]["pos"] <= span["end"])
        ]
        if outside:
            examples = [
                f"{ref} at {variants[ref]['chrom']}:{variants[ref]['pos']}"
                for ref in outside[:3]
            ]
            raise ValueError(
                f"catalog gene {symbol!r} variant(s) outside configured gene span "
                f"{span['chrom']}:{span['start']}-{span['end']}: {examples}"
            )
        key = str(symbol).strip().upper()
        genes[key] = refs
        gene_spans[key] = span

    panels: dict[str, tuple[str, ...]] = {}
    for panel, item in panels_raw.items():
        if not isinstance(item, dict):
            raise ValueError(f"catalog panel {panel!r} must be a mapping")
        refs = tuple(
            gene.strip().upper()
            for gene in _as_list(item.get("genes"), key=f"panels.{panel}.genes")
        )
        unknown = [ref for ref in refs if ref not in genes]
        if unknown:
            raise ValueError(f"catalog panel {panel!r} references unknown genes {unknown}")
        panels[str(panel).strip().lower()] = refs

    return {
        "variants": variants,
        "genes": genes,
        "gene_spans": gene_spans,
        "panels": panels,
        "path": str(catalog_path),
    }


def _variant_request(
    variant_id: str, catalog: dict, study_id: str, purpose: str, requested_source: str
) -> VariantRequest:
    v = catalog["variants"][variant_id]
    return VariantRequest.from_dict(
        {
            "study_id": study_id,
            "cpra": v["cpra"],
            "chrom": v["chrom"],
            "pos": v["pos"],
            "ref": v["ref"],
            "alt": v["alt"],
            "build": "GRCh38",
            "carrier_definition": "het_and_homalt",
            "requested_source": requested_source,
            "purpose": purpose,
        }
    )


def resolve_gene(request: GeneRequest, catalog_path: str | Path | None = None) -> BatchRequest:
    """Resolve a gene symbol to a governed batch/union request."""
    catalog = load_catalog(catalog_path)
    genes = catalog["genes"]
    if request.symbol not in genes:
        raise ValueError(f"unknown demo gene {request.symbol!r}; choose from {sorted(genes)}")
    variants = tuple(
        _variant_request(
            variant_id, catalog, request.study_id, request.purpose, request.requested_source
        )
        for variant_id in genes[request.symbol]
    )
    return BatchRequest(study_id=request.study_id, purpose=request.purpose, variants=variants)


def resolve_disease(
    request: DiseaseRequest, catalog_path: str | Path | None = None
) -> BatchRequest:
    """Resolve a disease-panel id to a governed batch/union request."""
    catalog = load_catalog(catalog_path)
    panels = catalog["panels"]
    genes = catalog["genes"]
    if request.panel not in panels:
        raise ValueError(f"unknown demo panel {request.panel!r}; choose from {sorted(panels)}")
    variant_ids = []
    for gene in panels[request.panel]:
        variant_ids.extend(genes[gene])
    variant_ids = list(dict.fromkeys(variant_ids))
    variants = tuple(
        _variant_request(
            variant_id, catalog, request.study_id, request.purpose, request.requested_source
        )
        for variant_id in variant_ids
    )
    return BatchRequest(study_id=request.study_id, purpose=request.purpose, variants=variants)


def catalog_cpras(catalog_path: str | Path | None = None) -> tuple[str, ...]:
    """All demo catalogue CPRAs; useful for tests and synthetic-data generation."""
    catalog = load_catalog(catalog_path)
    return tuple(item["cpra"] for item in catalog["variants"].values())
