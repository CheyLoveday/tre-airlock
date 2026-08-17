# Missing Data — gaps between the mock and the real OFH resources

> Raw OFH public reference files under `data/raw/` are not committed; they are the publicly
> downloadable variant lists from Our Future Health's researcher documentation (SHA-256s recorded
> in `variant-identifiability-provenance.json`).

This is a **mock on dummy data**. Most gaps are filled by synthesising OFH-shaped dummy data (seed 42);
this file names the gaps explicitly so nothing is silently faked. Each entry says what it is, why it
matters, how the mock currently handles it, and what a human would need to provide to close it for real.

Convention: **(a)** synthesised faithfully, **(b)** fetched from provided/public material, **(c)** truly
blocked — needs a human. Build is never blocked on a single gap.

---

## 1. Array CPRA variant list — FETCHED / VERIFIED  *(b, done)*
- **What:** the genotyping-**array** CPRA list (companion to the imputed list we have).
- **Why:** to confirm whether `10:119669928:C:G` is on the array (the manifest's `on_array` flag), which
  drives the array-vs-imputed source decision and high-confidence calling.
- **Now:** the Release 14 public array CPRA CSV has been fetched to
  `data/raw/our_future_health_cpra_array_variant_list_grch38_v14.csv`. The exact CPRA
  `10:119669928:C:G` is present with `Inaccurate Call=No`. The imputed list does **not** contain the
  variant — see `docs/reference/BAG3_VERIFICATION.md`. The runtime consumes the small committed
  derived artifact `docs/reference/variant-identifiability.csv`, not the raw public lists.
- **Closed by:** `uv run python scripts/verify_cpra.py --chrom 10 --pos 119669928 --ref C --alt G
  data/raw/our_future_health_cpra_array_variant_list_grch38_v14.csv
  data/raw/our_future_health_cpra_imputed_variant_list_grch38-csv.zip`.
- **New (GitBook):** ~8% of array variants are array-ONLY (absent from the imputed / reference panel),
  and OFH direct-assays rare clinical content. BAG3's absence from the imputed list is therefore
  consistent with an array-only/direct-assay variant. The honest resource verdict is now:
  **array-identifiable, imputed-source absent**.

## 2. Variant summary statistics (real DR2 / AF) — NOT AVAILABLE  *(a)*
- **What:** per-variant imputation **dosage r2 (DR2)** and allele frequencies.
- **Why:** DR2 gates whether imputed evidence is usable (`imputed_dr2_min`) and whether it is
  high-confidence (`imputed_dr2_high_confidence`); the pipeline threads `variant_info` through QC,
  classification and reporting.
- **Now:** the public CPRA lists carry only variant IDs plus annotation flags — **no DR2 / AF**. The mock
  supplies the metric via the synthetic `variant_manifest.csv`; public-list availability is overlaid
  separately from `docs/reference/variant-identifiability.csv`.
- **To close:** the real DR2 lives in the **TRE variant summary-statistics VCF**, available only after
  dispensal inside the TRE.
- **Correction (GitBook) — APPLIED:** OFH imputation quality is **dosage r2 (DR2)**, not a traditional
  INFO score; the variant-level summary VCF carries DR2 + ALT AF; the OFH threshold is DR2 >= 0.3 at
  AF > 1%, and quality is ancestry-dependent (lower for non-European at low AF). The manifest field is
  now `dosage_r2` and the client note reports "dosage r2 (DR2)". The config thresholds now use
  `imputed_dr2_*` names; historical `imputed_info_*` keys are accepted only as backward-compatible
  aliases.

## 3. Real sample-QC schema (~40 PCs, batch) — SIMPLIFIED  *(a)*
- **What:** real OFH sample-level QC may carry genetic principal components plus genotyping batch,
  call rate, heterozygosity, genetic sex, and kinship, depending on release and access scope.
- **Why:** ancestry stratification and batch effects are real analysis inputs.
- **Now:** the mock uses a **representative subset** — `array_call_rate, het_rate, sex_check_pass,
  ancestry_pc1, ancestry_pc2, kinship_flag` (2 PCs). Sufficient for single-variant feasibility; ancestry
  stratification is out of scope until a later wave.
- **To close:** widen `SAMPLE_QC_COLUMNS` and the generator to the full PC/batch set when needed.
- **Correction (GitBook):** the CURRENT Release 13 `sample_qc_metrics` provides ONLY batch
  (genotype-calling date), genetic sex, call rate, and `manifest_version` (A1 / C2). Comprehensive PCs,
  heterozygosity, relatedness, and HWE are NOT yet released (planned). So the mock's `kinship_flag` /
  `ancestry_pc1,2` / `het_rate` illustrate the FUTURE schema, not R13; the service computes its own
  kinship / PC QC for the query region. Add `manifest_version` to `SAMPLE_QC_COLUMNS`.

## 4. Dictionary schema vs real `v14` — ALIGNED (column shape)  *(a, done)*
- **What:** the real `our_future_health_data_dictionary_v14.xlsx` is **multi-sheet (one per entity:
  participant, questionnaire, clinic_measurements, …, genetic_data)** with columns
  `entity, name, type, primary_key_type, coding_name, …, title, units, description`; real codings carry
  `coding_name, code, meaning, display_order, parent_code` with OFH conventions (`-999=Suppressed`,
  `-1/-3=Do not know / Prefer not to provide`).
- **Now:** the synthetic dictionaries mirror the **v14 column shape and conventions** (D23): the data
  dictionary uses `entity, name, type, primary_key_type, coding_name, title, units, description`; the
  codings use `coding_name, code, meaning, display_order, parent_code` and include the OFH special-value
  codes (`-999 Suppressed`, `-1/-3`); a `genetic_data` entity is added. We keep a single CSV per
  dictionary (not the multi-sheet xlsx) and keep **field names as our actual data columns** (e.g.
  `participant_id`, not the real `PID`), since the Parquet/TSV data uses those.
- **Remaining (minor):** rename data columns to the exact real names (`PID`, etc.) and emit the full
  ~13-column v14 set if a closer mock is wanted — deferred, low value for the feasibility slice.

## 5. Real genotype store (chunked BGEN/vcf-zarr) — MOCKED  *(a)*
- **What:** real genotypes are a chunked array store (BGEN / vcf-zarr), accessed per chunk.
- **Why:** the OFH-native performance pattern (D7) is a numba `@njit` loop over chunks.
- **Now:** the mock represents the genotype slice as an int8 hardcall table + imputed dosages
  (Parquet); the kernel runs the carrier-count loop over the int8 array. Faithful in *shape*, not scale.
- **To close:** point the extractor at the real dispensed dataset object inside the TRE.

## 6. CPRA-list flags + manifest version — PARTLY DONE  *(a)*
- **What:** the CPRA variant list carries `inaccurate_annotation` (mismapped probe / multi-base
  misalignment) and `multiallelic_variant` (N=499 genotype ceiling effect, all-het); the sample QC
  carries `manifest_version` (A1 / C2).
- **Why:** intake must reject or caution flagged variants; manifest version is a batch confounder for the
  control view.
- **DONE (Wave 7, PR #32):** `inaccurate_annotation` + `multiallelic_variant` are in
  `VARIANT_MANIFEST_COLUMNS`, synthesised by the generator, and `extract.validate_variant` fails closed
  (no-go / query-client) when either flag is `TRUE`.
- **STILL TO CLOSE:** `manifest_version` (and `genotyping_batch`) are NOT yet in `SAMPLE_QC_COLUMNS` or
  the frequency-control strata — that batch-confounder stratification is the remaining live-data gap
  (real values arrive with the TRE QC file). Tracked as the unbuilt remainder of Wave 7.

## 7. Reference-matched variant normalization (build / strand / left-align) — DONE (Wave 7, PR #28)  *(a/c)*
- **DONE:** `extract.normalize_and_reference_match` (a pure pre-flight) + `io.default_reference` (a mock
  GRCh38/GRCh37 base + reference-panel-MAF stub) now: parsimoniously left-align/normalize the alleles;
  resolve the build by matching REF to the reference base (REF==GRCh38 confirms; REF==GRCh37 fails closed
  as back-formed GRCh37 coords; REF matching neither fails closed as mis-specified; an unavailable base is
  flagged not-reference-matched, not silently assumed); and resolve strand for palindromic (C/G, A/T) SNPs
  via allele-frequency concordance (unresolved → an explicit ambiguity caveat, never a silent forward
  assumption). For BAG3 the rare cohort MAF concords with the panel, so strand resolves forward — surfaced
  as a client caveat. Wired into both orchestration modes; doc at `docs/reference/variant_preflight.md`.
  Real FASTA + panel live in the TRE; the demo ships a stub. The description below records the original gap.
- **What:** an upfront pre-flight that, BEFORE manifest lookup: (1) flags that the client request OMITS
  the genome build (the scenario gives CHR:POS:REF:ALT and calls it a CPRA, but states no build);
  (2) reference-matches the REF allele against the reference genome at CHR:POS to confirm / resolve the
  build (REF should equal the GRCh38 base; if it only matches GRCh37, the client gave GRCh37 coords ->
  liftover or reject); (3) left-aligns + normalizes to the canonical parsimonious form (bcftools-norm
  style; trivial for a SNP, needed for indels); (4) handles strand: C/G and A/T are palindromic, so strand
  cannot be resolved by complementation -> resolve via allele-frequency concordance with a reference panel
  or the array assay design; (5) fails closed / caveats on any residual ambiguity.
- **Why:** this IS feasibility check #1 (identifiable). The scenario variant `10:119669928:C:G` is both
  build-unspecified AND a palindromic C/G SNP, both plausibly deliberate traps. CPRA implies GRCh38 by OFH
  convention, but a client may have back-formed a CPRA from a GRCh37 coordinate, so assertion is not
  verification.
- **Now:** `models.VariantRequest.build` is `Literal["GRCh38"]` (asserts GRCh38 by convention) and
  `extract.validate_variant` checks manifest membership + stated-build match + ref/alt orientation. That is
  membership + assertion, NOT a reference-genome match; no normalization, no strand / palindrome handling,
  no omitted-build disambiguation.
- **To close:** add a reference-FASTA-backed pre-flight (a `normalize_and_reference_match` pure builder +
  a small reference-base lookup). The real reference (GRCh38, plus GRCh37 for liftover / disambiguation) is
  available in the TRE; in the mock, stub the reference base for the test variant and flag it. Coordinate
  sanity check: BAG3 sits ~chr10:119.6Mb in GRCh38 but ~chr10:121.4Mb in GRCh37, so the given position is
  itself consistent with GRCh38 (verify exact coordinates in a browser before quoting). Validate-stage
  hardening was implemented as part of the live-data-quirk work and should be reviewed against live TRE
  headers when access exists.
