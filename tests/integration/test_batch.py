"""Batch / multi-variant requests resolve to a combined (union) feasibility set."""
import numpy as np
import pandas as pd
import pytest

from ofh_feasibility import io, pipeline
from ofh_feasibility.config import Config
from ofh_feasibility.models import BatchRequest

pytestmark = pytest.mark.integration

CPRA1 = "10:119669928:C:G"
CPRA2 = "10:121000000:A:T"


def _cfg(data, results):
    return Config.from_dict(dict(
        array_call_rate_min=0.98, array_gq_min=20, imputed_info_min=0.30,
        imputed_info_high_confidence=0.80, imputed_dosage_carrier_threshold=0.5,
        imputed_max_gp_min=0.90, carrier_definition="het_and_homalt", require_consent=True,
        sdc_min_cell=10, sdc_round_to=5, data_dir=str(data), results_dir=str(results),
    ))


def _variant2_rows(pids, carriers):
    rows = []
    for i, pid in enumerate(pids):
        c = i in carriers
        rows.append((pid, CPRA2, "array", 1 if c else 0, 40, 0.99, np.nan, np.nan))
        rows.append((pid, CPRA2, "imputed", np.nan, np.nan, np.nan, 1.0 if c else 0.0, 0.95))
    cols = ["participant_id", "cpra", "source", "gt_code", "gq", "call_rate", "dosage", "max_gp"]
    return pd.DataFrame(rows, columns=cols)


def _manifest_rows():
    base = {"chrom": "10", "build": "GRCh38", "biallelic": "TRUE", "on_array": "TRUE",
            "on_imputed": "TRUE", "array_maf": "0.01", "imputed_maf": "0.01", "annotation": "x",
            "inaccurate_annotation": "FALSE", "multiallelic_variant": "FALSE"}
    return pd.DataFrame([
        {**base, "cpra": CPRA1, "pos": "119669928", "ref": "C", "alt": "G",
         "dosage_r2": "0.71"},
        {**base, "cpra": CPRA2, "pos": "121000000", "ref": "A", "alt": "T",
         "dosage_r2": "0.88"},
    ])


@pytest.fixture
def batch_dataset(tmp_path, tiny_cohort):
    data = tmp_path / "synthetic"
    data.mkdir()
    pids = tiny_cohort["participants"]["participant_id"].tolist()
    # BAG3 -> included {3,11,15} (7 withdrawn, 15 imputed-only); variant2 {3,5,11} all consented.
    # union {3,5,11,15} (4); overlap {3,11} (2).
    slice2 = _variant2_rows(pids, carriers={3, 5, 11})
    full_slice = pd.concat([tiny_cohort["genotype_slice"], slice2], ignore_index=True)
    full_slice.to_parquet(data / "genotype_slice.parquet", index=False)
    tiny_cohort["participants"].to_parquet(data / "participant_table.parquet", index=False)
    tiny_cohort["sample_qc"].to_csv(data / "sample_qc_metrics.tsv", sep="\t", index=False)
    _manifest_rows().to_csv(data / "variant_manifest.csv", index=False)
    rows = []
    for cpra, ref, alt, pos in [(CPRA1, "C", "G", 119669928), (CPRA2, "A", "T", 121000000)]:
        rows.append(dict(
            study_id="BATCH", cpra=cpra, chrom="10", pos=pos, ref=ref, alt=alt, build="GRCh38",
            carrier_definition="het_and_homalt", requested_source="array_and_imputed", purpose="x",
        ))
    pd.DataFrame(rows).to_csv(data / "batch_request.csv", index=False)
    return tmp_path, data


def test_batch_resolves_to_combined_union(batch_dataset):
    tmp_path, data = batch_dataset
    batch = io.read_batch_request(data / "batch_request.csv")
    assert [v.cpra for v in batch.variants] == [CPRA1, CPRA2]
    bundle = pipeline.orchestrate_batch(_cfg(data, tmp_path / "results"), batch)
    combined = bundle["combined"]
    assert combined["per_variant"][CPRA1]["included"] == 3   # {3,11,15}
    assert combined["per_variant"][CPRA2]["included"] == 3   # {3,5,11}
    assert combined["combined_carriers"] == 4                # union {3,5,11,15}
    assert combined["overlap_carriers"] == 2                 # carry both: {3,11}
    assert combined["breakdown_suppressed"] is True
    assert (tmp_path / "results" / "batch_feasibility_summary.txt").exists()


