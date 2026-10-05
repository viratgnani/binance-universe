"""
research_discovery/models.py

Data models for the Market Behavior Discovery Laboratory.
These models sit entirely above the frozen infrastructure.
"""

from __future__ import annotations

import enum
from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field

from research.models import ResearchSpec


class DiscoveryFeatureRow(BaseModel):
    """
    A single row of discovery features for a given symbol and timestamp.
    Stored independently in data/discovery_features/.
    """
    symbol: str
    timestamp: datetime
    feature_version: str = "discovery_v1"

    # Price/Return Features
    return_1m: float | None = None
    return_3m: float | None = None
    return_5m: float | None = None
    return_10m: float | None = None
    return_15m: float | None = None
    return_30m: float | None = None
    return_1h: float | None = None
    absolute_return_1m: float | None = None
    absolute_return_5m: float | None = None
    absolute_return_15m: float | None = None

    # Range Features
    range_1m: float | None = None
    range_5m: float | None = None
    range_15m: float | None = None
    range_30m: float | None = None
    range_1h: float | None = None
    distance_from_high_24h: float | None = None
    distance_from_low_24h: float | None = None

    # Volatility Features
    volatility_5m: float | None = None
    volatility_15m: float | None = None
    volatility_30m: float | None = None
    volatility_1h: float | None = None
    volatility_pct_rank_1h: float | None = None

    # Volume Features
    volume_1m: float | None = None
    volume_5m: float | None = None
    volume_15m: float | None = None
    volume_30m: float | None = None
    volume_1h: float | None = None
    relative_volume_vs_1h: float | None = None
    volume_pct_rank_1h: float | None = None

    # Candle Structure Features
    body_pct: float | None = None
    upper_wick_pct: float | None = None
    lower_wick_pct: float | None = None
    close_location: float | None = None
    is_bullish: float | None = None
    is_bearish: float | None = None
    
    # Exposing the 1m close price for the outcome engine
    close: float | None = None


class ExperimentStatus(str, enum.Enum):
    REGISTERED = "REGISTERED"
    RUNNING = "RUNNING"
    COMPLETE = "COMPLETE"
    FAILED = "FAILED"


class DiscoverySpec(BaseModel):
    """
    A complete research specification wrapping the frozen ResearchSpec.
    Includes explicit metadata to guard against multiple-testing issues
    and document the experiment's intent.
    """
    experiment_id: str
    description: str
    universe_name: str
    universe_definition: str
    dataset_period: str
    is_exploratory: bool
    hypotheses_count: int
    methodology_version: str = "discovery_v1"
    
    research_spec: ResearchSpec


class ExperimentRegistryEntry(BaseModel):
    """
    A catalog entry for a registered experiment.
    """
    experiment_id: str
    status: ExperimentStatus
    created_at: datetime
    updated_at: datetime
    spec_summary: dict[str, Any]
