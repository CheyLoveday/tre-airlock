from pathlib import Path

import pytest
from pydantic import ValidationError

from ofh_feasibility.config import Config, load_config
from ofh_feasibility.models import (
    GENOTYPE_SLICE_COLUMNS,
    BatchRequest,
    VariantRequest,
    require_columns,
)

pytestmark = pytest.mark.unit

GOOD_CONFIG = dict(
    array_call_rate_min=0.98, array_gq_min=20, imputed_dr2_min=0.3,
    imputed_dr2_high_confidence=0.8, imputed_dosage_carrier_threshold=0.5,
    imputed_max_gp_min=0.9, carrier_definition="het_and_homalt", require_consent=True,
    sdc_min_cell=10, sdc_round_to=5, data_dir="data", results_dir="results",
)
GOOD_REQUEST = dict(
    study_id="S1", cpra="10:119669928:C:G", chrom="10", pos=119669928, ref="C", alt="G",
    build="GRCh38", carrier_definition="het_and_homalt", requested_source="array_and_imputed",
    purpose="demo",
)


def test_config_from_dict_ok():
    cfg = Config.from_dict(GOOD_CONFIG)
    assert cfg.array_gq_min == 20
    assert cfg.require_consent is True
    assert cfg.imputed_dr2_min == 0.3
    assert cfg.imputed_info_min == 0.3


def test_config_accepts_legacy_imputed_info_keys():
    legacy = {**GOOD_CONFIG}
    legacy.pop("imputed_dr2_min")
    legacy.pop("imputed_dr2_high_confidence")
    legacy["imputed_info_min"] = 0.4
    legacy["imputed_info_high_confidence"] = 0.9
    cfg = Config.from_dict(legacy)
    assert cfg.imputed_dr2_min == 0.4
    assert cfg.imputed_dr2_high_confidence == 0.9


def test_config_rejects_conflicting_dr2_aliases():
    with pytest.raises(ValidationError, match="sets both"):
        Config.from_dict({**GOOD_CONFIG, "imputed_info_min": 0.4})


def test_config_missing_key_raises():
    with pytest.raises(ValidationError):
        Config.from_dict({"array_call_rate_min": 0.98})


def test_config_rejects_disabling_consent():
    # the consent gate is non-negotiable: require_consent=False must fail fast at load
    with pytest.raises(ValidationError, match="consent gate is non-negotiable"):
        Config.from_dict({**GOOD_CONFIG, "require_consent": False})


def test_config_rejects_round_not_dividing_min_cell():
    # rounding base must divide the min cell so a released count can't round below the threshold
    with pytest.raises(ValidationError, match="must be a positive divisor"):
        Config.from_dict({**GOOD_CONFIG, "sdc_min_cell": 10, "sdc_round_to": 7})


def test_config_rejects_subminimum_sdc_floor():
    for min_cell in (0, 1, 4):
        with pytest.raises(ValidationError, match="sdc_min_cell must be >= 5"):
            Config.from_dict({**GOOD_CONFIG, "sdc_min_cell": min_cell, "sdc_round_to": 1})


def test_config_rejects_out_of_range_quality_thresholds():
    bad_values = {
        "array_call_rate_min": -0.1,
        "imputed_dr2_min": 1.1,
        "imputed_dr2_high_confidence": 1.1,
        "imputed_max_gp_min": 1.1,
    }
    for key, value in bad_values.items():
        with pytest.raises(ValidationError, match="between 0 and 1"):
            Config.from_dict({**GOOD_CONFIG, key: value})
    with pytest.raises(ValidationError, match="dosage.*between 0 and 2"):
        Config.from_dict({**GOOD_CONFIG, "imputed_dosage_carrier_threshold": 2.1})


def test_config_rejects_negative_gq_and_inverted_dr2_tiers():
    with pytest.raises(ValidationError, match="array_gq_min must be non-negative"):
        Config.from_dict({**GOOD_CONFIG, "array_gq_min": -1})
    with pytest.raises(ValidationError, match="high_confidence must be >= imputed_dr2_min"):
        Config.from_dict(
            {**GOOD_CONFIG, "imputed_dr2_min": 0.8, "imputed_dr2_high_confidence": 0.3}
        )


