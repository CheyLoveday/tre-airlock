<!-- Captured 2026-06-09 from an uploaded reference compiled from OFH public GitBook docs
     (ourfuturehealth.gitbook.io) + UK Biobank BGEN sample-file spec. This is a REFERENCE for
     the real OFH TRE genetic file formats. scripts/generate_ofh_files.py produces GENUINE
     OFH-format synthetic files — real bgzip(BGZF) pVCF + tabix .tbi, written with pysam/htslib
     (the offline generator can use any tooling; the `ofhgen` extra is local/dev-only, never the
     TRE runtime). The data are synthetic, and the generated files are valid stand-ins for public OFH
     file mechanics rather than a claim of exact private TRE contents.
     Remaining gap: a real .bgen (every pip BGEN lib is read-only; real BGEN comes from
     plink2/qctool). See docs/reference/ofh_file_format_mechanics_fact_check.md. -->

# OFH TRE Genetic File Formats: Deep Technical Reference

> **This is not a reconstruction of OFH's internal platform.** It is a captured public-documentation
> reference used to build a **synthetic, governed mock that follows the public shape of OFH genetic
> data as closely as the available docs allow**, while clearly labelling assumptions and unverifiable
> details. We do not claim perfect exactness — only that the mock is OFH-shaped and mechanically
> sympathetic to the public structure.
>
> Captured-reference draft, not an authority document. Patched 2026-06-09 against the consolidated
> fact-check (Wave 9A): array identity, Release 13↔14 scale, imputed chromosome coverage, panel/codec
> claims, and the points that can only be confirmed inside the TRE. Items marked **UNVERIFIABLE
> publicly** must be checked against live TRE file headers / the data dictionary (see the appendix at
> the end). The repo uses synthetic stand-ins shaped to these formats, not real OFH data.
>
> See `docs/reference/ofh_file_format_mechanics_fact_check.md` for the consolidated correction list.

## Overview

The Our Future Health (OFH) Trusted Research Environment (TRE), hosted on DNAnexus, makes two distinct genetic datasets available to approved researchers: a **genotype array** dataset (Release 14: ~686,416 variants for ~755,000 participants; the ~701,345 variants / ~775,118 participants figures are historical Release 13) and an **imputed genotype** dataset (~159.6 million variants, harmonised to the same R14 participant scale). Both datasets are delivered in two parallel file formats — **pVCF** (phased/population VCF, a standard VCF 4.x file) and **BGEN 1.2** — allowing analysts to pick the toolchain that fits their workflow. This document provides a complete technical reference for every file type, its internal format fields, naming conventions, QC rules, and the tooling used to access it within the TRE.[^1]

***

## Release History and Version Numbering

All file names carry an explicit version string (`v5`, `v6`, `v7`, etc.) that tracks the data release. The current live release as of mid-2026 is **Release 14**, which contains array data versioned without a release suffix (e.g. `ofh_snv.chrZ-bXXXX.vcf.gz`) and imputed data at **v6** (e.g. `ofh_imputed.v6.chrZ-bXXXX.vcf.gz`).[^1]

Key release landmarks:

- **Release 13 (December 2025)**: array manifest switched entirely from A1 to C2; all previously A1-called samples were re-called under C2; the `manifest_version` column in the sample QC TSV changed to show `v2` for all samples; 1,407 samples were flagged as having an implausibly large number of third-degree-or-closer relatives.[^1]
- **Release 14 (2026)**: imputed data promoted to v6; 809 imputed region files across **23 chromosomes — 22 autosomes + chromosome X non-PAR** (Y, MT, and the X pseudoautosomal regions are NOT imputed). R14 array scale is ~686,416 variants / ~755,000 participants; the Release 13 figures (701,345 variants; 775,118 array / 550,000 imputed participants) are historical.

***

## Part 1 — Genotype Array Data

### 1.1 What It Contains

The array dataset is the direct output of a **custom Illumina Infinium Excalibur beadchip** designated `OurFutureHealthv1` (the Illumina Global Screening Array / GSA is only backbone provenance, *not* the delivered product), called with **Illumina ACLI v2.1.0** on the **C2 manifest** (all samples from Release 13 onward; the cluster `.egt` version is not public). It contains hard-called genotypes only — no imputed dosage. **No variant-level filtering is applied before delivery**: all variants passing the sample-level pipeline are included regardless of allele frequency, missingness, or HWE. Release 14 delivers ~686,416 variants (the ~701,345 figure is historical Release 13). Despite the `ofh_snv` prefix the array carries SNPs **and small indels**, not SNVs only.[^1]

