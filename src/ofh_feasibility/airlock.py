"""airlock — pure builders for the transfer manifest, release candidate, and Lean airlock request.

The airlock governs EVERY transfer (code and data). The manifest classifies each artefact, records
the four airlock criteria, and proposes exactly one file for export — enforced in code: exactly one
file may be export_to_client, and it must be human-readable + classified AIRLOCK-EXPORT-CANDIDATE.

RELEASE AUTHORITY (TRE-airlock MVP): the final pre-egress decision is made by the executable Lean
airlock (`formal/TreAirlock`), invoked via `bridge.authorize`. Every release is a
`ReleaseCandidate` (aggregate-only) mapped by `build_airlock_request` into the strict
`tre-airlock/v1` request; only the exact Lean-emitted bytes may be written as the canonical
release payload. The Python predicates here (`release_ok` / `authorize_release`) mirror the Lean
`ReleaseOK` judgment as a reference/preflight implementation and differential-conformance target —
their verdict is not release authority. Pure; no IO.
"""

from __future__ import annotations

import re
from pathlib import PurePosixPath
from typing import TYPE_CHECKING

from .models import ReleaseCandidate

if TYPE_CHECKING:
    from .config import Config
    from .models import BatchRequest, FeasibilityResult, FinalResult, VariantRequest


def default_airlock_files() -> list[dict]:
    """The canonical output artefacts and their transfer classification (least privilege).

    The sole export is `release.json` — the canonical aggregate payload rendered by the runtime
    Lean airlock from a proof-indexed `AirlockExport`. Python-rendered artefacts (including the
    analyst summary) are INTERNAL: client-facing bytes come only from the formal adjudicator.
    """
    return [
        {
            "file": "internal_carrier_table.parquet",
            "classification": "INTERNAL-TRE-ONLY",
            "export_to_client": False,
            "human_readable": False,  # Parquet (binary) internal staging; never leaves the TRE
            "reason": "participant IDs + full QC/decision provenance; OFH recontact ops only",
        },
        {
            "file": "handoff_to_epi.csv",
            "classification": "INTERNAL-TRE-ONLY",
            "export_to_client": False,
            "human_readable": True,
            "reason": "pseudonymised participant-level; internal handoff for ICD-10 eligibility",
        },
        {
            "file": "frequency_control_view.json",
            "classification": "INTERNAL-TRE-ONLY",
            "export_to_client": False,
            "human_readable": True,
            "reason": "internal QC/credibility control (per-stratum AF + intervals); not exported",
        },
        {
            "file": "feasibility_summary.txt",
            "classification": "INTERNAL-TRE-ONLY",
            "export_to_client": False,
            "human_readable": True,
            "reason": "analyst-facing aggregate note; superseded as export by release.json",
        },
        {
            "file": "release.json",
            "classification": "AIRLOCK-EXPORT-CANDIDATE",
            "export_to_client": True,
            "human_readable": True,
            "reason": "canonical aggregate payload; exact bytes rendered by the Lean airlock",
        },
    ]


def final_airlock_files() -> list[dict]:
    """Airlock file set for the Wave 8 final (post-phenotype) export: the final summary is the sole
    export candidate; the preliminary genotype-ceiling summary is retained INTERNAL-only."""
    return [
        {
            "file": "feasibility_summary.txt",
            "classification": "INTERNAL-TRE-ONLY",
            "export_to_client": False,
            "human_readable": True,
            "reason": "preliminary genotype-ceiling summary; superseded by the final note",
        },
        {
            "file": "final_feasibility_summary.txt",
            "classification": "INTERNAL-TRE-ONLY",
            "export_to_client": False,
            "human_readable": True,
            "reason": "final post-phenotype analyst note; superseded as export by release.json",
        },
        {
            "file": "release.json",
            "classification": "AIRLOCK-EXPORT-CANDIDATE",
            "export_to_client": True,
            "human_readable": True,
            "reason": "canonical final aggregate payload; exact bytes rendered by the Lean airlock",
        },
    ]


def batch_airlock_files() -> list[dict]:
    """Airlock file set for a batch request: the aggregate batch summary is the only export."""
    return [
        {
            "file": "batch_release_candidate.json",
            "classification": "INTERNAL-TRE-ONLY",
            "export_to_client": False,
            "human_readable": True,
            "reason": "aggregate release-gate object; internal evidence for output review",
        },
        {
            "file": "batch_feasibility_summary.txt",
            "classification": "INTERNAL-TRE-ONLY",
            "export_to_client": False,
            "human_readable": True,
            "reason": "analyst-facing batch note; superseded as export by release.json",
        },
        {
            "file": "release.json",
            "classification": "AIRLOCK-EXPORT-CANDIDATE",
            "export_to_client": True,
            "human_readable": True,
            "reason": "canonical batch aggregate payload; exact bytes rendered by the Lean airlock",
        },
    ]


