"""E2E handover-acceptance: a full governed run-through + the fail-early break battery.

The final pre-handover gate. `test_full_runthrough_*` drives the whole vertical slice
(OFH-shaped inputs -> orchestrate -> governed outputs -> airlock -> Merkle audit) and asserts the
governance invariants on the produced artefacts. The `test_break_*` battery proves every malformed
or unsafe input fails closed at the boundary, BEFORE any count is produced — the "fails early"
property a reviewer should be able to trust.
"""
import json

import pandas as pd
import pytest
from pydantic import ValidationError

from ofh_feasibility import audit, extract, io, pipeline
from ofh_feasibility.config import Config
from ofh_feasibility.models import VariantRequest

pytestmark = pytest.mark.e2e

CPRA = "10:119669928:C:G"

_MANIFEST_ROW = {
    "cpra": CPRA, "chrom": "10", "pos": "119669928", "ref": "C", "alt": "G", "build": "GRCh38",
    "biallelic": "TRUE", "on_array": "TRUE", "on_imputed": "TRUE", "array_maf": "0.013",
    "imputed_maf": "0.014", "dosage_r2": "0.71", "annotation": "bag3",
    "inaccurate_annotation": "FALSE", "multiallelic_variant": "FALSE",
}


def _cfg(data, results, **over):
    base = dict(
        array_call_rate_min=0.98, array_gq_min=20, imputed_info_min=0.30,
        imputed_info_high_confidence=0.80, imputed_dosage_carrier_threshold=0.5,
        imputed_max_gp_min=0.90, carrier_definition="het_and_homalt", require_consent=True,
        sdc_min_cell=10, sdc_round_to=5, data_dir=str(data), results_dir=str(results),
    )
    return Config.from_dict({**base, **over})


def _request(**over):
    base = dict(
        study_id="HANDOVER", cpra=CPRA, chrom="10", pos=119669928, ref="C", alt="G",
        build="GRCh38", carrier_definition="het_and_homalt",
        requested_source="array_and_imputed", purpose="handover acceptance",
    )
    return {**base, **over}


def _manifest(**over):
    return pd.DataFrame([{**_MANIFEST_ROW, **over}])


def _write_inputs(d, tiny_cohort):
    tiny_cohort["participants"].to_parquet(d / "participant_table.parquet", index=False)
    tiny_cohort["genotype_slice"].to_parquet(d / "genotype_slice.parquet", index=False)
    tiny_cohort["sample_qc"].to_csv(d / "sample_qc_metrics.tsv", sep="\t", index=False)
    pd.DataFrame([tiny_cohort["request"]]).to_csv(d / "variant_request.csv", index=False)
    pd.DataFrame([_MANIFEST_ROW]).to_csv(d / "variant_manifest.csv", index=False)


# --- the happy path: a full governed run-through ----------------------------------------------


def test_full_runthrough_writes_every_governed_artefact(tmp_path, tiny_cohort):
    data = tmp_path / "synthetic"
    data.mkdir()
    _write_inputs(data, tiny_cohort)
    results = tmp_path / "results"
    pipeline.orchestrate(_cfg(data, results), VariantRequest.from_dict(tiny_cohort["request"]))
    for name in (
        "internal_carrier_table.parquet", "handoff_to_epi.csv", "feasibility_summary.txt",
        "frequency_control_view.json", "release_candidate.json", "airlock_manifest.json",
        "provenance.json", "audit_ledger.jsonl", "audit_root.txt", "epi_notification.json",
    ):
        assert (results / name).exists(), name


def test_full_runthrough_airlock_releases_exactly_one_human_readable_export(tmp_path, tiny_cohort):
    data = tmp_path / "synthetic"
    data.mkdir()
    _write_inputs(data, tiny_cohort)
    results = tmp_path / "results"
    pipeline.orchestrate(_cfg(data, results), VariantRequest.from_dict(tiny_cohort["request"]))
    manifest = json.loads((results / "airlock_manifest.json").read_text())

    exports = [f for f in manifest["files"] if f["export_to_client"]]
    assert len(exports) == 1  # least privilege: a single client deliverable
    assert exports[0]["file"] == "release.json"  # exact Lean-emitted bytes; the sole release
    assert exports[0]["human_readable"] is True
    assert exports[0]["classification"] == "AIRLOCK-EXPORT-CANDIDATE"
    # the participant-level table is locked down, never exportable
    internal = next(
        f for f in manifest["files"] if f["file"].endswith("internal_carrier_table.parquet")
    )
    assert internal["export_to_client"] is False
    assert internal["classification"] == "INTERNAL-TRE-ONLY"


def test_full_runthrough_export_is_aggregate_only_no_identifiers(tmp_path, tiny_cohort):
    data = tmp_path / "synthetic"
    data.mkdir()
    _write_inputs(data, tiny_cohort)
    results = tmp_path / "results"
    pipeline.orchestrate(_cfg(data, results), VariantRequest.from_dict(tiny_cohort["request"]))

    summary = (results / "feasibility_summary.txt").read_text()
    assert "RECOMMENDATION" in summary  # the decision-ready client note
    # no participant id or pseudo id reaches the client export
    for pid in tiny_cohort["participants"]["participant_id"]:
        assert pid not in summary
    for pseudo in tiny_cohort["participants"]["pseudo_id"]:
        assert pseudo not in summary