### 1.2 File Inventory — Array (Release 14)

| File pattern | Count | Description |
|---|---|---|
| `ofh_snv.chrZ-bXXXX.vcf.gz` | 160 | Bgzip-compressed pVCF, one per genomic region |
| `ofh_snv.chrZ-bXXXX.vcf.gz.tbi` | 160 | Tabix index for each pVCF region |
| `ofh_snv.chrZ-bXXXX.bgen` | 160 | BGEN 1.2 binary, one per region |
| `ofh_snv.chrZ-bXXXX.sample` | 160 | BGEN sample file, one per region |
| `ofh_snv.chrZ-bXXXX.bgen.bgi` | 160 | BGEN index (bgenix), one per region |
| `ofh_sample_qc_metrics.tsv` | 1 | Per-sample QC metrics (tab-separated) |
| `ofh_snv_kinship.txt` | 1 | Pairwise kinship coefficients |
| `ofh_snv_regions.bed` | 1 | BED file mapping `bXXXX` region codes to chr:start-end |
| `ofh_snv_pca_loadings.vcf.gz` | 1 | PCA variant loadings (bgzip VCF) |
| `ofh_snv_pca_loadings.vcf.gz.tbi` | 1 | Tabix index for PCA loadings |

`chrZ` is the chromosome identifier (1–22, X, Y, MT) using numeric notation except for X, Y, MT. `bXXXX` is a zero-padded integer region code that maps to genomic coordinates via `ofh_snv_regions.bed`. The 160 region files cover all chromosomes combined (not 160 per chromosome).[^1]

### 1.3 pVCF Format — Array

The array pVCF follows **VCF 4.1** specification and is **bgzip-compressed** with a paired **tabix (`.tbi`) index**.[^1]

**Key header fields:**
- `##fileformat=VCFv4.1`
- `##reference=GRCh38` — all coordinates are on the GRCh38/hg38 reference
- Chromosome notation is numeric (1–22) except X, Y, MT

**CHROM / POS / ID / REF / ALT:**
- Variant IDs in the `ID` column are formatted as **`CHR:POS:REF:ALT` (CPRA)** aligned to GRCh38[^1]
- Multi-allelic sites are represented as separate rows (split by allele)

**FORMAT column — array pVCF:**

| Field | Type | Description |
|---|---|---|
| `GT` | String | Hard-called diploid genotype (e.g. `0/0`, `0/1`, `1/1`, `./.` for missing) |

The array pVCF carries **only `GT`** — no dosage (`DS`), no genotype probabilities (`GP`), no phasing information (`HDS`/`AP`). This is the key distinction from the imputed pVCF.[^1]

**Illustrative pVCF record (array):**
```
##fileformat=VCFv4.1
##reference=GRCh38
#CHROM  POS       ID                    REF  ALT  QUAL  FILTER  INFO  FORMAT  SAMPLE1    SAMPLE2    SAMPLE3
1       752566    1:752566:A:G          A    G    .     .       .     GT      0/0        0/1        1/1
1       752721    1:752721:C:T          C    T    .     .       .     GT      0/0        0/0        ./.
```

**INFO column — array pVCF:**
The array pVCF INFO column is documented as `.` (no INFO fields are populated). All variant-level QC metrics are held in the separate `ofh_snv_regions.bed` and `ofh_sample_qc_metrics.tsv` files rather than embedded in the VCF INFO field.[^1]

### 1.4 BGEN 1.2 Format — Array

The BGEN files use **BGEN version 1.2** (the genotype-probability-block compression codec — zlib vs zstd — is NOT stated in the public docs; verify in the TRE from file metadata). BGEN 1.2 stores per-sample, per-variant genotype probability distributions rather than hard calls. For array data, these probabilities are typically hard-coded to near-certainty values derived from the `GT` field (i.e. probability vectors of the form {1,0,0}, {0,1,0} or {0,0,1} for homref, het, homalt respectively).[^1]

**BGEN 1.2 structure:**
- **Header block**: magic bytes `bgen`, version flags, number of samples (N), number of variants (M), flags byte
- **Sample identifier block**: N sample IDs stored as length-prefixed strings
- **Variant data blocks**: per-variant records containing CHROM, POS, ID, REF, ALT, then a compressed genotype probability block

