# Design decisions

The *why* behind the judgment calls in this MVP. The through-line is **proportionality and clear
boundaries**: right-size every choice to the problem and to OFH's actual stage (a growing resource,
still changing, governed end-to-end), and state the chosen boundary with the same care as the built
surface.

## Governance Built Into Execution
Consent gate, statistical disclosure control (SDC) with secondary suppression, least-privilege outputs,
a tamper-evident audit ledger,
and a release gate that is the **sole** path to an export.
**Why:** for a TRE the question that matters is "can this leave?" The `ReleaseCandidate` is
`frozen, extra="forbid"`, so a participant-level field is *structurally impossible to construct* — the
unsafe state is structurally excluded and re-verified at the gate. Governance encoded as types + a
fail-closed gate beats governance-by-convention.

## Identifiability Computed From Published Lists
The "is this variant in the resource?" verdict is derived from the real Release-14 array + imputed CPRA
lists (with SHA-256 provenance + line numbers), cached to a small committed artifact.
**Why:** the first feasibility gate has to be *true*. BAG3 → array-only (then ~15 in the synthetic
cohort); CHEK2
c.1100delC → array-absent, imputed-present-but-low-DR2 → NO-GO; I157T → array-direct. Computed against
the published manifests and reproducible by re-running the builder. The 3.5 GB imputed list is scanned
**once, offline**; the runtime reads the small artifact.

## Preflight Is The First Gate — And The Cheapest Checks Guard It
Before any resource or reference lookup, the typed request boundary fails closed on a malformed request:
an invalid contig (`chr23`, `chr0`), a position past the contig end, `REF == ALT` (a monomorphic site,
not a variant), or a CPRA that disagrees with its own fields. Pathogenicity is **never** load-bearing —
the determination is significance-agnostic — but *any* inconsistency or ambiguity between what was
requested and what was supplied flags at preflight (build, strand, normalization, and, where a
classification reference is available, a stated-intent-vs-allele mismatch), failing closed or caveating
rather than waving through.
**Why:** the first gate governs whether the pipeline fires at all. Elaborate downstream governance (the
Lean release gate, SDC, the audit ledger) behind a front door that accepts `chr23` or `REF==ALT` is
exactly backwards. The cheapest checks are the ones that must never be skipped — a malformed request
should fail at the door with a precise message, not three stages later as a misleading "not in resource".
Full surface: `reference/variant_preflight.md`.

## Synthetic Data, OFH-Format Shapes
Synthetic cohort; OFH-format bgzip pVCF + tabix stand-ins; published variant lists; OFH package
allowlist discipline. The quality/cohort layers (DR2, QC) are synthetic and **labelled** as such.
**Why:** verified fact vs reasonable assumption, clearly separated. A genetics reviewer can trust what's
marked verified and discount what's marked illustrative. The honesty *is* the credibility.

## One Request Family Built Deep; The Rest Mapped
Recall-by-genotype (variant → gene → disease) is built end-to-end; the wider feasibility surface
(cohort-sizing, PRS/ancestry, genotype–phenotype, pharmacogenetic) is articulated as the roadmap.
**Why:** depth on the hardest family — genetics + governance + disclosure control — demonstrates more
than a breadth of stubs. Naming the boundary ("here's the whole map; here's how the rest slots into the
same governed primitives") is the honest, higher-judgment move.

## Decision Support: Surface The Accounting, Defer The Judgment
Quality cut-offs are configurable and **surfaced** in the output, applied as a late, reversible
projection. The genotype result is a *ceiling*; the hard decisions
(phenotype eligibility, recruitment, which threshold to adopt) are downstream.
**Why:** a feasibility service informs a human decision; configurable thresholds keep that judgment
visible.
Show the masks and the trade-off; let the analyst and governance decide with full information.

## Proportionality: Right-Sized Tools
CPU vectorisation is sufficient for single-variant counting. The Merkle audit ledger is ~160 lines of
stdlib `hashlib`. Numba is reserved for the genotype inner loop and used as a *reconciliation oracle*.
**Why:** the signal is judgment — knowing the right scale for the problem. Over-engineering reads as
showing off; restraint is the harder, more valuable thing.

## Performance Is Measured
Vectorise by default; keep the cohort/variant axis out of Python loops; the OFH ingest is tabix-scoped,
and huge files are scanned once and cached.
**Why:** at 755k participants a missed loop passes on small fixtures and dies at scale. Profiled with
committed evidence (`reference/profile-summary.md`), and a scaling-slope regression test catches a
reintroduced O(n²). Performance claims are backed by committed evidence.

## CI Gates The Critical Path
CI = ruff + the full test suite (governance invariants, SDC, kernel-vs-reference) + the Lean proof gate.
The performance check is an **on-demand tool** used when the genotype path or scale claims change.
**Why:** CI should go red for failures that matter on the critical path. A noisy CI trains
warning-blindness. For a growing, still-changing resource, every red has to be worth acting on, so the
gate stays lean and green *means something*.

## Built for OFH's stage — deliberately lean
A clean, focused repo; critical CI gates; documented roadmap boundaries.
**Why:** an early, growing, high-friction resource benefits from low process and tooling overhead.
Reduce friction at the critical points: governance, reproducibility, and the airlock. The judgment
about where to stop is the fit.
