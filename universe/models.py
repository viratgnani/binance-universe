"""
universe/models.py

Typed Pydantic v2 data models for every stage of the universe pipeline.

Design principles:
  - Each model represents exactly one stage/concept.
  - Fields are explicitly typed so downstream code can rely on them.
  - Optional fields use None as sentinel — never use -1 or "" as missing.
  - The schema is intentionally minimal for V1; new fields should be added
    here when future research modules require them.
"""

from __future__ import annotations

import enum
from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field, model_validator


# --------------------------------------------------------------------------- #
#  Enumerations
# --------------------------------------------------------------------------- #


class UniverseStatus(str, enum.Enum):
    """Membership tier within the master universe."""

    ACTIVE_TOP_100 = "ACTIVE_TOP_100"
    WATCHLIST = "WATCHLIST"


# --------------------------------------------------------------------------- #
#  Stage 1 — Exchange metadata (raw Binance response)
# --------------------------------------------------------------------------- #


class ContractInfo(BaseModel):
    """
    Normalised representation of a single symbol from Binance
    GET /fapi/v1/exchangeInfo.

    Only the fields required for eligibility filtering and data-model
    population are retained; the full raw dict is kept separately for
    debugging if needed.
    """

    symbol: str
    base_asset: str
    quote_asset: str
    margin_asset: str
    contract_type: str          # "PERPETUAL", "CURRENT_QUARTER", etc.
    status: str                 # "TRADING", "SETTLING", "CLOSE", etc.
    listing_time: datetime | None = None

    # Binance category metadata — used for TradFi filtering.
    # These fields may be absent on older contract records.
    underlying_type: str | None = None          # "COIN", "INDEX", etc.
    underlying_sub_type: list[str] = Field(default_factory=list)

    # Keep the original raw dict so the filter layer can inspect unexpected
    # fields without requiring a model schema change.
    raw: dict[str, Any] = Field(default_factory=dict, exclude=True)

    model_config = {"populate_by_name": True}


# --------------------------------------------------------------------------- #
#  Stage 2 — Raw market metrics
# --------------------------------------------------------------------------- #


class MarketMetrics(BaseModel):
    """
    Raw (un-normalised) market quality metrics for a single contract.

    All monetary values are in the contract's quote currency (USDT by default).
    None signals that the metric could not be retrieved; such contracts are
    excluded from ranking but remain in the master universe as WATCHLIST.
    """

    symbol: str

    # 24-hour rolling statistics
    volume_24h_quote: float | None = None   # Total traded notional (quote units)
    volume_24h_base: float | None = None    # Total traded quantity (base units)
    last_price: float | None = None

    # Best bid / ask from the latest order book snapshot
    bid_price: float | None = None
    ask_price: float | None = None

    # Derived spread metric (calculated after collection)
    spread_bps: float | None = None         # (ask - bid) / last_price * 10_000

    # Open interest (in base asset units)
    open_interest: float | None = None

    # True if any API call for this symbol raised an exception.
    metrics_failed: bool = False
    failure_reason: str | None = None

    @model_validator(mode="after")
    def _compute_spread(self) -> "MarketMetrics":
        """Derive spread_bps from bid/ask/last if all three are present."""
        if (
            self.spread_bps is None
            and self.bid_price is not None
            and self.ask_price is not None
            and self.last_price is not None
            and self.last_price > 0
        ):
            self.spread_bps = (self.ask_price - self.bid_price) / self.last_price * 10_000
        return self


# --------------------------------------------------------------------------- #
#  Stage 3 — Normalised metrics (input to ranking engine)
# --------------------------------------------------------------------------- #


class NormalizedMetrics(BaseModel):
    """
    Min-max-normalised [0, 1] versions of the ranking-relevant raw metrics.

    Produced by normalization.py from a batch of MarketMetrics objects.
    """

    symbol: str
    norm_volume: float      # Higher = more liquid by volume
    norm_oi: float          # Higher = more open interest
    norm_spread: float      # Higher = tighter spread (already inverted)


# --------------------------------------------------------------------------- #
#  Stage 4 — Ranking output
# --------------------------------------------------------------------------- #


class RankResult(BaseModel):
    """Output of the ranking engine for a single contract."""

    symbol: str
    score: float            # Composite score in [0, 1]
    rank: int               # 1-indexed; rank 1 = highest quality


# --------------------------------------------------------------------------- #
#  Stage 5 — Full universe member (master universe record)
# --------------------------------------------------------------------------- #


class UniverseMember(BaseModel):
    """
    Complete record for a contract in the master universe.

    Merges ContractInfo + MarketMetrics + RankResult into a single document.
    Future research fields (funding rate, OI change, volatility, etc.) should
    be added here as Optional fields with default=None.
    """

    # Identity
    symbol: str
    base_asset: str
    quote_asset: str
    margin_asset: str
    contract_type: str
    status: str
    listing_time: datetime | None = None

    # Ranking
    rank: int | None = None
    universe_score: float | None = None
    universe_status: UniverseStatus | None = None

    # Raw market metrics
    volume_24h_quote: float | None = None
    volume_24h_base: float | None = None
    last_price: float | None = None
    bid_price: float | None = None
    ask_price: float | None = None
    spread_bps: float | None = None
    open_interest: float | None = None

    # Metadata
    metrics_failed: bool = False
    last_updated: datetime = Field(default_factory=datetime.utcnow)


# --------------------------------------------------------------------------- #
#  Stage 6 — Snapshot record (persisted to JSONL)
# --------------------------------------------------------------------------- #


class SnapshotRecord(BaseModel):
    """
    Slim per-symbol record written to the daily snapshot file.

    Intentionally minimal — only the fields needed to reconstruct
    rank history and Top-100 membership changes.
    """

    snapshot_timestamp: datetime
    snapshot_id: str            # ISO-format timestamp of the refresh run
    symbol: str
    rank: int | None = None
    score: float | None = None
    universe_status: UniverseStatus | None = None
    volume_24h_quote: float | None = None
    open_interest: float | None = None
    spread_bps: float | None = None
    metrics_failed: bool = False


class SnapshotHeader(BaseModel):
    """
    One header line written at the start of each refresh batch in the JSONL file.
    Allows consumers to group records by refresh run without scanning all records.
    """

    record_type: str = "HEADER"
    snapshot_id: str
    snapshot_timestamp: datetime
    total_eligible: int
    total_ranked: int
    total_failed: int
    top_n: int