**Associated `.sample` file (Oxford format):**
```
ID_1 ID_2 missing sex
0    0    0       D
OFHID_00001  OFHID_00001  0  1
OFHID_00002  OFHID_00002  0  2
```
Column 1 (`ID_1`) and column 2 (`ID_2`) are both the OFH pseudonymous participant ID (PID). Column 3 is missing data proportion (always 0 in the dispensed file). Column 4 is inferred sex (1=male, 2=female).[^2]

**Associated `.bgen.bgi` index** is a SQLite database created by `bgenix` that enables fast random-access queries by chromosome and position range.

### 1.5 Sample QC Metrics TSV — Array

The `ofh_sample_qc_metrics.tsv` is a tab-separated file with one row per participant. Based on documentation, columns include:[^1]

| Column | Description |
|---|---|
| `participant_id` | OFH pseudonymous participant ID |
| `genotyping_batch` | Plate/batch identifier |
| `manifest_version` | Array manifest used (`v1`=A1, `v2`=C2); all samples show `v2` from Release 13 onward |
| `estimated_genetic_sex` | Inferred sex from genotype data (M/F) |
| `call_rate` | Per-sample genotype call rate |
| Additional QC flags | (full column list defined in the OFH data dictionary genotype tab) |

Full column definitions are published in the **OFH data dictionary** accessible via the TRE Cohort Browser under the genotype entity tab.[^1]

### 1.6 Sample-Level QC Thresholds Applied Before Delivery

Samples are **excluded** from the delivered files if any of the following apply:[^1]

- Call rate < 97%
- Self-reported sex at birth missing
- Sex discordance between self-reported and genetically inferred sex (except participants recorded as Intersex)
- TGA control probe values outside the manufacturer's recommended range
- Technical replicate genotype concordance < 99%
- Control sample WGS concordance < 99%
- Plate-level sex discordance > 4%
- Plate-level exclusion: ≥90 of 96 wells on a plate excluded due to the above rules
- Exclusion of 1000 Genomes Project control samples (non-participant)

***

## Part 2 — Imputed Genotype Data

### 2.1 Imputation Pipeline

Imputation was performed by **Genomics Ltd** using **BEAGLE 5.4** with the following parameters:[^1]

- **Reference panel**: UK Biobank 200k **SHAPEIT5-phased** WGS (Field 20279), filtered to **184,801 retained samples** (cite the delivered SHAPEIT5 panel, not an earlier SHAPEIT4.x production version)
- The SHAPEIT-phased version was chosen over the Beagle-phased version because it includes both SNVs and small indels
- **Phasing**: statistical haplotype phasing performed by BEAGLE 5.4 before imputation
- **BEAGLE parameters**: 3 burn-in iterations; 12 main iterations; 40 cM window; 2 cM overlap
- **Imputation grouping**: samples were grouped by genotyping batch date, with group sizes of 2,000–8,000 samples; batches from multiple dates were combined if a group would have been <2,000 samples

### 2.2 File Inventory — Imputed (Release 14 / v6)

| File pattern | Count | Description |
|---|---|---|
| `ofh_imputed.v6.chrZ-bXXXX.vcf.gz` | 809 | Bgzip pVCF per region |
| `ofh_imputed.v6.chrZ-bXXXX.vcf.gz.tbi` | 809 | Tabix index per region |
| `ofh_imputed.v6.chrZ-bXXXX.bgen` | 809 | BGEN 1.2 per region |
| `ofh_imputed.v6.chrZ-bXXXX.sample` | 809 | BGEN sample file per region |
| `ofh_imputed.v6.chrZ-bXXXX.bgen.bgi` | 809 | BGEN bgenix index per region |
| `ofh_imputed_sample_qc_metrics.v6.tsv` | 1 | Per-sample imputed QC metrics |
| `ofh_imputed_variant_summary_stats.v6.vcf.gz` | 1 | Variant-level summary stats VCF |
| `ofh_imputed_variant_summary_stats.v6.vcf.gz.bgi` | 1 | bgenix-style index for summary stats |
| `ofh_imputed_regions.v6.bed` | 1 | BED file mapping region codes to chr:start-end |

The 809 region files cover **23 chromosomes — 22 autosomes + chromosome X non-PAR** — across the ~159.6 million imputed variants. **Y, MT, and the X pseudoautosomal (PAR1/PAR2) regions are NOT imputed.**[^1]

### 2.3 pVCF Format — Imputed

The imputed pVCF follows **VCF 4.2** (note: one version higher than the array pVCF, which is 4.1).[^1]

**FORMAT column — imputed pVCF:**

