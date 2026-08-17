"""extract — pure builders for the metadata-first dataset slice.

No IO: takes already-loaded DataFrames (the shell reads them via io) and returns new values.
Covers stage 1 (variant validation), stage 2 (source decision) and the per-participant slice
that QC / classify operate on. Mirrors the proven reference flow, vectorised over pandas.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import numpy as np
import pandas as pd

if TYPE_CHECKING:  # type-only; the pure core never imports the config IO at runtime
    from .config import Config
    from .models import VariantRequest

# One row per participant for the requested variant (the slice QC/classify consume).
CANDIDATE_COLUMNS = (
    "participant_id",
    "pseudo_id",
    "consent_status",
    "sex",
    "ancestry_stub",
    "array_gt_code",
    "array_gq",
    "array_call_rate",
    "imputed_dosage",
    "imputed_max_gp",
    "sex_check_pass",
    "kinship_flag",
)


def _parse_optional_float(value) -> float | None:
    """Parse an optional manifest float (DR2, MAF, ...); 'NA'/blank/NaN -> None."""
    if value in (None, "", "NA") or (isinstance(value, float) and np.isnan(value)):
        return None
    return float(value)


def assert_unique_key(df: pd.DataFrame, key: str | tuple[str, ...], name: str) -> None:
    """Fail loudly on duplicate-like records at the input boundary (Wave 7).

    `key` is a column name or a tuple of column names. A live dispensed resource can carry
    duplicate registrations / re-genotyped rows; without this a downstream `iloc[0]` silently
    takes the first and a join fans out. Raises ValueError naming the offending key values.
    """
    cols = [key] if isinstance(key, str) else list(key)
    dup = df.duplicated(subset=cols, keep=False)
    if not dup.any():
        return
    offending = df.loc[dup, cols].drop_duplicates()
    keys = sorted(
        row[cols[0]] if len(cols) == 1 else tuple(row[c] for c in cols)
        for _, row in offending.iterrows()
    )
    raise ValueError(f"{name}: duplicate {'+'.join(cols)} key(s): {keys}")


def assert_join_cardinality(
    left: pd.DataFrame,
    key_left: str | tuple[str, ...],
    right: pd.DataFrame,
    key_right: str | tuple[str, ...],
    name: str,
) -> None:
    """Assert a left→right join is 1:1: the right key is unique and every left row matches.

    Catches both fan-out (duplicate right keys) and silent row loss (unmatched left rows).
    """
    lk = [key_left] if isinstance(key_left, str) else list(key_left)
    rk = [key_right] if isinstance(key_right, str) else list(key_right)
    assert_unique_key(right, key_right, f"{name} (right side)")
    merged = left[lk].merge(
        right[rk].assign(_match=1), left_on=lk, right_on=rk, how="left"
    )
    unmatched = merged["_match"].isna()
    if unmatched.any():
        miss = sorted(set(merged.loc[unmatched, lk[0]]))
        raise ValueError(
            f"{name}: {int(unmatched.sum())} left row(s) unmatched in join, e.g. {miss[:5]}"
        )


def validate_variant(manifest: pd.DataFrame, request: VariantRequest) -> dict:
    """Stage 1: confirm the requested CPRA is in the resource and consistent; return its row.

    Fails fast (ValueError) on absence or build/ref/alt mismatch — the 'identifiable' check
    against the *manifest*. Reference-genome match, normalization and strand resolution are a
    separate pre-flight: see normalize_and_reference_match.
    """
    assert_unique_key(manifest, "cpra", "variant_manifest")
    rows = manifest[manifest["cpra"] == request.cpra]
    if rows.empty:
        raise ValueError(f"variant {request.cpra} not in resource manifest — query the client")
    row = rows.iloc[0].to_dict()
    if row["build"] != request.build:
        raise ValueError(f"build mismatch: manifest {row['build']!r} vs request {request.build!r}")
    if row["ref"] != request.ref or row["alt"] != request.alt:
        raise ValueError(
            f"ref/alt orientation mismatch: manifest {row['ref']}/{row['alt']} "
            f"vs request {request.ref}/{request.alt}"
        )
    # CPRA-list intake flags (Wave 7): a known-unreliable variant is a fail-closed no-go, not a
    # normal count. .get() keeps the check tolerant of older inline manifests lacking the columns.
    if str(row.get("inaccurate_annotation", "FALSE")).upper() == "TRUE":
        raise ValueError(
            f"variant {request.cpra} is flagged inaccurate_annotation in the CPRA list — "
            f"no-go; query the client (annotation unreliable)"
        )
    if str(row.get("multiallelic_variant", "FALSE")).upper() == "TRUE":
        raise ValueError(
            f"variant {request.cpra} is flagged multiallelic in the CPRA list — no-go; query the "
            f"client (multiallelic locus: genotype ceiling/orientation unreliable)"
        )
    return row


def _truthy(value) -> bool:
    text = str(value).strip().upper()
    if text in {"TRUE", "T", "YES", "Y", "1"}:
        return True
    if text in {"FALSE", "F", "NO", "N", "0"}:
        return False
    raise ValueError(f"variant_identifiability boolean value not recognised: {value!r}")


def _manifest_flag(value) -> str:
    return "TRUE" if _truthy(value) else "FALSE"


def _requested_sources(request: VariantRequest) -> set[str]:
    if request.requested_source == "array":
        return {"array"}
    if request.requested_source == "imputed":
        return {"imputed"}
    if request.requested_source == "array_and_imputed":
        return {"array", "imputed"}
    raise ValueError(f"unknown requested_source {request.requested_source!r}")


def apply_identifiability_artifact(
    manifest: pd.DataFrame, identifiability: pd.DataFrame
) -> pd.DataFrame:
    """Overlay public-list-derived availability/reliability onto the runtime manifest.

    The synthetic manifest still carries DR2/MAF/cohort metadata. This overlay replaces only the
    resource-membership facts that can be grounded in public OFH CPRA lists.
    """
    assert_unique_key(manifest, "cpra", "variant_manifest")
    assert_unique_key(identifiability, "cpra", "variant_identifiability")
    out = manifest.copy()
    artifact = identifiability.set_index("cpra")
    matches = out["cpra"].isin(artifact.index)
    if not matches.any():
        return out

    cpras = out.loc[matches, "cpra"]
    out.loc[matches, "on_array"] = cpras.map(artifact["on_array"].map(_manifest_flag)).to_numpy()
    out.loc[matches, "on_imputed"] = cpras.map(
        artifact["on_imputed"].map(_manifest_flag)
    ).to_numpy()
    reliable = cpras.map(artifact["annotation_reliable"].map(_truthy))
    out.loc[matches, "inaccurate_annotation"] = np.where(reliable, "FALSE", "TRUE")
    return out


# Palindromic (strand-ambiguous) SNP allele pairs: strand cannot be resolved by complementation.
_PALINDROMES = ({"C", "G"}, {"A", "T"})
# AF concordance band: a palindromic SNP whose MAF sits within this of 0.5 (cohort or panel), or
# whose same-vs-flipped concordance is this close, is too common to orient by allele frequency.
_AF_AMBIGUITY_BAND = 0.05


def _normalize_alleles(pos: int, ref: str, alt: str) -> tuple[int, str, str]:
    """Parsimonious left-aligned normalization (bcftools-norm style); a no-op for a SNP.

    Trims a shared suffix, then a shared prefix (advancing pos), keeping >=1 base on each allele.
    Trivial for equal-length SNPs/MNPs; the indel case is where it does real work.
    """
    ref, alt = ref.upper(), alt.upper()
    while len(ref) > 1 and len(alt) > 1 and ref[-1] == alt[-1]:
        ref, alt = ref[:-1], alt[:-1]
    while len(ref) > 1 and len(alt) > 1 and ref[0] == alt[0]:
        ref, alt, pos = ref[1:], alt[1:], pos + 1
    return pos, ref, alt


def observed_maf(manifest_row: dict) -> float | None:
    """Cohort minor-allele frequency for strand concordance: prefer array, fall back to imputed."""
    for key in ("array_maf", "imputed_maf"):
        maf = _parse_optional_float(manifest_row.get(key))
        if maf is not None:
            return maf
    return None


def _ref_base(reference: dict, build: str, chrom: str, pos: int) -> str | None:
    return reference.get("bases", {}).get(build, {}).get(f"{chrom}:{pos}")


def _panel_maf(reference: dict, chrom: str, pos: int, ref: str, alt: str) -> float | None:
    return reference.get("panel_maf", {}).get(f"{chrom}:{pos}:{ref}:{alt}")


def _resolve_build(reference: dict, chrom: str, pos: int, ref: str, asserted: str):
    """Resolve/confirm the genome build by matching REF to the reference base.

    Returns (build, ref_matched, caveat). Raises ValueError when REF matches the GRCh37 base
    (client likely gave GRCh37 coords -> liftover/re-query) or no available reference base
    (mis-specified). Falls back to the asserted build with a caveat when the base is unavailable.
    """
    g38 = _ref_base(reference, "GRCh38", chrom, pos)
    g37 = _ref_base(reference, "GRCh37", chrom, pos)
    ref_anchor = ref[0]
    if g38 is not None and g38 == ref_anchor:
        return "GRCh38", True, (
            f"Client request is a CPRA ({chrom}:{pos}:...) with no explicit genome build; GRCh38 "
            f"confirmed by REF-to-reference match (REF {ref!r})."
        )
    if g37 is not None and g37 == ref_anchor:
        raise ValueError(
            f"build mismatch: REF {ref!r} at {chrom}:{pos} matches the GRCh37 reference base, not "
            f"GRCh38 — client likely supplied GRCh37 coordinates; liftover or re-query "
            f"(asserted {asserted})"
        )
    if g38 is None:
        return asserted, False, (
            f"Reference base for {chrom}:{pos} not in the mock reference; build {asserted} "
            f"asserted by CPRA convention, NOT reference-matched — verify against in-TRE FASTA."
        )
    raise ValueError(
        f"REF {ref!r} does not match the GRCh38 reference base {g38!r} at {chrom}:{pos} — "
        f"variant mis-specified (GRCh37 checked); query client"
    )


def _resolve_strand(observed: float | None, panel: float | None) -> str:
    """Resolve a palindromic SNP's strand by allele-frequency concordance; 'unresolved' if unclear.

    A rare variant whose cohort MAF concords with the reference-panel MAF is on the same strand; if
    it concords with (1 - panel) it is flipped. Near MAF 0.5 the two are indistinguishable.
    """
    if observed is None or panel is None:
        return "unresolved"
    if abs(observed - 0.5) < _AF_AMBIGUITY_BAND or abs(panel - 0.5) < _AF_AMBIGUITY_BAND:
        return "unresolved"
    same, flipped = abs(observed - panel), abs(observed - (1.0 - panel))
    if abs(same - flipped) < _AF_AMBIGUITY_BAND:
        return "unresolved"
    return "forward" if same <= flipped else "reverse"


def _strand_caveat(ref: str, alt: str, strand: str, observed, panel) -> str:
    if strand == "unresolved":
        return (
            f"{ref}/{alt} is a palindromic (strand-ambiguous) SNP and its strand could NOT be "
            f"resolved by allele-frequency concordance (cohort MAF {observed}, panel {panel}); "
            f"orientation is provisional — confirm against the array assay design before recall."
        )
    return (
        f"{ref}/{alt} is a palindromic SNP; strand resolved as {strand} by allele-frequency "
        f"concordance (cohort MAF {observed} concords with the reference panel {panel})."
    )


def normalize_and_reference_match(
    request: VariantRequest, reference: dict, observed: float | None = None
) -> dict:
    """Stage-1 pre-flight: reference-match the build, normalize alleles, resolve strand.

    The 'identifiable' feasibility check done properly. It (1) parsimoniously left-aligns the
    alleles, (2) confirms the genome build by matching REF to the reference base rather than
    trusting the asserted GRCh38, and (3) resolves strand for palindromic (C/G, A/T) SNPs via
    allele-frequency concordance. Fails closed (ValueError) on a wrong-build or mis-specified
    variant; returns an explicit ambiguity caveat (never a silent GRCh38 assumption) when a
    palindrome's strand cannot be resolved. `reference` is a mock stub here; in the TRE it is
    backed by the GRCh38/GRCh37 FASTA + a reference panel behind the same dict contract.
    """
    pos, ref, alt = _normalize_alleles(request.pos, request.ref, request.alt)
    normalized_cpra = f"{request.chrom}:{pos}:{ref}:{alt}"
    caveats: list[str] = []
    if normalized_cpra != request.cpra:
        caveats.append(
            f"Normalized {request.cpra} -> {normalized_cpra} (parsimonious left-aligned form)."
        )

    build, ref_matched, build_caveat = _resolve_build(
        reference, request.chrom, pos, ref, request.build
    )
    caveats.append(build_caveat)

    is_palindromic = {ref, alt} in _PALINDROMES
    strand = "n/a"
    ambiguous = False
    if is_palindromic:
        panel = _panel_maf(reference, request.chrom, pos, ref, alt)
        strand = _resolve_strand(observed, panel)
        ambiguous = strand == "unresolved"
        caveats.append(_strand_caveat(ref, alt, strand, observed, panel))

    return {
        "normalized_cpra": normalized_cpra,
        "build_resolved": build,
        "ref_matched": ref_matched,
        "is_palindromic": is_palindromic,
        "strand": strand,
        "ambiguous": ambiguous,
        "caveats": tuple(caveats),
    }


def requested_source_availability(manifest_row: dict, request: VariantRequest) -> dict:
    """Pre-flight: explicitly compare the requested evidence source(s) to resource membership."""
    requested = _requested_sources(request)
    on_array = _truthy(manifest_row.get("on_array", "FALSE"))
    on_imputed = _truthy(manifest_row.get("on_imputed", "FALSE"))
    array_requested = "array" in requested
    imputed_requested = "imputed" in requested
    array_ok = (not array_requested) or on_array
    imputed_ok = (not imputed_requested) or on_imputed
    caveats: list[str] = []

    if array_requested:
        if not on_array:
            caveats.append(
                "Requested source includes array, but the exact CPRA is absent from the array "
                "resource; array-direct evidence is unavailable for this request."
            )
    if imputed_requested:
        if not on_imputed:
            caveats.append(
                "Requested source includes imputed, but the exact CPRA is absent from the imputed "
                "resource; imputed evidence is unavailable for this request."
            )

    return {
        "requested_source": request.requested_source,
        "requested_array": array_requested,
        "requested_imputed": imputed_requested,
        "array_available": on_array,
        "imputed_available": on_imputed,
        "array_requested_available": array_ok,
        "imputed_requested_available": imputed_ok,
        "requested_sources_available": array_ok and imputed_ok,
        "source_caveats": tuple(caveats),
    }


def attach_source_availability(
    preflight: dict, manifest_row: dict, request: VariantRequest
) -> dict:
    """Attach requested-source availability to the variant pre-flight artefact."""
    availability = requested_source_availability(manifest_row, request)
    return {
        **preflight,
        **availability,
    }


def resolve_sources(manifest_row: dict, request: VariantRequest, cfg: Config) -> dict:
    """Stage 2: decide which sources to use, plus the variant DR2 and its confidence tier."""
    info = _parse_optional_float(manifest_row.get("dosage_r2"))
    use_array = manifest_row["on_array"] == "TRUE" and "array" in request.requested_source
    use_imputed = (
        manifest_row["on_imputed"] == "TRUE"
        and "imputed" in request.requested_source
        and info is not None
        and info >= cfg.imputed_dr2_min
    )
    imp_high = info is not None and info >= cfg.imputed_dr2_high_confidence
    return {
        "variant_info": info,
        "use_array": use_array,
        "use_imputed": use_imputed,
        "imp_high": imp_high,
        "variant_on_array": manifest_row["on_array"] == "TRUE",  # array-direct evidence available
        "variant_on_imputed": manifest_row["on_imputed"] == "TRUE",
        "annotation_reliable": str(
            manifest_row.get("inaccurate_annotation", "FALSE")
        ).upper() != "TRUE",
    }


def build_candidate_table(
    request: VariantRequest,
    participants: pd.DataFrame,
    genotype_slice: pd.DataFrame,
    sample_qc: pd.DataFrame,
) -> pd.DataFrame:
    """Pivot the long genotype slice to one row per participant and join consent + sample flags.

    Returns the per-participant slice for the requested variant (array evidence + imputed
    evidence + consent + sample flags). Candidate selection (which rows show alt evidence) and
    the consent/QC decision happen downstream in classify, where cfg + variant DR2 are in scope.
    """
    # input-integrity guards (Wave 7): both orchestration modes funnel through here, so a
    # duplicate participant / sample-QC / genotype row fails loudly before the pivot + joins.
    assert_unique_key(participants, "participant_id", "participant_table")
    assert_unique_key(sample_qc, "participant_id", "sample_qc")
    assert_unique_key(genotype_slice, ("participant_id", "cpra", "source"), "genotype_slice")
    assert_join_cardinality(
        participants, "participant_id", sample_qc, "participant_id", "participant->sample_qc"
    )
    gs = genotype_slice[genotype_slice["cpra"] == request.cpra]
    array = gs[gs["source"] == "array"][["participant_id", "gt_code", "gq", "call_rate"]].rename(
        columns={"gt_code": "array_gt_code", "gq": "array_gq", "call_rate": "array_call_rate"}
    )
    imputed = gs[gs["source"] == "imputed"][["participant_id", "dosage", "max_gp"]].rename(
        columns={"dosage": "imputed_dosage", "max_gp": "imputed_max_gp"}
    )
    base = participants[["participant_id", "pseudo_id", "consent_status", "sex", "ancestry_stub"]]
    flags = sample_qc[["participant_id", "sex_check_pass", "kinship_flag"]]
    candidate = (
        base.merge(array, on="participant_id", how="left")
        .merge(imputed, on="participant_id", how="left")
        .merge(flags, on="participant_id", how="left")
    )
    return candidate.reset_index(drop=True)


def to_genotype_array(candidate: pd.DataFrame, source: str) -> np.ndarray:
    """Project one source to a numeric array for the kernel: int8 hardcalls or float dosage."""
    if source == "array":
        return candidate["array_gt_code"].fillna(-1).to_numpy(dtype=np.int8)
    if source == "imputed":
        return candidate["imputed_dosage"].fillna(0.0).to_numpy(dtype=np.float64)
    raise ValueError(f"unknown source {source!r}")
