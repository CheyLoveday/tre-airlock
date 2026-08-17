"""audit — tamper-evident Merkle evidence ledger (pure core; stdlib only).

Every pipeline run emits a canonical, hashed event; events batch into a Merkle root. A verifier
recomputes the leaves + root and proves the log was not modified, reordered, or truncated. The
ledger logs only hashes + metadata — NEVER participant-level data.

Allowlist-clean: `hashlib` + `json` only, no new runtime dependency. Framing maps to EU AI Act
Art. 12 (automatic record-keeping for traceability); it is not claimed to satisfy a tamper-evidence
mandate, and it does not replace disclosure review or the human-readable airlock checks.
"""

from __future__ import annotations

import hashlib
import json
import re

# Domain-separation prefixes for second-preimage resistance (a leaf can't be read as a node).
_LEAF = b"\x00"
_NODE = b"\x01"


def canonical_json(event: dict) -> str:
    """Deterministic JSON: sorted keys, compact separators — stable across runs and machines."""
    return json.dumps(event, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


# Identifiers that must never appear in an audit event (it records hashes + SDC metadata only).
# pseudo_id is quasi-identifying in the TRE, so it is forbidden alongside the direct identifiers.
# NB: these are identifier tokens, NOT filenames — a stage event legitimately records the hash of
# "handoff_to_epi.csv" keyed by filename, which is not a leak, so the filename is not forbidden.
FORBIDDEN_PII_KEYS = (
    "participant_id", "pseudo_id", "nhs_number", "date_of_birth",
)
_FORBIDDEN_PII_KEY_TOKENS = tuple(key.casefold() for key in FORBIDDEN_PII_KEYS)
_FORBIDDEN_PII_VALUE_PATTERNS = (
    re.compile(r"\bPSU-[0-9A-F]{6,}\b", re.IGNORECASE),
    re.compile(r"\bOFH\d{4,}\b", re.IGNORECASE),
    re.compile(r"\b\d{3}\s?\d{3}\s?\d{4}\b"),  # NHS-number shaped token
)
_HASH_METADATA_KEYS = {
    "config_sha256", "input_sha256", "output_sha256", "git_commit", "parent_root",
}


def _free_text_values(event) -> list[str]:
    """String values worth scanning for identifier-shaped tokens.

    Hash/provenance fields are deliberately skipped: they can contain arbitrary hexadecimal or
    numeric runs that look like identifiers but are not human-authored output text.
    """
    values: list[str] = []

    def walk(value, *, parent_key: str | None = None) -> None:
        if parent_key in _HASH_METADATA_KEYS:
            return
        if isinstance(value, dict):
            for key, nested in value.items():
                walk(nested, parent_key=str(key))
        elif isinstance(value, (list, tuple, set)):
            for nested in value:
                walk(nested, parent_key=parent_key)
        elif isinstance(value, str):
            values.append(value)

    walk(event)
    return values


def _has_forbidden_key(event) -> bool:
    def walk(value) -> bool:
        if isinstance(value, dict):
            for key, nested in value.items():
                key_text = str(key).casefold()
                if any(token in key_text for token in _FORBIDDEN_PII_KEY_TOKENS):
                    return True
                if walk(nested):
                    return True
        elif isinstance(value, (list, tuple, set)):
            return any(walk(nested) for nested in value)
        return False

    return walk(event)


def has_forbidden_pii(event) -> bool:
    """Defensive leak check (F7): True if an event mentions forbidden keys or ID-shaped values.

    Centralises what the audit verifier rejects so a future change that records pseudo_id (not just
    participant_id) cannot pass verification silently. Free-text values are scanned too, because
    aggregate contracts can otherwise leak a bare pseudo ID without naming the field.
    """
    if _has_forbidden_key(event):
        return True
    return any(
        pattern.search(value)
        for value in _free_text_values(event)
        for pattern in _FORBIDDEN_PII_VALUE_PATTERNS
    )


def leaf_hash(event: dict) -> str:
    """SHA-256 of the canonical event, leaf-prefixed."""
    return hashlib.sha256(_LEAF + canonical_json(event).encode()).hexdigest()


def _pair_hash(a: str, b: str) -> str:
    return hashlib.sha256(_NODE + bytes.fromhex(a) + bytes.fromhex(b)).hexdigest()


def merkle_root(leaves: list[str]) -> str:
    """Merkle root over leaf hashes (odd level duplicates its last node). Canonical empty root."""
    if not leaves:
        return hashlib.sha256(_NODE).hexdigest()
    level = list(leaves)
    while len(level) > 1:
        if len(level) % 2:
            level.append(level[-1])
        level = [_pair_hash(level[i], level[i + 1]) for i in range(0, len(level), 2)]
    return level[0]


def root_of_events(events: list[dict]) -> str:
    """The Merkle root over a list of events (leaf-hashed in order)."""
    return merkle_root([leaf_hash(e) for e in events])


def verify_ledger(events: list[dict], expected_root: str) -> bool:
    """Recompute the root from events and check it matches (detects modify / reorder / truncate)."""
    return root_of_events(events) == expected_root


def consistency_ok(old_events: list[dict], new_events: list[dict]) -> bool:
    """Append-only proof: the new log is an exact extension of the old (old is a prefix)."""
    return len(new_events) >= len(old_events) and new_events[: len(old_events)] == old_events


def build_run_event(
    *,
    request_id: str,
    cpra: str,
    timestamp: str,
    git_commit: str,
    config_sha256: str,
    input_sha256: dict,
    output_sha256: dict,
    sdc: dict,
    parent_root: str,
    actor_type: str = "cli",
    airlock: dict | None = None,
) -> dict:
    """A canonical pipeline-run event — hashes + governance metadata ONLY, no participant data.

    `airlock` (when the run crossed the runtime Lean gate) copies the adjudication decision's
    digests — request, payload, and executable SHA-256 — plus the retained-preimage path. The
    digests VERIFY separately retained artefacts; byte-for-byte REPLAY uses the retained request
    preimage under airlock_evidence/, not the digest alone.
    """
    event = {
        "request_id": request_id,
        "cpra": cpra,
        "actor_type": actor_type,
        "timestamp": timestamp,
        "git_commit": git_commit,
        "config_sha256": config_sha256,
        "input_sha256": input_sha256,
        "output_sha256": output_sha256,
        "sdc": sdc,
        "parent_root": parent_root,
    }
    if airlock is not None:
        event["airlock"] = airlock
    return event
