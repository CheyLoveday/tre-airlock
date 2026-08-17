"""E2E: the canonical release payload is exactly the Lean-emitted bytes, and nothing else.

Completion-gate evidence (plan §12) plus issues #54/#55/#56, exercised through the REAL
pipeline entrypoints:
- successful egress file bytes are EXACTLY the adjudicator's stdout for the recorded request;
- the egress-pending area contains only the canonical payload (no Python-rendered client text);
- the canonical slot is attempt-scoped: success → refusal → success in the SAME results
  directory behaves per the issue #55 regression sequence;
- the audit record's digests bind to the decision bytes and the published file.
"""
import hashlib
import json
import subprocess

import pandas as pd
import pytest

from ofh_feasibility import airlock, bridge, pipeline
from ofh_feasibility.config import Config
from ofh_feasibility.models import VariantRequest

pytestmark = pytest.mark.e2e


def _cfg(data, results):
    return Config.from_dict(dict(
        array_call_rate_min=0.98, array_gq_min=20, imputed_info_min=0.30,
        imputed_info_high_confidence=0.80, imputed_dosage_carrier_threshold=0.5,
        imputed_max_gp_min=0.90, carrier_definition="het_and_homalt", require_consent=True,
        sdc_min_cell=10, sdc_round_to=5, data_dir=str(data), results_dir=str(results),
    ))


def _write_inputs(d, tiny_cohort):
    tiny_cohort["participants"].to_parquet(d / "participant_table.parquet", index=False)
    tiny_cohort["genotype_slice"].to_parquet(d / "genotype_slice.parquet", index=False)
    tiny_cohort["sample_qc"].to_csv(d / "sample_qc_metrics.tsv", sep="\t", index=False)
    pd.DataFrame([tiny_cohort["request"]]).to_csv(d / "variant_request.csv", index=False)
    pd.DataFrame([{
        "cpra": tiny_cohort["request"]["cpra"], "chrom": "10", "pos": "119669928", "ref": "C",
        "alt": "G", "build": "GRCh38", "biallelic": "TRUE", "on_array": "TRUE",
        "on_imputed": "TRUE", "array_maf": "0.013", "imputed_maf": "0.014", "dosage_r2": "0.71",
        "annotation": "bag3", "inaccurate_annotation": "FALSE", "multiallelic_variant": "FALSE",
    }]).to_csv(d / "variant_manifest.csv", index=False)


def _skip_without_binary():
    if not bridge._TRUSTED_EXE.is_file():
        pytest.skip("airlock not built (make airlock)")


@pytest.fixture()
def run(tmp_path, tiny_cohort):
    _skip_without_binary()
    data = tmp_path / "synthetic"
    data.mkdir()
    _write_inputs(data, tiny_cohort)
    results = tmp_path / "results"
    cfg = _cfg(data, results)
    bundle = pipeline.orchestrate(cfg, VariantRequest.from_dict(tiny_cohort["request"]))
    return cfg, bundle, results


def test_egress_bytes_are_exactly_the_lean_bytes(run):
    _, bundle, results = run
    staged = (results / "airlock_pending" / "release.json").read_bytes()
    decision = bundle["airlock_decision"]
    assert staged == decision.payload_bytes
    direct = subprocess.run(
        [str(bridge._TRUSTED_EXE)], input=decision.request_bytes, capture_output=True
    )
    assert direct.returncode == 0
    assert staged == direct.stdout  # byte-for-byte reproducible from the retained preimage


def test_pending_area_contains_only_the_committed_generation(run):
    _, _, results = run
    staged = sorted(p.name for p in (results / "airlock_pending").iterdir())
    assert staged == ["release.json", "release.ready"]  # payload + its commit receipt


def test_payload_is_the_released_aggregate(run):
    cfg, bundle, results = run
    body = json.loads((results / "airlock_pending" / "release.json").read_text())
    assert body["status"] == "released"
    assert body["schema"] == "tre-airlock/v1"
    assert body["policy"] == {"min_cell": cfg.sdc_min_cell, "round_to": cfg.sdc_round_to}
    assert body["total"] == bundle["release_candidate"].client_total


def test_audit_record_binds_to_the_published_bytes(run):
    # issue #56: the ledger's digests equal the decision's, which equal the file's.
    cfg, bundle, results = run
    record = bundle["audit_event"]["airlock"]
    decision = bundle["airlock_decision"]
    staged = (results / "airlock_pending" / "release.json").read_bytes()
    assert record["payload"]["sha256"] == decision.payload_sha256
    assert record["payload"]["sha256"] == hashlib.sha256(staged).hexdigest()
    assert record["request"]["sha256"] == decision.request_sha256
    assert record["adjudicator"]["sha256"] == decision.adjudicator_sha256
    # the retained preimage exists at the recorded internal path and hashes to the digest.
    retained = results / bridge.EVIDENCE_DIR / f"request-{decision.request_sha256}.json"
    assert str(retained) == record["request"]["retained_internal_path"]
    assert hashlib.sha256(retained.read_bytes()).hexdigest() == record["request"]["sha256"]


def _bypass_build(real):
    def bypass(result, sdc_out, config):
        good = real(result, sdc_out, config)
        return good.model_copy(update={
            "client_total": "~70", "breakdown_suppressed": False,
            "reported_cells": (
                ("array_direct_high_confidence", 70), ("imputed_supported_conditional", 2),
            ),
        })

    return bypass