def build_airlock_manifest(request: VariantRequest, files: list[dict], cfg: Config) -> dict:
    """Assemble the airlock manifest; fail fast if the export/classification invariant is broken."""
    return _build_airlock_manifest(request.study_id, request.cpra, files, cfg)


def build_batch_airlock_manifest(batch: BatchRequest, files: list[dict], cfg: Config) -> dict:
    """Assemble the airlock manifest for a multi-variant batch request."""
    cpra = "+".join(v.cpra for v in batch.variants)
    return _build_airlock_manifest(batch.study_id, cpra, files, cfg)


_FILE_DESCRIPTOR_KEYS = {"file", "classification", "export_to_client", "human_readable", "reason"}


def _safe_manifest_file_name(value: object) -> bool:
    text = str(value).strip()
    if not text:
        return False
    path = PurePosixPath(text)
    return not path.is_absolute() and ".." not in path.parts and str(path) == path.name


def _files_described_and_inspectable(files: list[dict]) -> bool:
    return all(
        _FILE_DESCRIPTOR_KEYS.issubset(item)
        and _safe_manifest_file_name(item["file"])
        and bool(str(item["classification"]).strip())
        and isinstance(item["export_to_client"], bool)
        and isinstance(item["human_readable"], bool)
        and bool(str(item["reason"]).strip())
        for item in files
    )


def _technically_feasible(files: list[dict]) -> bool:
    return _files_described_and_inspectable(files) and all(
        (not item["export_to_client"]) or item["human_readable"] for item in files
    )


def _airlock_four_criteria(files: list[dict]) -> dict:
    return {
        "aligned_with_approved_aims": (
            "human airlock reviewer must attest against the approved study aims"
        ),
        "files_described_and_inspectable": _files_described_and_inspectable(files),
        "no_reidentification_or_confidentiality_risk": (
            "aggregate + SDC for the export file; participant-level kept internal"
        ),
        "technically_feasible": _technically_feasible(files),
    }


def _build_airlock_manifest(study_id: str, cpra: str, files: list[dict], cfg: Config) -> dict:
    exports = [f for f in files if f.get("export_to_client")]
    if len(exports) != 1:
        raise ValueError(f"airlock: exactly one file may be export_to_client, got {len(exports)}")
    if not exports[0].get("human_readable"):
        raise ValueError("airlock: the exported file must be human-readable")
    # tie export status to the file's own classification, not just the caller's flag: with exactly
    # one export, requiring it be AIRLOCK-EXPORT-CANDIDATE also guarantees no INTERNAL file leaks.
    if exports[0].get("classification") != "AIRLOCK-EXPORT-CANDIDATE":
        raise ValueError("airlock: the exported file must be classified AIRLOCK-EXPORT-CANDIDATE")
    export_name = exports[0]["file"]
    return {
        "study_id": study_id,
        "cpra": cpra,
        "five_safes": (
            "Safe Outputs — all transfers reviewed against approved aims; the export is "
            "aggregate, SDC-applied, and human-readable"
        ),
        "files": files,
        "airlock_four_criteria": _airlock_four_criteria(files),
        "code_also_through_airlock": True,
        "sdc": {"min_cell": cfg.sdc_min_cell, "round_to": cfg.sdc_round_to},
        "note": (
            f"Only {export_name} is proposed for export; participant and pseudonymised "
            "tables remain in the TRE."
        ),
    }


# --- release gate (Wave 5): the export is unconstructable without a passing decision ----------

# Aggregate-only field set a release object may carry (no participant-level columns).
_RELEASE_FIELDS = {
    "study_id", "cpra", "client_total", "breakdown_suppressed", "reported_cells",
    "min_cell", "round_to",
}


def build_release_candidate(result: FeasibilityResult, sdc: dict, cfg: Config) -> ReleaseCandidate:
    """Construct the serializable release object from the result + SDC output (aggregate only)."""
    return ReleaseCandidate(
        study_id=result.study_id,
        cpra=result.cpra,
        client_total=result.client_total,
        breakdown_suppressed=result.breakdown_suppressed,
        reported_cells=tuple(sdc.get("reported_cells", {}).items()),
        min_cell=cfg.sdc_min_cell,
        round_to=cfg.sdc_round_to,
    )


def _total_is_release_safe(token: str, min_cell: int, round_to: int) -> bool:
    if token.startswith("<"):  # the suppression token must be EXACTLY "<{min_cell}"
        return token == f"<{min_cell}"
    if token.startswith("~"):  # an approximate count: a multiple of round_to AND >= min_cell
        try:
            n = int(token[1:])
        except ValueError:
            return False
        return n % round_to == 0 and n >= min_cell
    return False


