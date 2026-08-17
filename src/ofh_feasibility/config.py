"""Config: a pydantic model + an IO loader. Fail-fast on an invalid config."""
from __future__ import annotations

from pathlib import Path
from typing import Any, ClassVar, Literal

import yaml
from pydantic import BaseModel, ConfigDict, field_validator, model_validator


class Config(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    _MIN_SDC_CELL: ClassVar[int] = 5

    array_call_rate_min: float
    array_gq_min: int
    imputed_dr2_min: float
    imputed_dr2_high_confidence: float
    imputed_dosage_carrier_threshold: float
    imputed_max_gp_min: float
    carrier_definition: Literal["het_and_homalt", "het_only"]
    require_consent: bool
    sdc_min_cell: int
    sdc_round_to: int
    data_dir: str
    results_dir: str
    # Optional request-file override for run matrices (e.g. BAG3 vs CHEK2) without mutating
    # data_dir/variant_request.csv. Snakemake passes this via --config request_path=...
    request_path: str | None = None
    # Optional small, committed artifact derived from public CPRA lists. It grounds variant
    # identifiability without shipping raw list files.
    variant_identifiability_path: str | None = None
    # Optional variant/gene/panel catalogue for gene/disease requests.
    variant_catalog_path: str = "configs/catalogs/demo_variant_catalog.yaml"
    # input format (Wave 9): 'simplified' = CSV/Parquet stand-ins; 'ofh_tre' =
    # real-named pVCF + summary-stats VCF + sample-QC TSV. Default keeps existing runs.
    source_format: Literal["simplified", "ofh_tre"] = "simplified"

    @model_validator(mode="before")
    @classmethod
    def _normalise_dr2_aliases(cls, data: Any) -> Any:
        """Accept the historical imputed_info_* keys while making DR2 names canonical."""
        if not isinstance(data, dict):
            return data
        out = dict(data)
        aliases = {
            "imputed_info_min": "imputed_dr2_min",
            "imputed_info_high_confidence": "imputed_dr2_high_confidence",
        }
        for old, new in aliases.items():
            if old not in out:
                continue
            if new in out and out[new] != out[old]:
                raise ValueError(f"config sets both {old!r} and {new!r} with different values")
            out.setdefault(new, out[old])
            del out[old]
        return out

    @property
    def imputed_info_min(self) -> float:
        """Backward-compatible alias for configs/tests that still use the old INFO wording."""
        return self.imputed_dr2_min

    @property
    def imputed_info_high_confidence(self) -> float:
        """Backward-compatible alias for configs/tests that still use the old INFO wording."""
        return self.imputed_dr2_high_confidence

    @field_validator("require_consent")
    @classmethod
    def _consent_is_non_negotiable(cls, v: bool) -> bool:
        # The consent gate is a hard governance control; it cannot be disabled.
        if v is not True:
            raise ValueError("require_consent must be true — the consent gate is non-negotiable")
        return v

    @field_validator(
        "array_call_rate_min",
        "imputed_dr2_min",
        "imputed_dr2_high_confidence",
        "imputed_max_gp_min",
    )
    @classmethod
    def _probability_threshold_is_unit_interval(cls, v: float) -> float:
        if not 0 <= v <= 1:
            raise ValueError("probability / quality thresholds must be between 0 and 1")
        return v

    @field_validator("imputed_dosage_carrier_threshold")
    @classmethod
    def _dosage_threshold_is_plausible(cls, v: float) -> float:
        if not 0 <= v <= 2:
            raise ValueError("imputed_dosage_carrier_threshold must be between 0 and 2")
        return v

    @field_validator("array_gq_min")
    @classmethod
    def _gq_is_non_negative(cls, v: int) -> int:
        if v < 0:
            raise ValueError("array_gq_min must be non-negative")
        return v

    @model_validator(mode="after")
    def _config_invariants(self) -> Config:
        if self.sdc_min_cell < self._MIN_SDC_CELL:
            raise ValueError(
                f"sdc_min_cell must be >= {self._MIN_SDC_CELL} to suppress small cells"
            )
        if self.imputed_dr2_high_confidence < self.imputed_dr2_min:
            raise ValueError(
                "imputed_dr2_high_confidence must be >= imputed_dr2_min"
            )
        # round base must divide the min cell, so rounding a released count can never cross below
        # the suppression threshold (the disclosure-control invariant that's easy to get wrong).
        if self.sdc_round_to <= 0 or self.sdc_min_cell % self.sdc_round_to != 0:
            raise ValueError(
                f"sdc_round_to ({self.sdc_round_to}) must be a positive divisor of "
                f"sdc_min_cell ({self.sdc_min_cell})"
            )
        return self

    @classmethod
    def from_dict(cls, data: dict) -> Config:
        return cls.model_validate(data or {})


def load_config(path: str | Path) -> Config:
    with open(path) as fh:
        data = yaml.safe_load(fh)
    return Config.from_dict(data or {})
