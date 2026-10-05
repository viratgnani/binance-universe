"""
indicators/models.py

Strongly-typed Pydantic models for Research Indicator Layer V1.

Model Hierarchy
---------------
  IndicatorDefinition   — what indicator to calculate and with what parameters
  IndicatorValue        — one timestamped indicator observation for one symbol
  IndicatorSeries       — an ordered series of IndicatorValues for one symbol
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# IndicatorDefinition
# ---------------------------------------------------------------------------

class IndicatorDefinition(BaseModel):
    """
    Complete, serializable specification of one indicator calculation.

    The parameter_hash() method produces a deterministic SHA-256 prefix
    that uniquely identifies this definition's parameters. This is used
    as part of the idempotency key so that RSI(14) and RSI(7) are stored
    as distinct series.

    Timestamp semantics
    -------------------
    For a candle-based input (e.g. 1-minute OHLCV/features):
      IndicatorValue.timestamp == candle close timestamp.
      All price information at or before that timestamp was used.
      No future price is ever accessed.

    Missing data policy
    -------------------
    "skip_missing": bars where the input_feature is null are excluded from
    the calculation. The warm-up period counts only non-null observations.
    No interpolation, no backfill, no forward-fill.
    """

    indicator_name: str = Field(..., description="e.g. 'rsi'")
    indicator_version: str = Field("v1", description="Calculator version")
    input_feature: str = Field(
        "mid_price",
        description="FeatureRow field used as the price input (e.g. 'mid_price')",
    )
    parameters: dict[str, Any] = Field(
        default_factory=dict,
        description="Indicator-specific parameters (e.g. {'period': 14})",
    )
    timestamp_semantics: str = Field(
        "candle_close",
        description=(
            "Describes what the timestamp of an IndicatorValue represents. "
            "'candle_close' means all information at or before that timestamp was used."
        ),
    )
    missing_data_policy: str = Field(
        "skip_missing",
        description=(
            "How to handle null/invalid input values. "
            "'skip_missing' excludes the bar from calculation without interpolation."
        ),
    )

    def parameter_hash(self) -> str:
        """
        Deterministic 16-character SHA-256 prefix of parameters + indicator identity.
        Used as part of the idempotency key — different parameter sets produce
        different hashes and are stored separately.
        """
        payload = json.dumps(
            {
                "indicator_name": self.indicator_name,
                "indicator_version": self.indicator_version,
                "input_feature": self.input_feature,
                "parameters": self.parameters,
            },
            sort_keys=True,
        )
        return hashlib.sha256(payload.encode()).hexdigest()[:16]


# ---------------------------------------------------------------------------
# IndicatorValue
# ---------------------------------------------------------------------------

class IndicatorValue(BaseModel):
    """
    A single timestamped indicator observation for one symbol.

    The timestamp is the information-state timestamp: all prices used in
    the calculation have timestamp <= this value. No future data was accessed.

    value is None when:
      - insufficient history exists to initialise the indicator (warm-up period)
      - the input price at this bar was invalid (null, NaN, Inf, <=0)
    """

    symbol: str
    timestamp: datetime = Field(
        ...,
        description="The candle-close timestamp at which this indicator became observable",
    )
    indicator_name: str
    indicator_version: str
    parameter_hash: str = Field(
        ...,
        description="Deterministic hash of the IndicatorDefinition parameters",
    )
    input_feature: str = Field(
        ...,
        description="FeatureRow field used as input (e.g. 'mid_price')",
    )
    value: float | None = Field(
        None,
        description="The indicator value; None during warm-up or for invalid input bars",
    )

    def logical_key(self) -> tuple:
        """
        Idempotency key for storage.
        RSI(14) and RSI(7) produce different parameter_hash values and are stored separately.
        """
        return (
            self.symbol,
            self.timestamp,
            self.indicator_name,
            self.indicator_version,
            self.parameter_hash,
        )


# ---------------------------------------------------------------------------
# IndicatorSeries
# ---------------------------------------------------------------------------

class IndicatorSeries(BaseModel):
    """
    An ordered series of IndicatorValues for one symbol.
    Values are sorted by timestamp ascending.
    """

    symbol: str
    definition: IndicatorDefinition
    start: datetime | None = None
    end: datetime | None = None
    values: list[IndicatorValue] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)

    @property
    def valid_count(self) -> int:
        """Number of observations with non-None values."""
        return sum(1 for v in self.values if v.value is not None)

    @property
    def warmup_count(self) -> int:
        """Number of observations with None values (warm-up or missing input)."""
        return sum(1 for v in self.values if v.value is None)