| Field | Type | Description |
|---|---|---|
| `GT` | String | Thresholded hard-call genotype (0/0, 0/1, 1/1, ./.) derived from maximum-posterior GP |
| `GP` | Float triplet | Posterior genotype probabilities for RR, RA, AA genotype states, sum to 1.0 (e.g. `0.02,0.15,0.83`) |

The `GT` field in the imputed pVCF is derived from the `GP` field by applying a posterior probability threshold (typically the most probable genotype state). The `GP` field is the primary carrier of imputation information and should be used in dosage-based analyses rather than the hard-call `GT`.[^1]

**Dosage calculation from GP:**
Dosage (expected allele count) = \( 0 \times GP_{RR} + 1 \times GP_{RA} + 2 \times GP_{AA} = GP_{RA} + 2 \times GP_{AA} \)

This is equivalent to the `DS` field used in some other imputed VCF conventions (e.g. Michigan Imputation Server output), but OFH does not add a separate `DS` tag — the dosage must be computed from `GP` by the analyst.

**Illustrative imputed pVCF record:**
```
##fileformat=VCFv4.2
##reference=GRCh38
##FORMAT=<ID=GT,Number=1,Type=String,Description="Genotype">
##FORMAT=<ID=GP,Number=G,Type=Float,Description="Genotype posterior probabilities">
#CHROM  POS       ID                    REF  ALT  QUAL  FILTER  INFO  FORMAT    SAMPLE1          SAMPLE2
1       752566    1:752566:A:G          A    G    .     .       .     GT:GP     0/0:0.97,0.03,0  0/1:0.05,0.89,0.06
1       865545    1:865545:G:A          G    A    .     .       .     GT:GP     0/1:0.02,0.96,0.02  1/1:0.01,0.04,0.95
```

### 2.4 Variant Summary Statistics VCF

The `ofh_imputed_variant_summary_stats.v6.vcf.gz` is a single genome-wide VCF containing one record per variant with **no per-sample columns** — only variant-level aggregate statistics in the INFO field.[^1]

**Documented INFO content** (from OFH release notes; exact field names are defined in the OFH data dictionary):[^1]

| INFO field (approximate) | Description |
|---|---|
| Dosage r² (`DR2` or similar) | Imputation accuracy metric; ratio of observed variance in dosage to its theoretical maximum. Range 0–1; higher = better imputed |
| ALT allele frequency (`AF`) | Observed ALT allele frequency across all imputed samples |
| Reference allele frequency (`RAF`) | 1 − AF — *an explicit RAF INFO field is UNVERIFIABLE publicly; confirm in TRE headers* |
| Number of groups imputed | Count of imputation groups for which the variant was imputed (not directly typed) |
| Number of groups directly genotyped | Count of imputation groups for which the variant was present on the array |
| `PROP_TYPED` | Proportion of groups in which the variant was directly typed rather than imputed. *Documented erratum: the public description of this field was corrected — treat exact semantics as TRE-header-verifiable.* |

This file is the primary resource for **pre-filtering variants** before loading the large per-region BGEN/pVCF files, and it is the correct source for the `DR2` threshold that defines the Tier 2 / Tier 3 boundary in a variant evidence hierarchy.

**Recommended workflow**: query `ofh_imputed_variant_summary_stats.v6.vcf.gz` by CPRA to determine:
1. Whether the variant exists in the imputed dataset at all
2. Its `DR2` score (threshold ≥ 0.3 is the documented QC requirement)
3. Whether it was directly typed in at least some groups (`PROP_TYPED > 0`)

Only then pull the relevant region BGEN/pVCF files.

### 2.5 Variant-Level QC Applied to Imputed Data

Variants are excluded from imputation input (per group) if:[^1]

- Genotype missingness > 5%
- Hardy–Weinberg equilibrium P < 1×10⁻¹⁰
- Multi-allelic (unless the multi-allelic site arises from imputation itself)
- Dosage r² < 0.3 for variants with ALT allele frequency > 1%

### 2.6 Sample QC for Imputed Data

The `ofh_imputed_sample_qc_metrics.v6.tsv` contains:[^1]

| Column | Description |
|---|---|
| `participant_id` | OFH PID |
| `genotyping_batch` | Genotyping batch |
| `imputation_group` | Pseudo-anonymised imputation group ID |
| `estimated_genetic_sex` | Inferred sex |
| Additional columns | Defined in OFH data dictionary genotype tab |

