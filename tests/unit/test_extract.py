"""Unit tests for extract: variant validation, source decision, slice pivot."""
import numpy as np
import pandas as pd
import pytest

from ofh_feasibility import extract
from ofh_feasibility.config import Config
from ofh_feasibility.models import VariantRequest

pytestmark = pytest.mark.unit

CPRA = "10:119669928:C:G"


def _cfg(**over):
    base = dict(
        array_call_rate_min=0.98, array_gq_min=20, imputed_info_min=0.30,
        imputed_info_high_confidence=0.80, imputed_dosage_carrier_threshold=0.5,
        imputed_max_gp_min=0.90, carrier_definition="het_and_homalt", require_consent=True,
        sdc_min_cell=10, sdc_round_to=5, data_dir="data/synthetic", results_dir="results",
    )
    return Config.from_dict({**base, **over})


def _request(**over):
    base = dict(
        study_id="S1", cpra=CPRA, chrom="10", pos=119669928, ref="C", alt="G", build="GRCh38",
        carrier_definition="het_and_homalt", requested_source="array_and_imputed", purpose="t",
    )
    return VariantRequest.from_dict({**base, **over})


def _manifest(info="0.71", on_array="TRUE", on_imputed="TRUE", **over):
    row = {
        "cpra": CPRA, "chrom": "10", "pos": "119669928", "ref": "C", "alt": "G",
        "build": "GRCh38", "biallelic": "TRUE", "on_array": on_array, "on_imputed": on_imputed,
        "array_maf": "0.013", "imputed_maf": "0.014", "dosage_r2": info, "annotation": "x",
        "inaccurate_annotation": "FALSE", "multiallelic_variant": "FALSE",
    }
    return pd.DataFrame([{**row, **over}])


def test_validate_variant_ok():
    row = extract.validate_variant(_manifest(), _request())
    assert row["cpra"] == CPRA and row["on_array"] == "TRUE"


def test_validate_variant_absent_raises():
    empty = _manifest().iloc[0:0]
    with pytest.raises(ValueError, match="not in resource manifest"):
        extract.validate_variant(empty, _request())


def test_validate_variant_refalt_mismatch_raises():
    bad = _manifest()
    bad.loc[0, "alt"] = "T"  # manifest alt disagrees with the request's alt
    with pytest.raises(ValueError, match="ref/alt orientation mismatch"):
        extract.validate_variant(bad, _request())


def test_validate_variant_inaccurate_annotation_flag_is_no_go():
    flagged = _manifest(inaccurate_annotation="TRUE")
    with pytest.raises(ValueError, match="inaccurate_annotation.*no-go"):
        extract.validate_variant(flagged, _request())


def test_validate_variant_multiallelic_flag_is_no_go():
    flagged = _manifest(multiallelic_variant="TRUE")
    with pytest.raises(ValueError, match="multiallelic.*no-go"):
        extract.validate_variant(flagged, _request())


def test_apply_identifiability_artifact_overlays_public_list_facts():
    manifest = _manifest(on_array="TRUE", on_imputed="TRUE")
    artifact = pd.DataFrame(
        {
            "cpra": [CPRA],
            "on_array": ["FALSE"],
            "on_imputed": ["TRUE"],
            "annotation_reliable": ["FALSE"],
            "source_release": ["OFH public Release 14"],
            "evidence": ["array absent; imputed present but unreliable"],
        }
    )
    out = extract.apply_identifiability_artifact(manifest, artifact)
    row = out.iloc[0]
    assert row["on_array"] == "FALSE"
    assert row["on_imputed"] == "TRUE"
    assert row["inaccurate_annotation"] == "TRUE"


# --- Wave 7: reference-matched variant pre-flight (normalize / build / strand) ----------------

# Mock reference: GRCh38 base C at the BAG3 locus; GRCh37 base C at a different (lifted) position.
_REFERENCE = {
    "bases": {"GRCh38": {"10:119669928": "C", "10:5": "A"}, "GRCh37": {"10:5": "C"}},
    "panel_maf": {"10:119669928:C:G": 0.013},
}


def test_normalize_alleles_snp_is_noop():
    assert extract._normalize_alleles(100, "C", "G") == (100, "C", "G")


def test_normalize_alleles_trims_shared_prefix_and_suffix():
    # GCA/GTA share a G prefix and an A suffix -> parsimonious C/T at pos+1.
    assert extract._normalize_alleles(100, "GCA", "GTA") == (101, "C", "T")


def test_preflight_grch38_reference_match_resolves_build():
    out = extract.normalize_and_reference_match(_request(), _REFERENCE, observed=0.013)
    assert out["build_resolved"] == "GRCh38" and out["ref_matched"] is True
    assert any("confirmed by REF-to-reference match" in c for c in out["caveats"])


def test_preflight_palindromic_snp_strand_resolved_by_af_concordance():
    out = extract.normalize_and_reference_match(_request(), _REFERENCE, observed=0.013)
    assert out["is_palindromic"] is True and out["strand"] == "forward"
    assert out["ambiguous"] is False
    assert any("strand resolved as forward" in c for c in out["caveats"])


