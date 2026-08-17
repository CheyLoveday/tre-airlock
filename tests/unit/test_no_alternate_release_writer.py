"""Static guards: authority substitution and alternate writers are structurally rejected.

Completion-gate items of the airlock design plus the review blockers: the ONLY writer of the
canonical `airlock_pending/release.json` (and its `release.ready` commit receipt) is the bridge's
release transaction; the ONLY adjudicator is the platform-owned trusted executable; and the ONLY
policy Γ is the platform-owned record — none resolvable from the environment, the analysis
config, candidate content, or analyst-reachable parameters. These source scans make a future
edit that re-opens any of those channels fail loudly; runtime evidence lives in
tests/e2e/test_release_payload.py and tests/integration/test_lean_bridge.py.
"""
import re
from pathlib import Path

import pytest

pytestmark = pytest.mark.unit

SRC = Path(__file__).resolve().parents[2] / "src" / "ofh_feasibility"
_SOURCES = {p.name: p.read_text() for p in sorted(SRC.glob("*.py"))}


def test_release_artefact_names_are_defined_once():
    # "release.json" appears as the bridge constant + the manifest descriptors (pure data) only;
    # "release.ready" exists ONLY in the bridge. Other modules use the bridge constants.
    owners = {name for name, text in _SOURCES.items() if '"release.json"' in text}
    assert owners == {"airlock.py", "bridge.py"}, owners
    assert _SOURCES["bridge.py"].count('"release.json"') == 1
    ready_owners = {name for name, text in _SOURCES.items() if '"release.ready"' in text}
    assert ready_owners == {"bridge.py"}, ready_owners


def test_only_the_bridge_publishes_the_canonical_payload():
    # os.replace / atomic promotion exists only inside the bridge's transaction; no other module
    # writes bytes into the pending area, and io has no verbatim-bytes writer at all.
    for name, text in _SOURCES.items():
        if name != "bridge.py":
            assert "os.replace" not in text, f"{name}: atomic promotion outside the bridge"
    assert "write_bytes" not in _SOURCES["io.py"]
    for name, text in _SOURCES.items():
        for kind, args in re.findall(r"io\.write_(text|json|csv|parquet)\(([^)]*)\)", text):
            if "AIRLOCK_PENDING" in args or "pending" in args.split(",")[-1]:
                assert "MANIFEST" in args, (
                    f"{name}: io.write_{kind}({args}) writes non-manifest content into the "
                    "egress-pending area — the payload comes only from the Lean bridge"
                )


def test_adjudicator_cannot_be_substituted_by_environment_or_config():
    # blocker: no production code may derive the adjudicator OR the policy from os.environ,
    # CLI args, or the analysis config. The old env override name must be dead in src/.
    for name, text in _SOURCES.items():
        assert "OFH_AIRLOCK_BIN" not in text, f"{name}: environment adjudicator override"
    assert "os.environ" not in _SOURCES["bridge.py"]
    assert "getenv" not in _SOURCES["bridge.py"]
    for cfg_word in ("airlock_bin", "adjudicator_path", "airlock_exe", "executable",
                     "policy_path", "release_policy"):
        assert cfg_word not in _SOURCES["config.py"], f"config.py exposes {cfg_word}"
        assert cfg_word not in _SOURCES["cli.py"], f"cli.py exposes {cfg_word}"


def test_policy_authority_is_platform_owned_not_config_owned():
    # blocker 1: the bridge never reads the analysis config — Γ comes from the platform record.
    bridge_src = _SOURCES["bridge.py"]
    assert "from .config" not in bridge_src and "import config" not in bridge_src
    assert "sdc_min_cell" not in bridge_src and "sdc_round_to" not in bridge_src
    assert 'platform" / "release_policy.json' in bridge_src.replace("'", '"')
    # the request builder takes the TrustedReleasePolicy, and pipeline passes no cfg policy in.
    assert "build_airlock_request(candidate, policy)" in bridge_src
    assert "build_airlock_request" not in _SOURCES["pipeline.py"]


def test_test_seams_are_private_and_never_assigned_in_production():
    # the ONLY assignments to the seams are their (annotated) None definitions inside bridge.py.
    for seam in ("_TEST_EXECUTABLE_OVERRIDE", "_TEST_POLICY_OVERRIDE"):
        for name, text in _SOURCES.items():
            hits = re.findall(rf"^{seam}(?::[^=]*)?=\s*(.+)$", text, re.M)
            if name == "bridge.py":
                assert hits == ["None"], (seam, hits)
            else:
                assert not hits, f"{name} assigns the private test seam {seam}"
                assert seam not in text, f"{name} touches the test seam {seam}"


def test_bridge_invokes_subprocess_only_with_the_bound_adjudicator():
    # every subprocess.run in the bridge executes argv [str(exe)] — the resolved adjudicator.
    calls = re.findall(r"subprocess\.run\(\s*\[([^\]]+)\]", _SOURCES["bridge.py"])
    assert calls and all(c == "str(exe)" for c in calls), calls
    users = {name for name, text in _SOURCES.items() if "subprocess" in text}
    assert users <= {"bridge.py", "pipeline.py"}, users
    pipeline_calls = re.findall(r"subprocess\.run\(\s*\[([^\]]+)\]", _SOURCES["pipeline.py"])
    assert all("git" in c for c in pipeline_calls), pipeline_calls


def test_every_egress_site_uses_the_single_transaction():
    # blocker 3: all four egress paths run inside bridge.release_transaction — internal writes
    # and the audit event included — and none calls authorize/publish_release directly.
    assert _SOURCES["pipeline.py"].count("bridge.release_transaction(") == 4
    assert "bridge.authorize(" not in _SOURCES["pipeline.py"]
    assert "bridge.publish_release(" not in _SOURCES["pipeline.py"]


def test_audit_record_is_copied_from_the_decision_not_reconstructed():
    # blocker (#56): the audit emitter must not rebuild the request from candidate + cfg — the
    # record IS the commit receipt, copied from the immutable decision.
    body = _SOURCES["pipeline.py"]
    record_fn = body[body.index("def _airlock_audit_record") : body.index("def _git_commit")]
    assert "build_airlock_request" not in record_fn
    assert "encode_request" not in record_fn
    assert "bridge.ready_receipt(decision" in record_fn
    receipt_fn = _SOURCES["bridge.py"]
    for field in ("decision.request_sha256", "decision.payload_sha256",
                  "decision.adjudicator_sha256", "decision.policy_sha256"):
        assert field in receipt_fn, field


def test_cli_release_commands_print_no_python_rendered_client_figures():
    # blocker 4: release commands print the committed receipt only; analyst narration lives in
    # the explicitly-internal `notes` command.
    cli = _SOURCES["cli.py"]
    assert 'print(bundle["summary"])' not in cli
    assert 'print(bundle["final_summary"])' not in cli
    assert "client figure" not in cli
    assert "--report" not in cli
    assert "_print_release_receipt" in cli
    assert "INTERNAL-TRE-ONLY" in cli  # the notes command banner