def test_issue55_regression_sequence(tmp_path, tiny_cohort, monkeypatch):
    # same cfg.results_dir throughout: success -> refusal -> different success (issue #55).
    _skip_without_binary()
    data = tmp_path / "synthetic"
    data.mkdir()
    _write_inputs(data, tiny_cohort)
    results = tmp_path / "results"
    cfg = _cfg(data, results)
    request = VariantRequest.from_dict(tiny_cohort["request"])
    release_path = results / "airlock_pending" / "release.json"
    real = airlock.build_release_candidate

    pipeline.orchestrate(cfg, request)
    assert release_path.exists()
    old = release_path.read_bytes()

    monkeypatch.setattr(airlock, "build_release_candidate", _bypass_build(real))
    with pytest.raises(bridge.AirlockRefusal):
        pipeline.orchestrate(cfg, request)
    assert not release_path.exists(), "refused attempt left the previous payload in place"
    monkeypatch.undo()

    def different(result, sdc_out, config):
        return real(result, sdc_out, config).model_copy(update={"client_total": "~95"})

    monkeypatch.setattr(airlock, "build_release_candidate", different)
    bundle = pipeline.orchestrate(cfg, request)
    fresh = release_path.read_bytes()
    assert fresh != old
    direct = subprocess.run(
        [str(bridge._TRUSTED_EXE)],
        input=bundle["airlock_decision"].request_bytes,
        capture_output=True,
    )
    assert fresh == direct.stdout


def test_refused_run_stages_nothing(tmp_path, tiny_cohort, monkeypatch):
    _skip_without_binary()
    data = tmp_path / "synthetic"
    data.mkdir()
    _write_inputs(data, tiny_cohort)
    results = tmp_path / "results"
    cfg = _cfg(data, results)
    # sabotage the SDC output into the plan §13 bypass shape AFTER Python SDC, so only the
    # runtime Lean airlock stands between the small cell and the egress-pending area.
    monkeypatch.setattr(
        airlock, "build_release_candidate", _bypass_build(airlock.build_release_candidate)
    )
    with pytest.raises(bridge.AirlockRefusal):
        pipeline.orchestrate(cfg, VariantRequest.from_dict(tiny_cohort["request"]))
    pending = results / "airlock_pending"
    assert not (pending / "release.json").exists()
    assert not pending.exists() or not any(pending.iterdir())


def test_audit_append_failure_leaves_no_committed_generation(tmp_path, tiny_cohort, monkeypatch):
    # second review, blocker 3: the audit event is INSIDE the transaction — if it cannot be
    # appended, the generation must not commit and the canonical slot must be empty.
    _skip_without_binary()
    data = tmp_path / "synthetic"
    data.mkdir()
    _write_inputs(data, tiny_cohort)
    cfg = _cfg(data, tmp_path / "results")

    def broken_audit(*args, **kwargs):
        raise RuntimeError("simulated audit append failure")

    monkeypatch.setattr(pipeline, "emit_audit_event", broken_audit)
    with pytest.raises(RuntimeError, match="audit append"):
        pipeline.orchestrate(cfg, VariantRequest.from_dict(tiny_cohort["request"]))
    pending = tmp_path / "results" / "airlock_pending"
    assert not (pending / "release.json").exists()
    assert not (pending / "release.ready").exists()


def test_internal_write_failure_after_lean_success_leaves_no_committed_generation(
    tmp_path, tiny_cohort, monkeypatch
):
    _skip_without_binary()
    data = tmp_path / "synthetic"
    data.mkdir()
    _write_inputs(data, tiny_cohort)
    cfg = _cfg(data, tmp_path / "results")

    def broken_parquet(*args, **kwargs):
        raise OSError("simulated internal write failure")

    monkeypatch.setattr(pipeline.io, "write_parquet", broken_parquet)
    with pytest.raises(OSError, match="internal write"):
        pipeline.orchestrate(cfg, VariantRequest.from_dict(tiny_cohort["request"]))
    pending = tmp_path / "results" / "airlock_pending"
    assert not (pending / "release.json").exists()
    assert not (pending / "release.ready").exists()


def test_cli_audit_verify_fails_after_payload_mutation(tmp_path, tiny_cohort, capsys):
    # item 5: `audit verify` must verify the ARTEFACTS, not just the ledger.
    _skip_without_binary()
    from ofh_feasibility import cli

    data = tmp_path / "synthetic"
    data.mkdir()
    _write_inputs(data, tiny_cohort)
    results = tmp_path / "results"
    cfg = _cfg(data, results)
    pipeline.orchestrate(cfg, VariantRequest.from_dict(tiny_cohort["request"]))
    cfg_path = tmp_path / "config.yaml"
    cfg_path.write_text(
        "array_call_rate_min: 0.98\narray_gq_min: 20\nimputed_info_min: 0.30\n"
        "imputed_info_high_confidence: 0.80\nimputed_dosage_carrier_threshold: 0.5\n"
        "imputed_max_gp_min: 0.90\ncarrier_definition: het_and_homalt\nrequire_consent: true\n"
        f"sdc_min_cell: 10\nsdc_round_to: 5\ndata_dir: {data}\nresults_dir: {results}\n"
    )
    cli.main(["audit", "verify", "--config", str(cfg_path)])  # intact: passes
    out = capsys.readouterr().out
    assert "release_generation=OK" in out

    target = results / "airlock_pending" / "release.json"
    mutated = target.read_bytes().replace(b'"status":"released"', b'"status":"RELEASED"')
    assert mutated != target.read_bytes()
    target.write_bytes(mutated)
    with pytest.raises(SystemExit, match="FAILED"):
        cli.main(["audit", "verify", "--config", str(cfg_path)])
    out = capsys.readouterr().out
    assert "release_generation=FAIL" in out