def test_full_runthrough_withdrawn_excluded_and_handoff_pseudonymised(tmp_path, tiny_cohort):
    data = tmp_path / "synthetic"
    data.mkdir()
    _write_inputs(data, tiny_cohort)
    results = tmp_path / "results"
    pipeline.orchestrate(_cfg(data, results), VariantRequest.from_dict(tiny_cohort["request"]))

    withdrawn = tiny_cohort["expected"]["withdrawn"]
    internal = pd.read_parquet(results / "internal_carrier_table.parquet")
    included = internal[internal["decision"] == "included"]
    assert withdrawn not in included["participant_id"].tolist()  # consent gate (hard invariant)
    # the withdrawn carrier IS retained in the internal table for audit, with a reason
    row = internal[internal["participant_id"] == withdrawn]
    assert row["decision"].iloc[0] == "excluded" and "consent" in row["reason"].iloc[0]
    handoff = pd.read_csv(results / "handoff_to_epi.csv")
    assert "participant_id" not in handoff.columns  # pseudonymised handoff only


def test_full_runthrough_audit_ledger_verifies_with_no_participant_data(tmp_path, tiny_cohort):
    data = tmp_path / "synthetic"
    data.mkdir()
    _write_inputs(data, tiny_cohort)
    results = tmp_path / "results"
    pipeline.orchestrate(_cfg(data, results), VariantRequest.from_dict(tiny_cohort["request"]))

    events = io.read_jsonl(results / "audit_ledger.jsonl")
    root = (results / "audit_root.txt").read_text().strip()
    assert audit.verify_ledger(events, root)  # tamper-evident Merkle chain holds
    assert not any(audit.has_forbidden_pii(e) for e in events)  # hashes + metadata only (no PII)


# --- the break battery: every malformed / unsafe input must FAIL EARLY -------------------------


@pytest.mark.parametrize(
    "over",
    [
        {"cpra": "chr10-119669928-C-G"},  # not CHR:POS:REF:ALT
        {"cpra": "10:119669928:C:G", "alt": "T"},  # cpra disagrees with alt field
        {"build": "GRCh37"},  # the model asserts GRCh38 by OFH CPRA convention
    ],
    ids=["malformed_cpra", "cpra_field_inconsistent", "non_grch38_build"],
)
def test_break_request_validation_fails_closed(over):
    with pytest.raises(ValidationError):
        VariantRequest.from_dict(_request(**over))


def test_break_variant_absent_from_manifest_fails_closed():
    req = VariantRequest.from_dict(_request(cpra="10:99999999:A:T", pos=99999999, ref="A", alt="T"))
    with pytest.raises(ValueError, match="not in resource manifest"):
        extract.validate_variant(_manifest(), req)


def test_break_refalt_orientation_mismatch_fails_closed():
    with pytest.raises(ValueError, match="ref/alt orientation mismatch"):
        extract.validate_variant(_manifest(alt="T"), VariantRequest.from_dict(_request()))


def test_break_duplicate_manifest_row_fails_closed():
    dup = pd.concat([_manifest(), _manifest()], ignore_index=True)
    with pytest.raises(ValueError, match="variant_manifest: duplicate cpra"):
        extract.validate_variant(dup, VariantRequest.from_dict(_request()))


@pytest.mark.parametrize(
    "flag",
    [{"inaccurate_annotation": "TRUE"}, {"multiallelic_variant": "TRUE"}],
    ids=["inaccurate_annotation", "multiallelic_variant"],
)
def test_break_cpra_list_flag_is_no_go(flag):
    with pytest.raises(ValueError, match="no-go"):
        extract.validate_variant(_manifest(**flag), VariantRequest.from_dict(_request()))


def test_break_grch37_coordinates_fail_closed_in_preflight():
    # REF matches the GRCh37 base, not GRCh38 -> client supplied GRCh37 coords -> fail closed.
    req = VariantRequest.from_dict(_request(cpra="10:5:C:G", pos=5))
    reference = {"bases": {"GRCh38": {"10:5": "A"}, "GRCh37": {"10:5": "C"}}, "panel_maf": {}}
    with pytest.raises(ValueError, match="GRCh37"):
        extract.normalize_and_reference_match(req, reference, observed=0.1)


@pytest.mark.parametrize(
    "over",
    [{"require_consent": False}, {"sdc_round_to": 3}],
    ids=["consent_gate_disabled", "sdc_round_not_dividing_min_cell"],
)
def test_break_unsafe_config_fails_closed(tmp_path, over):
    with pytest.raises(ValidationError):
        _cfg(tmp_path / "d", tmp_path / "r", **over)