def test_config_accepts_dividing_sdc():
    cfg = Config.from_dict({**GOOD_CONFIG, "sdc_min_cell": 20, "sdc_round_to": 10})
    assert cfg.sdc_round_to == 10


def test_load_config_reads_repo_yaml():
    assert load_config("config.yaml").sdc_min_cell == 10


def test_example_configs_load():
    expected = {
        "single_variant_simplified.yaml",
        "ofh_tre_chek2_i157t.yaml",
        "gene_panel_simplified.yaml",
    }
    example_config_dir = Path("configs/examples")
    paths = sorted(example_config_dir.glob("*.yaml"))
    assert {path.name for path in paths} == expected
    for path in paths:
        cfg = load_config(path)
        assert cfg.require_consent is True
        assert cfg.sdc_min_cell % cfg.sdc_round_to == 0
        assert cfg.variant_identifiability_path == "docs/reference/variant-identifiability.csv"
        assert cfg.variant_catalog_path == "configs/catalogs/demo_variant_catalog.yaml"


def test_variant_request_ok():
    r = VariantRequest.from_dict(GOOD_REQUEST)
    assert r.pos == 119669928
    assert r.requested_source == "array_and_imputed"


def test_variant_request_bad_build_raises():
    with pytest.raises(ValidationError):
        VariantRequest.from_dict({**GOOD_REQUEST, "build": "hg19"})


def test_variant_request_cpra_mismatch_raises():
    with pytest.raises(ValidationError):
        VariantRequest.from_dict({**GOOD_REQUEST, "pos": 1})


def test_variant_request_rejects_invalid_chromosome():
    # chr23 / chr0 / chr99 are not real contigs — must fail at the first gate, not at the manifest.
    for chrom in ("23", "0", "99"):
        with pytest.raises(ValidationError, match="invalid chromosome"):
            VariantRequest.from_dict(
                {**GOOD_REQUEST, "cpra": f"{chrom}:100:C:G", "chrom": chrom, "pos": 100}
            )


def test_variant_request_rejects_nonpositive_pos():
    with pytest.raises(ValidationError, match="1-based positive integer"):
        VariantRequest.from_dict({**GOOD_REQUEST, "cpra": "10:0:C:G", "pos": 0})


def test_variant_request_rejects_pos_past_contig_end():
    # a coordinate past the contig length is impossible on GRCh38 — wrong build/contig.
    beyond = 133797422 + 1  # chr10 length + 1
    with pytest.raises(ValidationError, match="out of range"):
        VariantRequest.from_dict({**GOOD_REQUEST, "cpra": f"10:{beyond}:C:G", "pos": beyond})


def test_variant_request_rejects_ref_equals_alt():
    # REF == ALT describes no change; it is not a variant and must fail at the boundary.
    for ref_alt in ("C", "CG"):
        with pytest.raises(ValidationError, match="REF == ALT"):
            VariantRequest.from_dict(
                {**GOOD_REQUEST, "cpra": f"10:100:{ref_alt}:{ref_alt}", "pos": 100,
                 "ref": ref_alt, "alt": ref_alt}
            )


def test_batch_request_rejects_extra_fields_and_empty_variants():
    request = VariantRequest.from_dict(GOOD_REQUEST)
    with pytest.raises(ValidationError, match="Extra inputs are not permitted"):
        BatchRequest(study_id="B1", purpose="demo", variants=(request,), injected="x")
    with pytest.raises(ValidationError, match="batch request has no variants"):
        BatchRequest(study_id="B1", purpose="demo", variants=())


def test_require_columns_raises_on_missing():
    with pytest.raises(ValueError):
        require_columns(["participant_id"], GENOTYPE_SLICE_COLUMNS, "genotype_slice")