Not all array-genotyped participants received imputed data: the ~550,000 / ~775,000 split is a **historical Release 13** figure (Release 14 harmonises to the ~755,000 participant scale).[^1]

***

## Part 3 — TRE Data Entities

Within the TRE, files are not exposed as raw filesystem paths. Instead, they are wrapped in **named data entities** accessible via the DNAnexus Cohort Browser and SDK. The complete entity list for Release 14:[^1]

| Entity name | Contents |
|---|---|
| `snv_pvcf` | Array pVCF files (160 regions) |
| `snv_bgen` | Array BGEN files (160 regions) |
| `snv_resources` | Array QC TSV, kinship, BED, PCA loadings |
| `imputed_pvcf` | Imputed pVCF files (809 regions) |
| `imputed_bgen` | Imputed BGEN files (809 regions) |
| `imputed_resources` | Imputed QC TSV, variant summary stats, BED |
| `participant` | Core participant demographic and consent fields |
| `questionnaire` | Lifestyle and health questionnaire responses |
| `clinic_measurements` | Anthropometric and clinical measurements |
| `poct_lipid_profile` | Point-of-care lipid results |
| `nhse_eng_inpat` | HES Admitted Patient Care (inpatient) |
| `nhse_eng_ed` | HES Emergency Department |
| `nhse_eng_outpat` | HES Outpatient |
| `nhse_eng_ecds` | Emergency Care Data Set |
| `nhse_eng_primcare_meds` | Primary care prescribed medications |
| `nhse_engwal_deaths` | ONS death registrations (England & Wales) |
| `nhse_eng_canpat` | NCRAS cancer patient data |
| `nhse_eng_canreg_pattumour` | NCRAS cancer registration (tumour-level) |
| `nhse_eng_canreg_treat` | NCRAS cancer treatment records |
| `nhse_eng_canreg_pre1995` | Pre-1995 cancer registrations |
| `participant_nhs_linked` | NHS linkage status flags |

***

## Part 4 — Tools Available in the TRE

### 4.1 Swiss Army Knife (SAK)

Swiss Army Knife is the primary bioinformatics execution environment on the OFH TRE. It is a DNAnexus app that accepts one or more input files (`-iin`) and a bash command string (`-icmd`), stages the input files to a temporary working directory, executes the command, and uploads outputs back to the project.[^1]

Bundled tools inside Swiss Army Knife include:
- **plink / plink2** — GWAS, LD, PCA, format conversion
- **qctool v2** — BGEN manipulation, filtering by INFO score, format conversion BGEN ↔ VCF
- **bgenix** — BGEN index creation and region extraction
- **bcftools** — VCF/BCF manipulation, filtering, annotation
- **samtools** — BAM/CRAM handling (less relevant for genotype data)
- **Regenie** — whole-genome regression GWAS, can read BGEN directly
- **tabix / bgzip** — VCF index creation and compression

**SAK invocation pattern:**
```bash
dx run swiss-army-knife \
    -iin="/path/to/ofh_snv.chrZ-bXXXX.bgen" \
    -iin="/path/to/ofh_snv.chrZ-bXXXX.sample" \
    -icmd='plink2 --bgen ofh_snv.chrZ-bXXXX.bgen ref-first \
           --sample ofh_snv.chrZ-bXXXX.sample \
           --maf 0.01 --geno 0.05 --hwe 1e-6 \
           --make-bed --out chr1_filtered' \
    --detach -y
```

The `--detach` flag is required when launching from inside another TRE job; `-y` suppresses confirmation prompts.[^1]

### 4.2 dx CLI Commands for Finding Genetic Files

```bash
# List all BGEN files in the project
dx find data --name "*.bgen" --brief

# List all BGEN files in a specific folder, non-recursive
dx find data --path "/path/to/directory" --name "*.bgen" --brief --norecurse

# Find files matching a pattern (e.g. all chr1 imputed files)
dx find data --name "ofh_imputed.v6.chr1-*.bgen" --brief

# Store file IDs in a bash array for batch processing
bgen_files=($(dx find data --name "ofh_imputed.v6.chr*.bgen" --brief))
echo "Found ${#bgen_files[@]} BGEN files"

# Find all completed jobs
dx find jobs --project project-XXXX --state done

# Find jobs run with a specific applet by a specific user
dx find jobs --project project-XXXX --state done --app applet-XXXX --user user-XXXX
```

### 4.3 Accessing Data via dx extract_dataset

For phenotype/clinical data, the `dx extract_dataset` command is used rather than direct file access:

