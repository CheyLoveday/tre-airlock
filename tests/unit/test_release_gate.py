"""Unit tests for the Wave 5 release gate: release_ok predicates + conformance battery."""
import pytest
from pydantic import ValidationError

from ofh_feasibility import airlock
from ofh_feasibility.config import Config
from ofh_feasibility.models import FeasibilityResult, ReleaseCandidate

pytestmark = pytest.mark.unit


def _cfg():
    return Config.from_dict(dict(
        array_call_rate_min=0.98, array_gq_min=20, imputed_info_min=0.30,
        imputed_info_high_confidence=0.80, imputed_dosage_carrier_threshold=0.5,
        imputed_max_gp_min=0.90, carrier_definition="het_and_homalt", require_consent=True,
        sdc_min_cell=10, sdc_round_to=5, data_dir="d", results_dir="r",
    ))


def _candidate(**over):
    base = dict(
        study_id="S", cpra="10:1:C:G", client_total="~20", breakdown_suppressed=True,
        reported_cells=(), min_cell=10, round_to=5,
    )
    return ReleaseCandidate(**{**base, **over})


# (description, overrides, expected_releasable) — the conformance battery (edge cases).
_BATTERY = [
    ("suppressed total, no breakdown", dict(client_total="<10", reported_cells=()), True),
    ("rounded total, no breakdown", dict(client_total="~20", reported_cells=()), True),
    ("full breakdown, all >= min",
     dict(client_total="~40", breakdown_suppressed=False,
          reported_cells=(("a", 25), ("b", 15))), True),
    ("sub-min subgroup cell released",
     dict(client_total="~40", breakdown_suppressed=False,
          reported_cells=(("a", 25), ("b", 5))), False),
    ("breakdown shown while flagged suppressed",
     dict(client_total="~40", breakdown_suppressed=True, reported_cells=(("a", 25),)), False),
    ("unrounded subgroup cell",
     dict(client_total="~40", breakdown_suppressed=False, reported_cells=(("a", 23),)), False),
    ("unrounded total", dict(client_total="~23", reported_cells=()), False),
    ("malformed total token", dict(client_total="20", reported_cells=()), False),
    # F6: a bare "<" prefix is not enough — the suppression token must be EXACTLY "<{min_cell}".
    ("non-numeric suppression token", dict(client_total="<banana", reported_cells=()), False),
    ("wrong-min suppression token", dict(client_total="<5", reported_cells=()), False),
    ("suppression token with suffix", dict(client_total="<10x", reported_cells=()), False),
    ("rounded total below min_cell", dict(client_total="~5", reported_cells=()), False),
]


@pytest.mark.parametrize("desc,over,expected", _BATTERY, ids=[b[0] for b in _BATTERY])
def test_release_gate_conformance_battery(desc, over, expected):
    assert airlock.release_ok(_candidate(**over)) is expected


def test_authorize_release_returns_on_pass_and_fails_closed():
    ok = _candidate(client_total="<10")
    assert airlock.authorize_release(ok) is ok
    with pytest.raises(ValueError, match="release refused"):
        airlock.authorize_release(_candidate(
            client_total="~40", breakdown_suppressed=False, reported_cells=(("a", 5),)
        ))


def test_release_candidate_forbids_participant_fields():
    # the release object is aggregate-only by construction (extra="forbid")
    with pytest.raises(ValidationError):
        ReleaseCandidate(
            study_id="S", cpra="c", client_total="<10", breakdown_suppressed=True,
            min_cell=10, round_to=5, participant_id="OFH100001",
        )


def test_build_release_candidate_from_result():
    result = FeasibilityResult(
        study_id="S", cpra="10:1:C:G", total_included=40, high_confidence=25, conditional=15,
        excluded=2, flagged=0, client_total="~40", breakdown_suppressed=False,
        assumptions=(), limitations=(),
    )
    sdc = {"reported_cells": {"array_direct_high_confidence": 25, "imputed_supported": 15}}
    candidate = airlock.build_release_candidate(result, sdc, _cfg())
    assert candidate.client_total == "~40" and airlock.release_ok(candidate)
