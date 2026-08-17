## What & why
<one or two lines: what changed and why>

## Wave / decision

## Governance impact
- [ ] No change to consent gate / SDC / airlock behaviour, OR
- [ ] Governance behaviour changed (describe, and name the invariant test that covers it):

## Checks
- [ ] `uv run ruff check` clean
- [ ] `uv run pytest` green
- [ ] Unit tests added/updated for changed core logic
- [ ] Integration / e2e updated if a stage changed
- [ ] Any new dependency is on the `tre-package-access` allowlist (reason recorded in CHANGELOG/docs)
- [ ] No performance claim without a saved profile artefact
- [ ] Docs / CHANGELOG updated alongside the change
- [ ] No `data/`, `results/`, or secrets committed