def release_reasons(candidate: ReleaseCandidate) -> list[str]:
    """The release requirements that a candidate FAILS (empty list == releasable).

    Reference/preflight predicate: mirrors the Lean `ReleaseOK` judgment (formal/TreAirlock) so the
    two implementations can be differentially tested. The RUNTIME authority is the Lean airlock
    (bridge.authorize); this predicate provides diagnostics and conformance evidence only.
    """
    fails = []
    labels = [name for name, _ in candidate.reported_cells]
    cells = dict(candidate.reported_cells)
    # least privilege: the release object carries no participant-level field (structural + checked).
    if set(candidate.model_dump()) - _RELEASE_FIELDS:
        fails.append("release object carries a non-aggregate field")
    # structural closure (mirrors Lean, where these are unrepresentable/refused at parse):
    if len(set(labels)) != len(labels):
        fails.append("duplicate released subgroup cell labels")
    if any(n < 0 for _, n in candidate.reported_cells):
        fails.append("a released subgroup cell count is negative")
    # minimum cell size: no released subgroup cell below the minimum.
    if any(0 < n < candidate.min_cell for n in cells.values()):
        fails.append("a released subgroup cell is below the minimum cell size")
    # secondary suppression: a suppressed breakdown must release no subgroup cells (no diff attack).
    if candidate.breakdown_suppressed and cells:
        fails.append("breakdown suppressed but subgroup cells released (back-calculation risk)")
    # rounding: every released number is a multiple of the rounding base (or the suppression token).
    if any(n % candidate.round_to != 0 for n in cells.values()):
        fails.append("a released cell is not a multiple of the rounding base")
    if not _total_is_release_safe(
        candidate.client_total, candidate.min_cell, candidate.round_to
    ):
        fails.append("the released total is neither the suppression token nor a rounded value")
    return fails


# --- runtime Lean airlock request (TRE-airlock MVP): the candidate crossing the boundary --------

# The closed release value language, mirrored from formal/TreAirlock/Candidate.lean. The Lean
# parser is the authority (out-of-vocabulary values refuse there too); this mirror fails fast so
# a malformed candidate never becomes an authority-bearing request.
APPROVED_CELL_LABELS = ("array_direct_high_confidence", "imputed_supported_conditional")
_MAX_COUNT = 1_000_000_000
_MAX_CELLS = 16
_MAX_SUBJECT_VARIANTS = 16
_CHROMS = frozenset([str(n) for n in range(1, 23)] + ["X", "Y", "MT"])
_STUDY_ID_RE = re.compile(r"^[A-Za-z0-9._-]{1,64}\Z")  # \Z: no trailing-newline latitude
_ALLELE_RE = re.compile(r"^[ACGT]{1,64}\Z")
_TOTAL_COUNT_RE = re.compile(r"^[0-9]{1,10}\Z")  # canonical ASCII digits, bounded
_MAX_POS = 1_000_000_000_000


def _require_valid_subject(subject: str) -> None:
    parts = subject.split("+")
    if not 1 <= len(parts) <= _MAX_SUBJECT_VARIANTS:
        raise ValueError(f"airlock request: subject must be 1-{_MAX_SUBJECT_VARIANTS} CPRAs")
    for part in parts:
        fields = part.split(":")
        ok = (
            len(fields) == 4
            and fields[0] in _CHROMS
            and _TOTAL_COUNT_RE.match(fields[1]) is not None
            and str(int(fields[1])) == fields[1]
            and 0 < int(fields[1]) <= _MAX_POS
            and _ALLELE_RE.match(fields[2]) is not None
            and _ALLELE_RE.match(fields[3]) is not None
        )
        if not ok:
            raise ValueError(f"airlock request: invalid CPRA subject component {part!r}")


