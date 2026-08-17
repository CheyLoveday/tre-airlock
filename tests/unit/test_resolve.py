"""Unit tests for the WAVE_11 pure gene/disease resolver."""

import pytest

from ofh_feasibility import resolve
from ofh_feasibility.models import DiseaseRequest, GeneRequest

pytestmark = pytest.mark.unit


def test_resolve_chek2_gene_to_two_variant_batch():
    request = GeneRequest(
        study_id="G1",
        symbol="chek2",
        purpose="CHEK2 gene feasibility",
    )
    batch = resolve.resolve_gene(request)

    assert batch.study_id == "G1"
    assert [v.cpra for v in batch.variants] == [
        resolve.CHEK2_C1100DELC,
        resolve.CHEK2_I157T,
    ]
    assert all(v.requested_source == "array_and_imputed" for v in batch.variants)


def test_resolve_breast_cancer_panel_contains_demo_genes():
    request = DiseaseRequest(
        study_id="D1",
        panel="breast_cancer",
        purpose="demo breast cancer panel feasibility",
    )
    batch = resolve.resolve_disease(request)

    assert len(batch.variants) == 6
    assert set(v.cpra for v in batch.variants) == set(resolve.catalog_cpras())


def test_resolve_disease_deduplicates_overlapping_genes_from_catalog(tmp_path):
    catalog_path = tmp_path / "catalog.yaml"
    catalog_path.write_text(
        """\
variants:
  c1100:
    cpra: "22:28695868:AG:A"
    chrom: "22"
    pos: 28695868
    ref: "AG"
    alt: "A"
  i157t:
    cpra: "22:28725099:A:G"
    chrom: "22"
    pos: 28725099
    ref: "A"
    alt: "G"
genes:
  CHEK2:
    chrom: "22"
    start: 28687738
    end: 28742422
    variants: ["c1100", "i157t"]
panels:
  overlap_demo:
    genes: ["CHEK2", "CHEK2"]
"""
    )
    request = DiseaseRequest(
        study_id="D2",
        panel="overlap_demo",
        purpose="overlap panel feasibility",
    )
    batch = resolve.resolve_disease(request, catalog_path)

    assert [v.cpra for v in batch.variants] == [
        resolve.CHEK2_C1100DELC,
        resolve.CHEK2_I157T,
    ]


def test_catalog_gene_span_rejects_out_of_span_variant(tmp_path):
    catalog_path = tmp_path / "catalog.yaml"
    catalog_path.write_text(
        """\
variants:
  c1100:
    cpra: "22:28695868:AG:A"
    chrom: "22"
    pos: 28695868
    ref: "AG"
    alt: "A"
genes:
  CHEK2:
    chrom: "22"
    start: 1
    end: 10
    variants: ["c1100"]
panels:
  chek2_only:
    genes: ["CHEK2"]
"""
    )

    with pytest.raises(ValueError, match="outside configured gene span"):
        resolve.load_catalog(catalog_path)


def test_catalog_rejects_cpra_that_disagrees_with_variant_fields(tmp_path):
    catalog_path = tmp_path / "catalog.yaml"
    catalog_path.write_text(
        """\
variants:
  c1100:
    cpra: "22:1:AG:A"
    chrom: "22"
    pos: 28695868
    ref: "AG"
    alt: "A"
genes:
  CHEK2:
    chrom: "22"
    start: 28687738
    end: 28742422
    variants: ["c1100"]
panels:
  chek2_only:
    genes: ["CHEK2"]
"""
    )

    with pytest.raises(ValueError, match="catalog variant 'c1100' invalid"):
        resolve.load_catalog(catalog_path)


def test_unknown_gene_fails_fast():
    request = GeneRequest(study_id="G2", symbol="NOTAGENE", purpose="x")
    with pytest.raises(ValueError, match="unknown demo gene"):
        resolve.resolve_gene(request)
