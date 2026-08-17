"""ofh_feasibility CLI — one command to run a governed feasibility request.

Allowlist-clean: argparse (stdlib) only, no new dependency. Wraps the same pipeline as run_demo.

    ofh-feasibility run    [--request <path>] [--config config.yaml]
    ofh-feasibility batch   --request <batch.csv> [--config config.yaml]
    ofh-feasibility notes  [--config config.yaml]   # INTERNAL analyst diagnostics
    ofh-feasibility audit  verify [--config config.yaml]

Release commands print the COMMITTED RELEASE RECEIPT only (canonical path + digests + policy +
adjudicator identity). Python-rendered summaries are INTERNAL-TRE-ONLY analyst notes: they are
written into the results directory and shown only by the explicitly-internal `notes` command —
no Python-rendered figure is presented as client-facing output (second-review blocker 4).
"""

from __future__ import annotations

import argparse
import json
import logging
import re
from pathlib import Path

from . import audit, bridge, io, pipeline, resolve
from .config import load_config
from .models import DiseaseRequest, GeneRequest

# A small catalogue of standard request types: a new type is added by dropping a template here.
TEMPLATES = {
    "single_variant": "single_variant.json",
    "composite_profile": "composite_profile.csv",
}
_TEMPLATE_DIR = Path(__file__).resolve().parent.parent.parent / "templates"


def _id_token(value: str) -> str:
    token = re.sub(r"[^A-Za-z0-9]+", "-", value.strip()).strip("-").upper()
    return token or "REQUEST"


def _panel_label(value: str) -> str:
    return value.strip().lower().replace("_", " ")


def _gene_request(args) -> GeneRequest:
    symbol = args.symbol.strip().upper()
    return GeneRequest(
        study_id=args.study_id or f"OFH-CRRS-DEMO-{_id_token(symbol)}-GENE",
        symbol=symbol,
        requested_source=args.requested_source,
        purpose=args.purpose or f"Recontact feasibility: {symbol} carriers",
    )


def _disease_request(args) -> DiseaseRequest:
    panel = args.panel.strip().lower()
    label = _panel_label(panel)
    return DiseaseRequest(
        study_id=args.study_id or f"OFH-CRRS-DEMO-{_id_token(panel)}-PANEL",
        panel=panel,
        requested_source=args.requested_source,
        purpose=args.purpose or f"Recontact feasibility: {label} panel carriers",
    )


def _resolve_request(arg_request: str | None, template: str | None, default: Path) -> Path:
    if template is not None:
        if template not in TEMPLATES:
            raise SystemExit(f"unknown template {template!r}; choose from {sorted(TEMPLATES)}")
        return _TEMPLATE_DIR / TEMPLATES[template]
    return Path(arg_request) if arg_request else default


def _apply_config_overrides(cfg, args):
    updates = {}
    if getattr(args, "source_format", None):
        updates["source_format"] = args.source_format
    if getattr(args, "data_dir", None):
        updates["data_dir"] = args.data_dir
    if getattr(args, "results_dir", None):
        updates["results_dir"] = args.results_dir
    if getattr(args, "request_path", None):
        updates["request_path"] = args.request_path
    if getattr(args, "variant_catalog_path", None):
        updates["variant_catalog_path"] = args.variant_catalog_path
    return cfg.model_copy(update=updates) if updates else cfg


def _add_config_flags(sp: argparse.ArgumentParser, *, source_format: bool = False) -> None:
    sp.add_argument("--config", default="config.yaml", help="path to config.yaml")
    sp.add_argument("--data-dir", default=None, help="override config data_dir")
    sp.add_argument("--results-dir", default=None, help="override config results_dir")
    sp.add_argument(
        "--variant-catalog",
        dest="variant_catalog_path",
        default=None,
        help="override config variant_catalog_path for gene/disease requests",
    )
    if source_format:
        sp.add_argument(
            "--source-format",
            default=None,
            choices=["simplified", "ofh_tre"],
            help="input format: simplified stand-ins or OFH-format pVCF/tabix stand-ins",
        )


def _configured_request_default(cfg, filename: str) -> Path:
    if cfg.request_path:
        return Path(cfg.request_path)
    return Path(cfg.data_dir) / filename




