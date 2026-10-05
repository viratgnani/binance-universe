"""
research_features/models.py

Data models for the Research Feature Layer V1.
"""

from __future__ import annotations

from datetime import datetime
from pydantic import BaseModel, Field


class FeatureMetadata(BaseModel):
    name: str
    version: str
    description: str
    source_dataset: str
    lookback: str
    timestamp_semantics: str
    missing_data_policy: str


class FeatureRow(BaseModel):
    """
    A single timestamped feature observation for a symbol.
    
    A FeatureRow at time T represents facts available at precisely T.
    No future data (data with a timestamp > T) may be used to calculate these features.
    """
    symbol: str = Field(..., description="The contract symbol (e.g., BTCUSDT)")
    timestamp: datetime = Field(..., description="The latest point in time at which all information used to calculate the row was known")
    feature_version: str = Field("v1", description="Version of the feature schema and calculation logic")
    
    # ------------------------------------------------------------------ #
    # Price / Return Features
    # ------------------------------------------------------------------ #
    return_1m: float | None = None
    return_5m: float | None = None
    return_15m: float | None = None
    return_1h: float | None = None

    # ------------------------------------------------------------------ #
    # Volatility / Range Features
    # ------------------------------------------------------------------ #
    volatility_5m: float | None = None
    volatility_15m: float | None = None
    volatility_1h: float | None = None
    range_pct: float | None = Field(None, description="(high - low) / close over the current candle")

    # ------------------------------------------------------------------ #
    # Volume Features
    # ------------------------------------------------------------------ #
    volume_1m: float | None = None
    volume_5m: float | None = None
    volume_15m: float | None = None
    volume_1h: float | None = None
    relative_volume: float | None = Field(None, description="current volume / historical rolling mean")

    # ------------------------------------------------------------------ #
    # Trade-Derived Features
    # ------------------------------------------------------------------ #
    trade_count: int | None = None
    total_trade_volume: float | None = None
    total_trade_quote_volume: float | None = None
    average_trade_size: float | None = None
    median_trade_size: float | None = None

    # ------------------------------------------------------------------ #
    # Order-Book Features
    # ------------------------------------------------------------------ #
    spread: float | None = None
    spread_bps: float | None = None
    best_bid: float | None = None
    best_ask: float | None = None
    mid_price: float | None = None

    # Depth
    bid_depth_5: float | None = None
    ask_depth_5: float | None = None
    bid_depth_10: float | None = None
    ask_depth_10: float | None = None
    bid_depth_20: float | None = None
    ask_depth_20: float | None = None

    # Imbalance: (bid_depth - ask_depth) / (bid_depth + ask_depth)
    depth_imbalance_5: float | None = None
    depth_imbalance_10: float | None = None
    depth_imbalance_20: float | None = None