```bash
# Get the dataset ID from the Cohort Browser
DATASET_ID="dataset-XXXX"

# Extract specific entity fields
dx extract_dataset $DATASET_ID \
    --fields "participant.pid,participant.year_of_birth,participant.sex_at_birth" \
    --output participant_fields.csv

# Use Table Exporter app for large extracts
dx run app-table-exporter/3.0.150 \
    -idataset_or_cohort_or_dashboard=$DATASET_ID \
    -ifield_names_file_txt="file-XXXX" \
    -ientity=participant \
    --detach -y
```

### 4.4 Parallel BGEN Processing with Swiss Army Knife

The OFHB1 example notebook demonstrates a three-step pattern for bulk BGEN operations:[^1]

**Step 1 — Discover files:**
```bash
bgen_files=($(dx find data --name "*.bgen" --brief))
```

**Step 2 — Write a processing script and upload it:**
```bash
cat > script.sh << 'EOF'
#!/bin/bash
NUM_PARALLEL=$(($(nproc) - 1))

# Index all BGEN files
for f in *.bgen; do bgenix -index -g "$f"; done

# Filter by INFO score using qctool
for f in *.bgen; do
    base="${f%.bgen}"
    qctool -g "$f" -og "qc_output/${base}_info.bgen" -threshold 0.8
done

# Generate summary statistics
for f in *.bgen; do
    base="${f%.bgen}"
    if [ -f "${base}.sample" ]; then
        qctool -g "$f" -s "${base}.sample" -snp-stats -osnp "summary_stats/${base}_stats.txt"
    fi
done
EOF

dx upload script.sh --destination /scripts/script.sh
```

**Step 3 — Execute via SAK:**
```bash
dx run swiss-army-knife \
    $(for fid in "${bgen_files[@]}"; do echo "-iin=$fid"; done) \
    -iin="file-XXXX_script" \
    -icmd='bash script.sh' \
    --detach -y
```

***

## Part 5 — Format Conversion Reference

### 5.1 BGEN → PLINK BED (via plink2)

```bash
plink2 \
    --bgen ofh_imputed.v6.chr1-b0001.bgen ref-first \
    --sample ofh_imputed.v6.chr1-b0001.sample \
    --maf 0.01 \
    --geno 0.05 \
    --hwe 1e-6 \
    --make-bed \
    --out chr1_filtered
# Output: chr1_filtered.bed, chr1_filtered.bim, chr1_filtered.fam
```

### 5.2 BGEN → VCF (via qctool)

```bash
qctool \
    -g ofh_imputed.v6.chr1-b0001.bgen \
    -s ofh_imputed.v6.chr1-b0001.sample \
    -og chr1_b0001.vcf \
    -os chr1_b0001.sample
```

### 5.3 Filter BGEN by INFO score (via qctool)

```bash
# Keep only variants with INFO (dosage r²) ≥ 0.8
qctool \
    -g ofh_imputed.v6.chr1-b0001.bgen \
    -og chr1_b0001_info08.bgen \
    -threshold 0.8
```

### 5.4 Region extraction from pVCF (via tabix + bcftools)

```bash
# Extract a single variant by CPRA
tabix ofh_imputed.v6.chr1-b0001.vcf.gz 1:752566-752566

# Extract a gene region
bcftools view ofh_imputed.v6.chr1-b0001.vcf.gz \
    --regions 1:752566-850000 \
    -o region.vcf.gz -O z
tabix region.vcf.gz
```

### 5.5 Lookup variant in summary stats before pulling region file

```bash
# Does variant 1:752566:A:G exist and pass DR2 ≥ 0.3?
tabix ofh_imputed_variant_summary_stats.v6.vcf.gz 1:752566-752566

# Filter summary stats to high-confidence variants genome-wide
bcftools filter \
    -i 'INFO/DR2 >= 0.3' \
    ofh_imputed_variant_summary_stats.v6.vcf.gz \
    -o high_conf_variants.vcf.gz -O z
```

***

## Part 6 — BEAGLE 5.4 Output VCF Fields (Upstream Context)

Since OFH imputation uses BEAGLE 5.4, understanding its native output fields clarifies what was available before the OFH pipeline post-processed and repackaged the files. BEAGLE 5.4 natively outputs:

