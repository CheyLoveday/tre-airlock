# OFH Genetic File Mechanics - Consolidated Fact-Check

> Status: consolidated reference from user-supplied research notes, captured 2026-06-09.
> This is not a fresh independent verification pass. Treat it as a patch guide for
> `docs/reference/ofh_tre_genetic_file_formats.md`; verify live release details against the current
> OFH GitBook, the researcher-login data dictionary, and TRE file headers before operational use.

## Executive Summary

The existing OFH file-format reference is broadly useful, but it needs a corrective patch before being
treated as a reliable Release 14 technical reference.

High-priority corrections:

- The array should be described as a custom Illumina Infinium Excalibur beadchip, designated
  `OurFutureHealthv1`, not as the off-the-shelf Illumina GSA with Multi-Disease content. The GSA point
  is only a backbone/provenance caveat.
- If the document targets Release 14, use Release 14 scale figures consistently: array data on 686,416
  variants for 755,000 participants, and imputed/ancestry data harmonised to the same participant
  scale. Release 13 figures such as 701,345 variants, 775,118 array participants, and 550,000 imputed
  participants should be labelled historical.
- The imputed 809 region files cover 23 chromosomes: 22 autosomes plus chromosome X non-PAR. They do
  not cover Y, MT, or X PAR.
- Imputation/phasing was performed by Genomics Ltd, not Genomics England. Genomics England belongs in
  the reference-panel citation context only.
- BGEN 1.2 is confirmed, but the public docs do not state the compression codec. Do not claim zstd
  unless verified inside the TRE.
- Several mechanics remain unverifiable from public docs: exact BED columns, exact GRCh38 FASTA, whether
  `bcftools norm` left-alignment was explicitly applied, male X delivered GT/ploidy strings, phased vs
  unphased separators, and some exact TRE entity identifiers.

## Confidence Legend

- CONFIRMED: supported by OFH public docs or a directly relevant tool/spec source.
- PARTIAL: the broad claim is supported but the exact mechanism or wording needs qualification.
- UNVERIFIABLE: not public; must be checked inside the TRE, data dictionary, or file headers.
- CONTRADICTED: conflicts with the supplied fact-check notes and should be patched.

## Per-Area Verdicts

| Area | Consolidated Verdict | Patch Implication |
|---|---|---|
| Array identity | CONTRADICTED if called GSA. Correct label is custom Illumina Infinium Excalibur `OurFutureHealthv1`; GSA is only backbone context. | Replace GSA wording throughout. |
| Release scale | PARTIAL / stale if R13 numbers are used under R14 framing. | Use one release consistently; prefer R14 for current docs. |
| Array files | CONFIRMED: 160 region files and R14 resources include QC, kinship, regions BED, PCA loadings. | Keep inventory, but label R14-specific naming. |
| Imputed files | CONFIRMED: 809 region files, imputed v6 for R14, pVCF/BGEN plus summary stats and regions BED. | Fix "24 chromosomes" to 23 and add Y/MT/PAR exclusion. |
| Region splitting | CONFIRMED only for imputed processing split at 200 kb; exact delivered bXXXX windows are strongly implied but not verbatim guaranteed. Array split rule is UNVERIFIABLE. | State imputed 200 kb as processing rule; do not assert array window size. |
| BED columns | UNVERIFIABLE publicly. | Say columns must be read with `head` in TRE; do not invent headers/count columns. |
| pVCF vs BGEN region boundaries | CONFIRMED within each dataset; array vs imputed boundaries differ. | Keep dataset-internal equivalence; avoid cross-dataset alignment claims. |
| X PAR/Y/MT | CONFIRMED: imputed excludes Y, MT, and X PAR; array retains these chromosome classes but details are public-doc incomplete. | Add explicit imputed exclusion; mark array PAR/ploidy handling as TRE-header check. |
| Male X non-PAR | PARTIAL: Beagle implies homozygous diploid coding for imputed male X non-PAR, but OFH delivered strings are UNVERIFIABLE publicly. | Phrase as expected behaviour, not confirmed OFH file string. |
| Y/MT non-haploid calls | CONFIRMED known issue: non-haploid calls occur and should be treated as missing. | Add to representation caveats. |
| Contig naming | CONFIRMED: numeric autosomes plus X/Y/MT, no `chr` prefix. | Keep; note Beagle maps may use chr-prefixed names upstream. |
| Normalisation/left alignment | PARTIAL: GRCh38 is confirmed; exact FASTA and explicit `bcftools norm` use are UNVERIFIABLE. | Remove/soften exact FASTA or left-alignment claims. |
| Multi-allelic representation | CONFIRMED: split to biallelic; array multi-allelic loci removed in current release; imputed may retain biallelic split records. | Add distinction between split representation and array removal. |
| Indels | CONFIRMED: array includes SNPs and small indels despite `ofh_snv` prefix; imputed contains SNVs and indels. | Avoid saying `ofh_snv` means SNV-only. |
| CPRA IDs | CONFIRMED: CHR:POS:REF:ALT on GRCh38 after biallelic splitting. | Keep; tie exact left-aligned status to normalisation caveat. |
| Array calling | CONFIRMED: Illumina ACLI v2.1.0, C2 manifest. Cluster file/version is UNVERIFIABLE publicly. | Add ACLI/C2; do not invent egt version. |
| Imputation target pipeline | CONFIRMED: Beagle 5.4 `beagle.22Jul22.46e.jar`, default burn-in/iterations/window/overlap. | Keep. |
| Reference panel | CONFIRMED: UKB 200k SHAPEIT5-phased WGS, Field 20279, 184,801 retained samples. | Do not cite SHAPEIT4.2.2 as delivered panel production version. |
| Beagle maps | CONFIRMED: PLINK-format GRCh38 maps from Beagle website; exact map version string not public. | Keep with caveat. |
| Imputed FORMAT | CONFIRMED: delivered pVCF GT:GP, dosage derivable as GP_RA + 2*GP_AA. | Keep; avoid claiming DS is delivered in OFH per-region pVCF unless header-verified. |
| Variant summary fields | PARTIAL: DR2, ALT AF, number of imputed/typed groups confirmed. RAF field is UNVERIFIABLE. PROP_TYPED description has documented erratum. | Add erratum; soften RAF claim. |
| SAK/dx tooling | CONFIRMED at high level from DNAnexus docs. | Keep examples as TRE tooling context, not OFH pipeline internals. |
| TRE entity names | PARTIAL: some genetic entities are public; exact linked-health snake_case identifiers are UNVERIFIABLE. | Label internal entity identifiers as login-gated. |