def _print_release_receipt(cfg) -> None:
    """Print the committed generation's receipt — the ONLY release-shaped CLI output.

    Read back from the release.ready commit marker (ground truth on disk), not from in-memory
    state: what is printed is exactly what a transfer consumer would verify.
    """
    results = Path(cfg.results_dir)
    pending = results / pipeline.AIRLOCK_PENDING
    receipt = json.loads((pending / bridge.RELEASE_READY).read_text())
    print("release: committed")
    print(f"  canonical: {pending / bridge.RELEASE_PAYLOAD}")
    print(f"  payload_sha256: {receipt['payload']['sha256']}")
    print(f"  request_sha256: {receipt['request']['sha256']}")
    print(f"  policy: {receipt['policy']['id']} v{receipt['policy']['version']}")
    print(f"  adjudicator_sha256: {receipt['adjudicator']['sha256']}")
    print(f"  internal artefacts: {results}/ (view with: ofh-feasibility notes)")

def _run(args) -> None:
    cfg = _apply_config_overrides(load_config(args.config), args)
    request_path = _resolve_request(
        args.request, args.template, _configured_request_default(cfg, "variant_request.csv")
    )
    cfg = cfg.model_copy(update={"request_path": str(request_path)})
    request = io.read_request(request_path)
    pipeline.orchestrate(cfg, request, audience=args.audience)
    _print_release_receipt(cfg)


def _batch(args) -> None:
    cfg = _apply_config_overrides(load_config(args.config), args)
    request_path = _resolve_request(
        args.request, args.template, _configured_request_default(cfg, "batch_request.csv")
    )
    pipeline.orchestrate_batch(cfg, io.read_batch_request(request_path), audience=args.audience)
    _print_release_receipt(cfg)


def _gene(args) -> None:
    cfg = _apply_config_overrides(load_config(args.config), args)
    request = _gene_request(args)
    pipeline.orchestrate_batch(
        cfg, resolve.resolve_gene(request, cfg.variant_catalog_path), audience=args.audience
    )
    _print_release_receipt(cfg)


def _disease(args) -> None:
    cfg = _apply_config_overrides(load_config(args.config), args)
    request = _disease_request(args)
    pipeline.orchestrate_batch(
        cfg, resolve.resolve_disease(request, cfg.variant_catalog_path), audience=args.audience
    )
    _print_release_receipt(cfg)


def _finalize_eligible(args) -> None:
    cfg = _apply_config_overrides(load_config(args.config), args)
    request_path = _resolve_request(
        args.request, None, _configured_request_default(cfg, "variant_request.csv")
    )
    cfg = cfg.model_copy(update={"request_path": str(request_path)})
    request = io.read_request(request_path)
    epi_return = io.read_epi_return(args.epi_return)
    checkpoints = io.read_checkpoints(args.checkpoints) if args.checkpoints else []
    pipeline.orchestrate_finalize(cfg, request, epi_return, checkpoints)
    _print_release_receipt(cfg)




def _notes(args) -> None:
    """Explicitly INTERNAL diagnostics: print the analyst notes from a results directory."""
    cfg = _apply_config_overrides(load_config(args.config), args)
    results = Path(cfg.results_dir)
    print("=== INTERNAL-TRE-ONLY analyst notes — diagnostics, NOT a release artefact ===")
    found = False
    for name in (pipeline.SUMMARY, pipeline.BATCH_SUMMARY, pipeline.FINAL_SUMMARY):
        path = results / name
        if path.is_file():
            found = True
            print(f"\n--- {name} (INTERNAL-TRE-ONLY) ---")
            print(path.read_text())
    if not found:
        raise SystemExit(f"no analyst notes under {results}/ — run a request first")