| Field | Type | Description |
|---|---|---|
| `GT` | FORMAT | Hard-call genotype (thresholded from GP) |
| `GP` | FORMAT | Posterior genotype probabilities (3 values: P(RR), P(RA), P(AA)) |
| `DS` | FORMAT | Dosage = expected number of ALT alleles (= GP[RA] + 2×GP[AA]) |
| `AP1` | FORMAT | Posterior probability ALT allele on first haplotype |
| `AP2` | FORMAT | Posterior probability ALT allele on second haplotype |
| `DR2` | INFO | Dosage r²: imputation accuracy metric |
| `AF` | INFO | ALT allele frequency in the study sample |
| `IMP` | INFO | Flag indicating variant was imputed (not directly typed) |

OFH delivers `GT:GP` in the per-region pVCF files and moves the variant-level `DR2` and `AF` metrics to the separate summary stats VCF. Analysts requiring `DS` must compute it from `GP` as described in Part 2.3.[^1]

***

## Part 7 — Pydantic Schema Implications

Given the file structure above, the typed Python schema for a feasibility service should handle:

```python
from pydantic import BaseModel, Field
from enum import Enum
from typing import Optional

class GenomeBuild(str, Enum):
    GRCh38 = "GRCh38"

class DataSource(str, Enum):
    ARRAY_PVCF = "snv_pvcf"
    ARRAY_BGEN = "snv_bgen"
    IMPUTED_PVCF = "imputed_pvcf"
    IMPUTED_BGEN = "imputed_bgen"
    IMPUTED_SUMMARY = "imputed_resources"

class VariantSpec(BaseModel):
    chrom: str                        # e.g. "1", "X", "MT"
    pos: int                          # GRCh38 1-based
    ref: str
    alt: str
    genome_build: GenomeBuild = GenomeBuild.GRCh38
    cpra: str = Field(description="CHR:POS:REF:ALT string as used in VCF ID column")

class ImputedVariantSummary(BaseModel):
    cpra: str
    dr2: Optional[float] = None       # from ofh_imputed_variant_summary_stats
    af: Optional[float] = None        # ALT allele frequency
    prop_typed: Optional[float] = None  # proportion of groups with direct assay
    n_groups_imputed: Optional[int] = None
    n_groups_typed: Optional[int] = None
    pass_dr2_threshold: Optional[bool] = None  # DR2 >= 0.3

class RegionFile(BaseModel):
    file_id: str                      # DNAnexus file-XXXX
    file_name: str                    # e.g. ofh_imputed.v6.chr1-b0001.bgen
    chrom: str
    region_code: str                  # bXXXX
    data_source: DataSource
    release_version: str              # e.g. "v6"

class GenotypeCallSummary(BaseModel):
    cpra: str
    data_source: DataSource
    n_participants: int
    n_called: int
    n_missing: int
    n_hom_ref: int
    n_het: int
    n_hom_alt: int
    call_rate: float
    pass_qc: bool
```

The `ofh_imputed_variant_summary_stats.v6.vcf.gz` lookup maps directly onto `ImputedVariantSummary`. The `RegionFile` model provides the bridge between a CPRA query result and the actual file that needs to be staged for a SAK job.

***

## Part 8 — Known QC Issues and Caveats

### 8.1 Manifest A1 vs C2 (critical for longitudinal analysis)

All samples in Release 13 onward are called on the **C2 manifest**. Any analysis comparing pre-Release 13 results (A1-called) with current data must account for the manifest switch. The `manifest_version` column in `ofh_sample_qc_metrics.tsv` shows `v1` (A1) or `v2` (C2). From Release 13, all samples show `v2`.[^1]

### 8.2 1,407 Cryptically Related Samples

Release 13 flagged **1,407 participants** with an implausibly large number of third-degree or closer relatives in the dataset. These are identified in `ofh_snv_kinship.txt`. Any GWAS or carrier frequency analysis that assumes unrelated samples must filter these out or apply a mixed-model approach.[^1]

### 8.3 Array vs Imputed Coverage Gap

The ~700k array variants and the ~159.6 million imputed variants are not fully overlapping sets. A small proportion of array variants are absent from the imputed dataset because they failed imputation QC in all groups. These variants exist **only** in the array pVCF/BGEN and cannot be found via the imputed summary stats VCF. Any feasibility lookup must check both sources independently.[^1]

### 8.4 Participant Count Difference

The imputed dataset covers a subset of array participants (the ~550,000 / ~775,000 split is historical Release 13; Release 14 harmonises to ~755,000). Participants with array data who lack imputed data are identifiable by joining `ofh_sample_qc_metrics.tsv` against `ofh_imputed_sample_qc_metrics.v6.tsv` on participant ID.[^1]