def build_airlock_request(candidate: ReleaseCandidate, policy) -> dict:
    """Map the aggregate release candidate to the strict `tre-airlock/v1` request (pure).

    `policy` is the PLATFORM-authorised `TrustedReleasePolicy` (bridge.load_trusted_policy) —
    never the analysis config and never the candidate: the analysis must not choose the policy
    under which its own output is judged. The candidate's declared min_cell/round_to are audit
    fields only, and a disagreement with the authorised policy refuses before adjudication.
    Display tokens map back to the structural form Lean judges — `~N` -> shown, the exact
    `<{min_cell}` token -> suppressed. Anything outside the closed value language (unapproved
    labels, malformed identifiers, over-cap values) fails fast here AND in the Lean parser.
    """
    if (candidate.min_cell, candidate.round_to) != (policy.min_cell, policy.round_to):
        raise ValueError(
            "airlock request: candidate declares policy "
            f"({candidate.min_cell}, {candidate.round_to}) but the platform-authorised policy "
            f"is ({policy.min_cell}, {policy.round_to}) — refusing before adjudication"
        )
    if not _STUDY_ID_RE.match(candidate.study_id):
        raise ValueError(f"airlock request: invalid study_id {candidate.study_id!r}")
    _require_valid_subject(candidate.cpra)
    token = candidate.client_total
    if token == f"<{policy.min_cell}":
        total: dict = {"tag": "suppressed"}
    elif (
        token.startswith("~")
        and _TOTAL_COUNT_RE.match(token[1:]) is not None
        and str(int(token[1:])) == token[1:]  # canonical: no leading zeros, ASCII digits only
        and int(token[1:]) <= _MAX_COUNT
    ):
        total = {"tag": "shown", "n": int(token[1:])}
    else:
        raise ValueError(f"airlock request: unmappable client_total token {token!r}")
    labels = [name for name, _ in candidate.reported_cells]
    if len(labels) > _MAX_CELLS:
        raise ValueError(f"airlock request: more than {_MAX_CELLS} subgroup cells")
    if any(name not in APPROVED_CELL_LABELS for name in labels):
        raise ValueError("airlock request: subgroup cell label outside the approved vocabulary")
    if len(set(labels)) != len(labels):
        raise ValueError("airlock request: duplicate subgroup cell labels")
    if any(
        (not isinstance(n, int)) or n < 0 or n > _MAX_COUNT
        for _, n in candidate.reported_cells
    ):
        raise ValueError("airlock request: subgroup cell counts must be bounded non-negative ints")
    if candidate.breakdown_suppressed and candidate.reported_cells:
        # NEVER silently drop cells (plan §8: no permissive filterMap at the boundary) — a
        # suppressed breakdown carrying cells is a contradictory state and cannot be serialised.
        raise ValueError("airlock request: suppressed breakdown must carry no subgroup cells")
    if candidate.breakdown_suppressed:
        breakdown: dict = {"tag": "suppressed"}
    else:
        breakdown = {
            "tag": "shown",
            "cells": [{"label": name, "count": n} for name, n in candidate.reported_cells],
        }
    return {
        "schema": "tre-airlock/v1",
        "policy": {"min_cell": policy.min_cell, "round_to": policy.round_to},
        "candidate": {
            "study_id": candidate.study_id,
            "subject_id": candidate.cpra,  # TRE-neutral subject key; the example carries CPRAs
            "total": total,
            "breakdown": breakdown,
        },
    }


def build_final_release_candidate(final_result: FinalResult, cfg: Config) -> ReleaseCandidate:
    """Aggregate-only release object for the Wave 8 post-phenotype eligible count.

    Maps the POST-PHENOTYPE figure (not the genotype ceiling) to the release candidate, so the
    SAME runtime Lean gate adjudicates the final released figure. The eligible count
    is a single aggregate — no subgroup breakdown — so reported_cells is empty.
    """
    return ReleaseCandidate(
        study_id=final_result.study_id,
        cpra=final_result.cpra,
        client_total=final_result.client_eligible,
        breakdown_suppressed=True,  # single aggregate, no subgroup cells: structurally suppressed
        reported_cells=(),
        min_cell=cfg.sdc_min_cell,
        round_to=cfg.sdc_round_to,
    )


def _released_int(token: str) -> int | None:
    """A released SDC token '~N' -> N; a suppression token '<min' -> None (no cell released)."""
    return int(token[1:]) if token.startswith("~") else None


def build_batch_release_candidate(
    batch: BatchRequest, combined: dict, cfg: Config
) -> ReleaseCandidate:
    """Aggregate-only release object for a multi-variant batch summary (F1).

    The batch release carries only the union total by default. Per-variant and overlap
    cells can create a differencing attack (`A + B - union = overlap`), so those details are kept
    internal unless a future proof/tested breakdown rule makes them safe.
    """
    return ReleaseCandidate(
        study_id=batch.study_id,
        cpra="+".join(combined["per_variant"].keys()),
        client_total=combined["combined_client_total"],
        breakdown_suppressed=combined.get("breakdown_suppressed", True),
        reported_cells=(),
        min_cell=cfg.sdc_min_cell,
        round_to=cfg.sdc_round_to,
    )


def release_ok(candidate: ReleaseCandidate) -> bool:
    """True iff every disclosure-control release requirement holds for the candidate."""
    return not release_reasons(candidate)


def authorize_release(candidate: ReleaseCandidate) -> ReleaseCandidate:
    """Reference/preflight gate (NOT the release authority): passes the candidate or fails closed.

    In the completed TRE-airlock MVP the runtime authority is the Lean adjudicator invoked via
    `bridge.authorize`; the canonical release payload is only ever the Lean-emitted bytes. This
    function remains for preflight diagnostics, unit/property tests, and differential conformance.
    """
    reasons = release_reasons(candidate)
    if reasons:
        raise ValueError("airlock: release refused — " + "; ".join(reasons))
    return candidate