def test_preflight_palindromic_strand_flip_detected():
    # Cohort MAF concords with (1 - panel) -> the variant is on the opposite strand.
    out = extract.normalize_and_reference_match(_request(), _REFERENCE, observed=0.987)
    assert out["strand"] == "reverse" and out["ambiguous"] is False


def test_preflight_palindromic_strand_unresolved_emits_caveat_not_silent():
    # No panel MAF for this palindrome -> strand cannot be resolved -> explicit ambiguity caveat.
    ref = {"bases": {"GRCh38": {"10:119669928": "C"}}, "panel_maf": {}}
    out = extract.normalize_and_reference_match(_request(), ref, observed=0.013)
    assert out["ambiguous"] is True and out["strand"] == "unresolved"
    assert any("could NOT be resolved" in c for c in out["caveats"])


def test_preflight_grch37_coordinates_fail_closed():
    # REF matches the GRCh37 base, not GRCh38 -> client gave GRCh37 coords -> fail closed.
    req = _request(cpra="10:5:C:G", pos=5, ref="C", alt="G")
    with pytest.raises(ValueError, match="GRCh37"):
        extract.normalize_and_reference_match(req, _REFERENCE, observed=0.1)


def test_preflight_ref_matches_no_reference_base_fail_closed():
    # GRCh38 base is A, no GRCh37 entry; REF G matches neither -> mis-specified, fail closed.
    ref = {"bases": {"GRCh38": {"10:7": "A"}}, "panel_maf": {}}
    req = _request(cpra="10:7:G:T", pos=7, ref="G", alt="T")
    with pytest.raises(ValueError, match="mis-specified"):
        extract.normalize_and_reference_match(req, ref, observed=0.1)


def test_preflight_unavailable_reference_base_caveats_not_assumes():
    # Position absent from the mock reference -> asserted build kept, but flagged as NOT matched.
    ref = {"bases": {"GRCh38": {}}, "panel_maf": {}}
    out = extract.normalize_and_reference_match(_request(), ref, observed=0.013)
    assert out["ref_matched"] is False
    assert any("NOT reference-matched" in c for c in out["caveats"])


def test_preflight_non_palindromic_snp_has_no_strand_step():
    req = _request(cpra="10:119669928:C:T", ref="C", alt="T")
    ref = {"bases": {"GRCh38": {"10:119669928": "C"}}, "panel_maf": {}}
    out = extract.normalize_and_reference_match(req, ref, observed=0.1)
    assert out["is_palindromic"] is False and out["strand"] == "n/a"
    assert not any("palindromic" in c for c in out["caveats"])


def test_preflight_requested_source_availability_flags_missing_array():
    row = _manifest(on_array="FALSE", on_imputed="TRUE").iloc[0].to_dict()
    out = extract.requested_source_availability(row, _request(requested_source="array"))

    assert out["requested_array"] is True
    assert out["array_available"] is False
    assert out["requested_sources_available"] is False
    assert any("array-direct evidence is unavailable" in c for c in out["source_caveats"])


def test_attach_source_availability_surfaces_requested_source_caveats():
    row = _manifest(on_array="TRUE", on_imputed="FALSE").iloc[0].to_dict()
    preflight = extract.normalize_and_reference_match(_request(), _REFERENCE, observed=0.013)
    out = extract.attach_source_availability(preflight, row, _request())

    assert out["requested_source"] == "array_and_imputed"
    assert out["requested_sources_available"] is False
    assert any("imputed evidence is unavailable" in c for c in out["source_caveats"])
    assert not any("imputed evidence is unavailable" in c for c in out["caveats"])


def test_observed_maf_prefers_array_then_imputed():
    assert extract.observed_maf({"array_maf": "0.013", "imputed_maf": "0.02"}) == 0.013
    assert extract.observed_maf({"array_maf": "NA", "imputed_maf": "0.02"}) == 0.02
    assert extract.observed_maf({"array_maf": "NA", "imputed_maf": "NA"}) is None


# --- Wave 7: input-integrity guards (uniqueness + join cardinality) ---------------------------


def test_assert_unique_key_single_column_raises_on_duplicate():
    df = pd.DataFrame({"participant_id": ["P0", "P1", "P0"]})
    with pytest.raises(ValueError, match=r"participant_table: duplicate participant_id.*P0"):
        extract.assert_unique_key(df, "participant_id", "participant_table")


def test_assert_unique_key_composite_key_raises():
    df = pd.DataFrame({
        "participant_id": ["P0", "P0", "P0"], "cpra": [CPRA, CPRA, CPRA],
        "source": ["array", "imputed", "array"],  # (P0, CPRA, array) duplicated
    })
    with pytest.raises(ValueError, match=r"genotype_slice: duplicate participant_id\+cpra\+source"):
        extract.assert_unique_key(df, ("participant_id", "cpra", "source"), "genotype_slice")