### 8.5 Chromosome X Non-PAR Coverage

The 809 imputed region files cover chromosome X using the **non-PAR** region. Pseudoautosomal region (PAR1, PAR2) variants on chromosome X may be handled differently — verify against `ofh_imputed_regions.v6.bed` for exact coordinates.[^1]

***

## Part 9 — Useful External Links

| Resource | URL |
|---|---|
| OFH TRE documentation (DNAnexus) | https://dnanexus.gitbook.io/ofh |
| OFH researcher documentation (genotype array) | https://ourfuturehealth.gitbook.io/our-future-health/data-types/genetic-data/genotype-array-data |
| OFH researcher documentation (imputed data) | https://ourfuturehealth.gitbook.io/our-future-health/data-types/genetic-data/imputed-genotype-data |
| OFH TRE example notebooks (GitHub) | https://github.com/ourfuturehealth/tre-example-notebooks |
| OFHB1 notebook (Bash GWAS phenotype prep + SAK) | https://github.com/ourfuturehealth/tre-example-notebooks/blob/main/Bash%20Notebooks/OFHB1_Phenotype_Prep_for_GWAS_Bash.ipynb |
| OFHP1 notebook (Python GWAS phenotype prep) | https://github.com/ourfuturehealth/tre-example-notebooks/blob/main/Python%20Notebooks/OFHP1_Phenotype_Prep_for_GWAS_Python.ipynb |
| Swiss Army Knife app documentation | https://ourfuturehealth.dnanexus.com/app/swiss-army-knife |
| BGEN format specification | https://enkre.net/cgi-bin/code/bgen |
| BEAGLE 5.4 documentation | https://faculty.washington.edu/browning/beagle/beagle.html |
| UK Biobank BGEN sample file spec | https://biobank.ndph.ox.ac.uk/ukb/refer.cgi?id=531 |
| OFH researcher portal | https://research.ourfuturehealth.org.uk |
| Release 14 notes | https://ourfuturehealth.gitbook.io/our-future-health/data-releases/2026-data-releases/release-14 |
| Release 13 notes | https://ourfuturehealth.gitbook.io/our-future-health/data-releases/2025-data-releases/release-13 |

---

## References

1. [Genotype array data - Welcome | Our Future Health - GitBook](https://ourfuturehealth.gitbook.io/our-future-health/data/genotype-array-data) - The pVCF files are bgzip compressed and follow the standard VCF 4.1 file specification, with genotyp...

2. [: Resource 531 - UK Biobank](https://biobank.ndph.ox.ac.uk/ukb/refer.cgi?id=531) - The sample file lists the order of the samples in the .bgen files. The sample file includes the 'Sex...

***

## Appendix — TRE header checks (resolve the UNVERIFIABLE items once inside the TRE)

The mechanics below cannot be confirmed from public docs; resolve them by inspecting live file headers
and the data dictionary inside the TRE (Wave 9A). Until then they are explicit assumptions in this mock.

```bash
bcftools view -h ofh_snv.chrZ-bXXXX.vcf.gz | sed -n '1,80p'
bcftools view -h ofh_imputed.v6.chrZ-bXXXX.vcf.gz | sed -n '1,120p'
head -n 5 ofh_snv_regions.bed
head -n 5 ofh_imputed_regions.v6.bed
head -n 5 ofh_snv.chrZ-bXXXX.sample
head -n 5 ofh_imputed.v6.chrZ-bXXXX.sample
```

Questions to answer in the TRE:

- The exact `##reference` and `##contig` header lines (and whether contigs are `chr`-prefixed upstream).
- Which `FORMAT`/`INFO` fields are actually populated in one array pVCF and one imputed pVCF (e.g. is
  `DS` delivered, or only `GT:GP`? is `RAF` present?).
- The exact BED columns, and whether they include the `bXXXX` identifier and/or a variant count.
- The exact array region-splitting rule (the imputed processing split is 200 kb; the delivered array
  window size is not public).
- Whether imputed X non-PAR male genotypes are written as homozygous diploid, and whether phased (`|`).
- How array X PAR, Y, and MT genotypes are represented (and the known non-haploid-on-Y/MT issue →
  treat such calls as missing).
- The exact GRCh38 FASTA and whether `bcftools norm` left-alignment was explicitly applied.
- The BGEN genotype-block compression codec (zlib vs zstd), if discoverable from file metadata.
- The exact non-public TRE entity snake_case identifiers (some genetic entities are public; the
  linked-health identifiers are login-gated).