def _audit(args) -> None:
    cfg = _apply_config_overrides(load_config(args.config), args)
    results = Path(cfg.results_dir)
    ledger = results / pipeline.AUDIT_LEDGER
    if not ledger.exists():
        raise SystemExit(f"no audit ledger at {ledger} — run a request first")
    events = io.read_jsonl(ledger)
    root = (results / pipeline.AUDIT_ROOT).read_text().strip()
    verified = audit.verify_ledger(events, root)
    leaks = any(audit.has_forbidden_pii(e) for e in events)  # no participant/pseudo data may appear
    pii = "OK" if not leaks else "FAIL"
    # the ledger check proves the LOG; the generation check proves the ARTEFACTS: the canonical
    # payload, its receipt, the retained request preimage, and (where available) exact replay.
    generation = bridge.verify_release_generation(cfg.results_dir)
    if generation["generation"]:
        gen = "OK" if generation["ok"] else "FAIL"
    else:
        gen = "none"
    print(
        f"audit: {len(events)} events | root {root[:12]}… | "
        f"verify={'OK' if verified else 'FAIL'} | no_participant_data={pii} | "
        f"release_generation={gen}"
    )
    for failure in generation["failures"]:
        print(f"  generation: {failure}")
    if not verified or leaks or not generation["ok"]:
        raise SystemExit("audit verification FAILED")


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="ofh-feasibility", description="Governed genotype-feasibility service."
    )
    sub = p.add_subparsers(dest="command", required=True)
    for name, func, default_help in [
        ("run", _run, "run a single-variant feasibility request"),
        ("batch", _batch, "run a multi-variant (composite-profile) request"),
    ]:
        sp = sub.add_parser(name, help=default_help)
        sp.add_argument("--request", default=None, help="path to the request file")
        sp.add_argument(
            "--template", default=None, choices=sorted(TEMPLATES), help="use a request template"
        )
        _add_config_flags(sp, source_format=True)
        sp.add_argument(
            "--audience",
            default="neutral",
            choices=["neutral", "research", "commercial"],
            help=(
                "shape the INTERNAL analyst note for a neutral, research, or planning "
                "reviewer (never client-facing; view with `notes`)"
            ),
        )
        sp.set_defaults(func=func)
    gp = sub.add_parser("gene", help="run a gene-level WAVE_11 request")
    gp.add_argument("--symbol", required=True, help="gene symbol, e.g. CHEK2")
    gp.add_argument("--study-id", default=None)
    gp.add_argument("--purpose", default=None)
    gp.add_argument(
        "--requested-source",
        default="array_and_imputed",
        choices=["array", "imputed", "array_and_imputed"],
    )
    _add_config_flags(gp, source_format=True)
    gp.add_argument(
        "--audience",
        default="neutral",
        choices=["neutral", "research", "commercial"],
        help="shape the INTERNAL gene analyst note (never client-facing; view with `notes`)",
    )
    gp.set_defaults(func=_gene)
    dp = sub.add_parser("disease", help="run a disease/panel-level WAVE_11 request")
    dp.add_argument("--panel", required=True, help="panel id, e.g. breast_cancer")
    dp.add_argument("--study-id", default=None)
    dp.add_argument("--purpose", default=None)
    dp.add_argument(
        "--requested-source",
        default="array_and_imputed",
        choices=["array", "imputed", "array_and_imputed"],
    )
    _add_config_flags(dp, source_format=True)
    dp.add_argument(
        "--audience",
        default="neutral",
        choices=["neutral", "research", "commercial"],
        help="shape the INTERNAL panel analyst note (never client-facing; view with `notes`)",
    )
    dp.set_defaults(func=_disease)
    fp = sub.add_parser(
        "finalize-eligible", help="finalize the post-phenotype count from an epi return (Wave 8)"
    )
    fp.add_argument("--epi-return", required=True, help="path to the epidemiology return (JSON)")
    fp.add_argument("--request", default=None, help="path to the original variant request")
    fp.add_argument(
        "--checkpoints", default=None, help="path to the human-review checkpoint ledger (JSONL)"
    )
    _add_config_flags(fp, source_format=True)
    fp.set_defaults(func=_finalize_eligible)
    np = sub.add_parser(
        "notes",
        help="print INTERNAL-TRE-ONLY analyst notes from a results directory (diagnostics)",
    )
    _add_config_flags(np)
    np.set_defaults(func=_notes)
    ap = sub.add_parser(
        "audit", help="verify the evidence ledger AND the committed release generation"
    )
    ap.add_argument("action", choices=["verify"], help="ledger action")
    _add_config_flags(ap)
    ap.set_defaults(func=_audit)
    return p


def main(argv: list[str] | None = None) -> None:
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    args = build_parser().parse_args(argv)
    args.func(args)


if __name__ == "__main__":
    main()