def test_assert_unique_key_passes_when_unique():
    df = pd.DataFrame({"cpra": [CPRA, "10:121000000:A:T"]})
    extract.assert_unique_key(df, "cpra", "variant_manifest")  # no raise


def test_validate_variant_duplicate_manifest_cpra_fails_closed():
    dup = pd.concat([_manifest(), _manifest()], ignore_index=True)  # CPRA appears twice
    with pytest.raises(ValueError, match="variant_manifest: duplicate cpra"):
        extract.validate_variant(dup, _request())


def test_build_candidate_table_duplicate_genotype_row_fails():
    participants, gs, sqc = _cohort()
    gs_dup = pd.concat([gs, gs.iloc[[0]]], ignore_index=True)  # dup (pid, cpra, source)
    with pytest.raises(ValueError, match="genotype_slice: duplicate"):
        extract.build_candidate_table(_request(), participants, gs_dup, sqc)


def test_build_candidate_table_missing_sample_qc_row_fails_closed():
    participants, gs, sqc = _cohort()
    sqc_missing = sqc[sqc["participant_id"] != "P3"]
    with pytest.raises(ValueError, match="participant->sample_qc.*unmatched.*P3"):
        extract.build_candidate_table(_request(), participants, gs, sqc_missing)


def test_assert_join_cardinality_unmatched_left_raises():
    left = pd.DataFrame({"participant_id": ["P0", "P1", "P2"]})
    right = pd.DataFrame({"participant_id": ["P0", "P1"], "v": [1, 2]})  # P2 unmatched
    with pytest.raises(ValueError, match="unmatched in join.*P2"):
        extract.assert_join_cardinality(left, "participant_id", right, "participant_id", "p->qc")


def test_assert_join_cardinality_fanout_right_raises():
    left = pd.DataFrame({"participant_id": ["P0", "P1"]})
    right = pd.DataFrame({"participant_id": ["P0", "P0", "P1"], "v": [1, 2, 3]})  # P0 fans out
    with pytest.raises(ValueError, match="right side.*duplicate"):
        extract.assert_join_cardinality(left, "participant_id", right, "participant_id", "p->qc")


def test_resolve_sources_moderate_info():
    out = extract.resolve_sources(_manifest().iloc[0].to_dict(), _request(), _cfg())
    assert out == {
        "variant_info": 0.71, "use_array": True, "use_imputed": True, "imp_high": False,
        "variant_on_array": True, "variant_on_imputed": True, "annotation_reliable": True,
    }


def test_resolve_sources_na_info_disables_imputed():
    out = extract.resolve_sources(
        _manifest(info="NA").iloc[0].to_dict(), _request(), _cfg()
    )
    assert out["variant_info"] is None and out["use_imputed"] is False


def _cohort():
    participants = pd.DataFrame({
        "participant_id": ["P0", "P1", "P2", "P3"],
        "pseudo_id": ["a", "b", "c", "d"],
        "sex": ["M", "F", "M", "F"], "ancestry_stub": ["EUR"] * 4,
        "consent_status": ["consented", "consented", "consented", "consented"],
        "baseline_qc_pass": [True] * 4,
    })
    rows = []
    for pid, gt, cr in [("P0", 1, 0.99), ("P1", 1, 0.90), ("P2", 0, 0.99)]:  # P3 imputed-only
        rows.append((pid, CPRA, "array", gt, 40, cr, np.nan, np.nan))
    for pid, dos in [("P0", 1.0), ("P1", 1.0), ("P2", 0.01), ("P3", 1.0)]:
        rows.append((pid, CPRA, "imputed", np.nan, np.nan, np.nan, dos, 0.95))
    gs = pd.DataFrame(rows, columns=[
        "participant_id", "cpra", "source", "gt_code", "gq", "call_rate", "dosage", "max_gp"])
    sqc = pd.DataFrame({
        "participant_id": ["P0", "P1", "P2", "P3"], "array_call_rate": [0.99, 0.90, 0.99, np.nan],
        "het_rate": [0.25] * 4, "sex_check_pass": [True] * 4, "ancestry_pc1": [0.0] * 4,
        "ancestry_pc2": [0.0] * 4, "kinship_flag": [False] * 4,
    })
    return participants, gs, sqc


def test_build_candidate_table_pivots_one_row_per_participant():
    participants, gs, sqc = _cohort()
    cand = extract.build_candidate_table(_request(), participants, gs, sqc)
    assert len(cand) == 4
    assert set(extract.CANDIDATE_COLUMNS).issubset(cand.columns)
    p3 = cand[cand["participant_id"] == "P3"].iloc[0]
    assert np.isnan(p3["array_gt_code"]) and p3["imputed_dosage"] == 1.0  # imputed-only


def test_to_genotype_array_array_int8_missing_to_neg1():
    participants, gs, sqc = _cohort()
    cand = extract.build_candidate_table(_request(), participants, gs, sqc)
    arr = extract.to_genotype_array(cand, "array")
    assert arr.dtype == np.int8
    # P3 has no array row -> NaN -> filled to -1
    assert arr[cand["participant_id"].tolist().index("P3")] == -1
