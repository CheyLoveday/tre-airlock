"""Unit tests for the Merkle evidence ledger (audit.py) — determinism + tamper detection."""
import pytest

from ofh_feasibility import audit

pytestmark = pytest.mark.unit


def _events(n):
    return [{"cpra": "10:1:C:G", "i": i, "output_sha256": {"x": f"{i:064x}"}} for i in range(n)]


def test_canonical_json_is_order_independent():
    assert audit.canonical_json({"b": 1, "a": 2}) == audit.canonical_json({"a": 2, "b": 1})


def test_root_is_deterministic():
    events = _events(5)
    assert audit.root_of_events(events) == audit.root_of_events(events)
    assert len(audit.root_of_events(events)) == 64  # sha256 hex


@pytest.mark.parametrize("n", [0, 1, 2, 3, 4, 7, 8])
def test_root_defined_for_any_count(n):
    assert isinstance(audit.root_of_events(_events(n)), str)


def test_verify_passes_for_intact_ledger():
    events = _events(6)
    assert audit.verify_ledger(events, audit.root_of_events(events))


def test_tamper_is_detected():
    events = _events(6)
    root = audit.root_of_events(events)
    events[2] = {**events[2], "output_sha256": {"x": "deadbeef"}}  # modify one event
    assert not audit.verify_ledger(events, root)


def test_reorder_is_detected():
    events = _events(6)
    root = audit.root_of_events(events)
    assert not audit.verify_ledger(list(reversed(events)), root)


def test_truncation_is_detected():
    events = _events(6)
    root = audit.root_of_events(events)
    assert not audit.verify_ledger(events[:-1], root)  # a missing (dropped) event


def test_consistency_append_only_proof():
    old = _events(4)
    assert audit.consistency_ok(old, old + _events(2))      # extended -> ok
    assert not audit.consistency_ok(old, _events(4)[::-1])  # not a prefix -> fail
    assert not audit.consistency_ok(old, old[:2])           # shorter -> fail


def test_build_run_event_has_no_participant_fields():
    event = audit.build_run_event(
        request_id="S", cpra="10:1:C:G", timestamp="t", git_commit="abc",
        config_sha256="c", input_sha256={"i": "h"}, output_sha256={"o": "h"},
        sdc={"client_total": "<10"}, parent_root="r",
    )
    assert "participant_id" not in audit.canonical_json(event)
    assert not audit.has_forbidden_pii(event)  # the real run event is clean
    assert set(event) == {
        "request_id", "cpra", "actor_type", "timestamp", "git_commit", "config_sha256",
        "input_sha256", "output_sha256", "sdc", "parent_root",
    }
    assert event["actor_type"] == "cli"


def test_has_forbidden_pii_catches_pseudo_id_not_just_participant_id():
    # F7: the leak check must catch pseudo_id (quasi-identifying), not only participant_id.
    assert audit.has_forbidden_pii({"meta": {"pseudo_id": "PSU-000003"}})
    assert audit.has_forbidden_pii({"meta": {"Pseudo_ID": "PSU-000003"}})
    assert audit.has_forbidden_pii({"participant_id": "OFH100003"})
    assert audit.has_forbidden_pii({"Participant_ID": "OFH100003"})
    assert audit.has_forbidden_pii({"nhs_number": "123"})
    assert audit.has_forbidden_pii({"meta": "contact psu-000003"})
    assert audit.has_forbidden_pii({"meta": "review ofh100003"})
    assert not audit.has_forbidden_pii({"request_id": "S", "cpra": "10:1:C:G", "sdc": {}})


def test_has_forbidden_pii_does_not_flag_handoff_filename():
    # the audit hashes the file "handoff_to_epi.csv" keyed by filename — that is NOT a PII leak;
    # the forbidden-key check must not false-positive on a legitimate output filename.
    event = {"output_sha256": {"handoff_to_epi.csv": "deadbeef", "feasibility_summary.txt": "abc"}}
    assert not audit.has_forbidden_pii(event)


def test_has_forbidden_pii_does_not_scan_hash_values_for_id_shapes():
    event = {
        "config_sha256": "1234567890abcdef",
        "output_sha256": {"feasibility_summary.txt": "0000000000abcdef"},
        "sdc": {"client_total": "<10"},
    }
    assert not audit.has_forbidden_pii(event)