def test_batch_goes_through_release_gate_and_audit(batch_dataset):
    # F1: the batch release must be Lean-adjudicated + audited like the single-variant path.
    from ofh_feasibility import audit

    tmp_path, data = batch_dataset
    results = tmp_path / "results"
    batch = io.read_batch_request(data / "batch_request.csv")
    bundle = pipeline.orchestrate_batch(_cfg(data, results), batch)

    assert (results / "batch_release_candidate.json").exists()  # authorized release object staged
    assert (results / "batch_airlock_manifest.json").exists()
    assert (results / "batch_feasibility_summary.txt").exists()  # INTERNAL analyst note
    assert (results / "airlock_pending" / "release.json").exists()  # Lean-emitted payload
    assert not (results / "airlock_pending" / "batch_feasibility_summary.txt").exists()
    assert (results / "airlock_pending" / "batch_airlock_manifest.json").exists()
    assert bundle["release_candidate"].study_id == "BATCH"
    assert bundle["release_candidate"].reported_cells == ()
    manifest = bundle["airlock_manifest"]
    exports = [f for f in manifest["files"] if f["export_to_client"]]
    assert len(exports) == 1 and exports[0]["file"] == "release.json"
    summary_text = (results / "batch_feasibility_summary.txt").read_text()
    assert "PER-VARIANT / OVERLAP BREAKDOWN: SUPPRESSED" in summary_text
    assert CPRA1 not in summary_text and CPRA2 not in summary_text
    assert "of which carry >=2 variants" not in summary_text
    # the run is recorded in the tamper-evident ledger, with no participant data
    events = io.read_jsonl(results / "audit_ledger.jsonl")
    assert any(e["request_id"] == "BATCH" for e in events)
    assert audit.verify_ledger(events, (results / "audit_root.txt").read_text().strip())
    assert not any("participant_id" in str(e) for e in events)


def test_batch_release_suppresses_differencing_breakdown():
    # A + B - union would reveal the overlap, so the release object exposes only the union total.
    from ofh_feasibility import airlock
    from ofh_feasibility.models import BatchRequest

    batch = BatchRequest.from_rows([
        dict(study_id="S", cpra=CPRA1, chrom="10", pos="119669928", ref="C", alt="G",
             build="GRCh38", carrier_definition="het_and_homalt",
             requested_source="array_and_imputed", purpose="p"),
    ])
    combined = {
        "combined_client_total": "~25",
        "overlap_client": "<10",  # A + B - union = 5 would reveal this if A/B were released.
        "breakdown_suppressed": True,
        "per_variant": {
            CPRA1: {"included": 15, "client": "~15"},
            CPRA2: {"included": 15, "client": "~15"},
        },
    }
    candidate = airlock.authorize_release(
        airlock.build_batch_release_candidate(batch, combined, _cfg("d", "r"))
    )
    assert candidate.client_total == "~25"
    assert candidate.breakdown_suppressed is True
    assert candidate.reported_cells == ()


def test_batch_request_from_rows_validates():
    batch = BatchRequest.from_rows([
        dict(study_id="S", cpra=CPRA1, chrom="10", pos="119669928", ref="C", alt="G",
             build="GRCh38", carrier_definition="het_and_homalt",
             requested_source="array_and_imputed", purpose="p"),
    ])
    assert batch.study_id == "S" and len(batch.variants) == 1 and batch.variants[0].pos == 119669928


def test_combine_feasibility_union_and_overlap():
    def _cl(included_ids):
        return pd.DataFrame({
            "participant_id": ["a", "b", "c", "d"],
            "decision": ["included" if x in included_ids else "excluded" for x in "abcd"],
        })
    per_variant = [
        {"cpra": CPRA1, "classified": _cl({"a", "b"})},
        {"cpra": CPRA2, "classified": _cl({"b", "c"})},
    ]
    out = pipeline.combine_feasibility(per_variant, _cfg("d", "r"))
    assert out["combined_carriers"] == 3        # union {a,b,c}
    assert out["overlap_carriers"] == 1         # b carries both
    assert out["breakdown_suppressed"] is True