## Header-Inspection Checklist For TRE Access

When TRE access is available, resolve the unverifiable mechanics with direct file inspection:

```bash
bcftools view -h ofh_snv.chrZ-bXXXX.vcf.gz | sed -n '1,80p'
bcftools view -h ofh_imputed.v6.chrZ-bXXXX.vcf.gz | sed -n '1,120p'
head -n 5 ofh_snv_regions.bed
head -n 5 ofh_imputed_regions.v6.bed
head -n 5 ofh_snv.chrZ-bXXXX.sample
head -n 5 ofh_imputed.v6.chrZ-bXXXX.sample
```

Specific questions to answer in the TRE:

- What are the exact `##reference` and `##contig` header lines?
- Which FORMAT/INFO fields are actually populated in one array pVCF and one imputed pVCF?
- What are the exact BED columns, and do they include the `bXXXX` identifier and/or variant count?
- Are imputed X non-PAR male genotypes written as homozygous diploid, and are they phased with `|`?
- How are array X PAR, Y, and MT genotypes represented in delivered files?
- What BGEN compression codec is used, if discoverable from file metadata/tool output?

## Patch Targets For The Existing Reference

Patch `docs/reference/ofh_tre_genetic_file_formats.md` using this reference as the control document:

1. Replace the array identity section.
2. Decide whether the whole document is Release 14 current-state or historical multi-release. If current,
   remove stale R13 scale numbers or explicitly label them as R13.
3. Fix imputed chromosome arithmetic and add Y/MT/X-PAR exclusion.
4. Replace Genomics England wording with Genomics Ltd where describing OFH imputation operations.
5. Mark public-doc gaps as `UNVERIFIABLE publicly; check in TRE headers`.
6. Add the PROP_TYPED erratum and SHAPEIT5 reference-panel nuance.
7. Add the TRE header-inspection checklist above as an operational appendix.

## Relationship To Wave 9

This fact-check does not itself require changing the code. It should inform the next Wave 9 doc patch:

- The synthetic OFH-format generator should continue to state what is real format and what is synthetic.
- If generator headers or comments claim zstd/BGEN/native OFH internals, soften them unless the repo
  actually writes/verifies that format.
- The adapter should keep `ofh_snv` as a naming convention and not infer SNV-only content.
- Generic region resolution should be tested against BED columns once real TRE column structure is known.
