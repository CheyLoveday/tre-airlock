# Variant pre-flight — reference-match, normalization, strand (Wave 7)

The first feasibility gate is **identifiable**: the requested variant must be correctly mapped and
present in the genotype resources. The original `extract.validate_variant` did a *manifest* check —
membership plus stated-build and ref/alt orientation — which is membership-plus-assertion, not a
reference-genome match. `extract.normalize_and_reference_match` adds the missing pre-flight.

More broadly, pre-flight is the **request-integrity gate**: *any* inconsistency or ambiguity between
what was **requested** and what was **supplied** flags here — failing closed or caveating — rather than
slipping into a clean-looking count. The checks below cover build, ref/alt orientation, and
normalization; the same principle extends to other request-vs-allele mismatches (e.g., where a
classification reference is TRE-available, a stated "pathogenic" intent paired with a known-benign CPRA
is a likely variant-identity error and flags — without making clinical significance load-bearing).

It matters here because the scenario variant `10:119669928:C:G` (BAG3) is **two traps at once**:

1. **Build is asserted, not stated.** A CPRA is `CHR:POS:REF:ALT` with no genome-build token; GRCh38
   is an OFH *convention*, and a client can back-form a CPRA from a GRCh37 coordinate. Asserting
   `Literal["GRCh38"]` is not verification.
2. **`C/G` is palindromic.** C/G and A/T SNPs are strand-ambiguous — the complement of the pair is the
   pair itself — so a strand flip cannot be caught by complementation.

## Request well-formedness — the first gate (boundary)

Before any resource or reference lookup, the typed request boundary (`VariantRequest`) fails closed on
a malformed CPRA, so the pipeline never fires on a request that cannot describe a real locus:

| Check | Rule | Rejected example |
|---|---|---|
| **Contig** | chrom ∈ {1–22, X, Y, MT} | `23:…`, `0:…`, `99:…` |
| **Position** | 1-based, and POS ≤ the GRCh38 contig length | `10:0:…`, a coordinate past the contig end |
| **Alleles** | REF, ALT are A/C/G/T and **REF ≠ ALT** | `10:100:C:C` (a monomorphic site, not a variant) |
| **Self-consistency** | the CPRA string equals `chrom:pos:ref:alt` | a CPRA that disagrees with its own fields |

These are cheap and deterministic, but they are the checks that *govern whether the pipeline runs at
all*: a malformed request fails here with a precise message (`invalid chromosome '23'`, `REF == ALT`,
`POS … out of range`), not three stages later as a misleading "not in resource — query the client". The
genetics-heavy checks below run only once the request is well-formed.

## What the pre-flight does

`normalize_and_reference_match(request, reference, observed)` is a pure builder (no IO; the shell
passes the reference). It runs three steps and fails closed or caveats — it never silently assumes
GRCh38 or a forward strand:

| Step | Method | Outcome |
|---|---|---|
| **Normalize** | Parsimonious left-align (bcftools-norm style): trim shared suffix then prefix, advancing POS. No-op for a SNP; real work for indels. | Canonical `normalized_cpra`; a caveat if it differs from the request. |
| **Build** | Match REF to the reference base at CHR:POS. REF==GRCh38 base → confirmed. REF==GRCh37 base → **fail closed** (client gave GRCh37 coords; liftover or re-query). REF matches neither → **fail closed** (mis-specified). Base unavailable → keep asserted build but flag NOT reference-matched. | `build_resolved`, `ref_matched`, a caveat recording how the build was settled. |
| **Strand** (palindromes only) | Allele-frequency concordance: a rare variant whose cohort MAF concords with the panel MAF is forward; concordance with `1 − panel` is a flip; near MAF 0.5, or no panel value, is unresolved. | `strand` ∈ {forward, reverse, unresolved}, `ambiguous`, a caveat. |

For BAG3 the cohort MAF (~0.013) concords cleanly with the reference panel, so the palindrome's strand
**is** resolvable (forward) — the honest result is "trap detected, strand checked, resolved", surfaced
as a client caveat rather than waved through. A palindrome whose strand can't be resolved (MAF near
0.5, or no panel value) returns an explicit ambiguity caveat instead of a count that looks clean.

## Where it sits

- Pure core: `extract.normalize_and_reference_match` (+ `_normalize_alleles`, `_resolve_build`,
  `_resolve_strand`, `observed_maf`).
- Shell: `io.default_reference()` is the **mock** GRCh38/GRCh37 base + panel-MAF stub. In the TRE this
  is replaced by a FASTA lookup (GRCh38, plus GRCh37 for disambiguation) and a reference-panel AF
  source behind the same dict contract — the demo does not ship a reference genome.
- Both orchestration modes run it: `run_pipeline` (in-memory) and the staged path
  (`stage_extract` writes `variant_preflight.json`; `stage_report` threads its caveats).
- Output: the caveats lead the client note's limitations (`reporting.build_result`), so an analyst
  reads how the variant was identified before they read the count.

## Coverage map — the full preflight surface

Preflight is layered; each layer flags (fails closed or caveats) a distinct class of request defect.
Built today vs deliberately deferred — the deferred items are named scope, not oversight:

| Layer | Checks | Status |
|---|---|---|
| **Well-formedness** (boundary) | contig valid, POS 1-based & in-range, REF≠ALT, CPRA self-consistent, parsimonious normalization | **built** |
| **Resource** (manifest / CPRA lists) | present in resource, build & ref/alt match, on-array / on-imputed membership, inaccurate-annotation & multiallelic no-go | **built** |
| **Reference genome** (FASTA / panel) | REF↔GRCh38 base (GRCh37 → liftover), palindromic strand by AF concordance | **built** |
| **Locus reliability** | multiallelic no-go (built); explicit indel-on-array & MNP caveats (planned) | partial |
| **Requested-source availability** | the asked-for source actually present (e.g. array-absent surfaced explicitly, not silent) | **built** |
| **Semantic** (stated intent ↔ allele) | catalogue-backed gene symbol ↔ POS within configured gene span (built); stated significance ↔ classification reference (e.g. ClinVar); rsID / HGVS ↔ CPRA | partial |
| **Batch** (gene/disease/batch) | per-variant preflight (built); normalize-then-dedup across the union (planned) | partial |

Requested-source availability is recorded in `variant_preflight.json` as explicit booleans plus
`source_caveats`, and the client summary's source line shows the same resource-membership status before
the count. Gene-span validation runs when the configurable gene/panel catalogue loads: each variant
assigned to a gene must sit inside that gene's configured GRCh38 span, so a catalogue typo fails before
it can produce a gene-level count. Significance and rsID/HGVS checks remain articulated scope because
the current request model does not carry those fields and the repo does not ship a TRE-available
classification reference.

The principle is constant across layers: never silently wave a request through; the analyst reads *how
the variant was identified* — and any unresolved ambiguity — before they read the count.

## Honesty

The reference base and panel MAF are stubs for the demo, not a shipped reference genome. The check
demonstrates the *method* OFH would run in-TRE; it does not re-adjudicate clinical pathogenicity, and
it supports — does not replace — human governance review. See `docs/reference/BAG3_VERIFICATION.md`
for the separate note that this CPRA is absent from the real imputed list (the demo uses a synthetic
manifest).
