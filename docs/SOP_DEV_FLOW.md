# SOP — development flow

The reproducible change cadence. Mirrors OFH public signals + standard reproducible-research
practice; not a claim of an org-wide OFH Git policy.

## Branch → PR → merge
1. `main` is protected — **no direct commits**. Branch: `feat/` `fix/` `chore/` `test/` `docs/`.
2. Small, single-purpose change; **conventional commits**; one stage/module per PR where practical.
3. Open a PR using `.github/pull_request_template.md`. Governance-touching PRs (consent / SDC /
   airlock / release gate) are flagged and carry an invariant test.
4. CI gates every PR: `ci.yml` (`ruff` + `pytest`) and, for the release gate, `lean.yml`
   (`lake build` + conformance). All green before merge.
5. **Squash-merge**; delete the branch; sync `main` (`git pull --ff-only`).

## Local gates (run before pushing)
```bash
uv sync --extra dev
uv run ruff check
uv run pytest
uv run python run_demo.py          # the slice runs green
cd formal && lake build            # the release-gate proofs compile (Lean)
```

## Determinism & data
Seed 42; same inputs → identical artefacts (golden-tested). Never commit `data/`, `results/`,
`.snakemake/`, `formal/.lake/`, or secrets — they are gitignored and regenerable.

## Releases (when cut — not automatic)
`CHANGELOG.md` (Keep a Changelog) + version bump in `pyproject.toml` + a `v`-tag push triggers
`release.yml` (gates → `uv build` → GitHub release). The MVP is tagged `v0.1.0`.

## AI assistance
AI accelerates implementation and docs; it is a **draft channel, not an authority**. Everything
AI-produced is DRAFT until tests + reproduction + governance checks + human sign-off
(`docs/AI_USAGE_POLICY.md`). Substantial AI-assisted changes get an append-only project note.
