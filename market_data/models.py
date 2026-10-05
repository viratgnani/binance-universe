"""
market_data/models.py

Typed Pydantic v2 data models for the Market Data Layer.

Design principles (same as universe/models.py):
  - Each model represents exactly one concept.
  - All monetary values in quote currency (USDT).
  - All timestamps are UTC-aware datetime objects.
  - None = missing; never use -1 or "" as sentinels.
  - Raw exchange fields are preserved — no silent lossy transforms.

Timestamp conventions
---------------------
Exchange (Binance):
  - kline open_time  : UTC milliseconds since epoch, aligned to interval boundary
  - kline close_time : UTC milliseconds since epoch = open_time + interval_ms - 1
  - aggTrade T       : UTC milliseconds since epoch, exact trade execution time

Internal (this layer):
  - All datetime fields use timezone.utc (tzinfo is never None).
  - Stored in JSONL as ISO-8601 with +00:00 suffix.
  - collection_time  : UTC wall-clock time of the API call (separate from event time).
"""

from __future__ import annotations

import enum
from datetime import datetime, timezone
from typing import Any

from pydantic import BaseModel, Field, field_validator, model_validator


# --------------------------------------------------------------------------- #
#  Enumerations
# --------------------------------------------------------------------------- #


class Dataset(str, enum.Enum):
    OHLCV = "ohlcv"
    TRADES = "trades"


class ViolationType(str, enum.Enum):
    DUPLICATE_CANDLE    = "DUPLICATE_CANDLE"
    MISSING_CANDLE      = "MISSING_CANDLE"
    OUT_OF_ORDER        = "OUT_OF_ORDER"
    INVALID_OHLC        = "INVALID_OHLC"
    INVALID_VOLUME      = "INVALID_VOLUME"
    TIMESTAMP_MISALIGN  = "TIMESTAMP_MISALIGN"
    DUPLICATE_TRADE     = "DUPLICATE_TRADE"
    INVALID_TRADE_PRICE = "INVALID_TRADE_PRICE"
    INVALID_TRADE_QTY   = "INVALID_TRADE_QTY"


# --------------------------------------------------------------------------- #
#  OHLCV — Candlestick
# --------------------------------------------------------------------------- #


class Candle(BaseModel):
    """
    A single OHLCV candlestick from Binance /fapi/v1/klines.

    All prices are in quote currency (USDT).
    volume is in base asset units; quote_volume is in USDT.
    """

    symbol: str
    interval: str

    # Candle boundaries — both UTC-aware
    open_time: datetime     # Start of interval (millisecond-aligned)
    close_time: datetime    # End of interval   (= open_time + interval_ms - 1ms)

    # OHLC prices
    open: float
    high: float
    low: float
    close: float

    # Volume metrics
    volume: float           # Base asset traded in this interval
    quote_volume: float     # USDT equivalent of all trades

    # Activity
    trade_count: int

    # Taker-side breakdown (preserved for future research; no signals built here)
    taker_buy_base_vol: float
    taker_buy_quote_vol: float

    # Metadata
    collection_time: datetime = Field(
        default_factory=lambda: datetime.now(tz=timezone.utc)
    )

    @field_validator("open_time", "close_time", "collection_time", mode="before")
    @classmethod
    def _ensure_utc(cls, v: Any) -> datetime:
        if isinstance(v, datetime):
            return v if v.tzinfo is not None else v.replace(tzinfo=timezone.utc)
        # Allow ISO strings (from JSONL deserialization)
        if isinstance(v, str):
            dt = datetime.fromisoformat(v.replace("Z", "+00:00"))
            return dt if dt.tzinfo is not None else dt.replace(tzinfo=timezone.utc)
        raise ValueError(f"Cannot parse datetime from {v!r}")

    model_config = {"frozen": False}


# --------------------------------------------------------------------------- #
#  Aggregate Trade
# --------------------------------------------------------------------------- #


class AggTrade(BaseModel):
    """
    A single aggregate trade from Binance /fapi/v1/aggTrades.

    Binance aggregates consecutive trades at the same price/direction into
    one record.  The raw 'm' (buyer_is_maker) field is preserved so future
    research can reconstruct trade direction without this layer.

    NOTE: Do NOT build CVD or order-flow signals here.  This model stores
    the raw exchange data only.
    """

    symbol: str
    agg_trade_id: int           # Binance field 'a' — unique per symbol

    price: float                # Binance field 'p'
    quantity: float             # Binance field 'q' — base asset
    quote_quantity: float       # price * quantity (derived — not a Binance field)

    first_trade_id: int         # Binance field 'f' — first raw trade in this agg
    last_trade_id: int          # Binance field 'l' — last raw trade in this agg

    timestamp: datetime         # Binance field 'T' — UTC trade execution time
    buyer_is_maker: bool        # Binance field 'm' — True = sell-side aggressor

    collection_time: datetime = Field(
        default_factory=lambda: datetime.now(tz=timezone.utc)
    )

    @field_validator("timestamp", "collection_time", mode="before")
    @classmethod
    def _ensure_utc(cls, v: Any) -> datetime:
        if isinstance(v, datetime):
            return v if v.tzinfo is not None else v.replace(tzinfo=timezone.utc)
        if isinstance(v, str):
            dt = datetime.fromisoformat(v.replace("Z", "+00:00"))
            return dt if dt.tzinfo is not None else dt.replace(tzinfo=timezone.utc)
        if isinstance(v, (int, float)):
            # Millisecond epoch
            return datetime.fromtimestamp(v / 1000.0, tz=timezone.utc)
        raise ValueError(f"Cannot parse datetime from {v!r}")

    model_config = {"frozen": False}


# --------------------------------------------------------------------------- #
#  Integrity
# --------------------------------------------------------------------------- #


class IntegrityViolation(BaseModel):
    """Describes a single data-quality problem detected by integrity.py."""

    symbol: str
    dataset: Dataset
    interval: str | None = None     # Set for OHLCV violations; None for trades
    violation_type: ViolationType
    detail: str                     # Human-readable explanation


# --------------------------------------------------------------------------- #
#  Collection errors
# --------------------------------------------------------------------------- #


class CollectionError(BaseModel):
    """Records a failure during backfill or update for a single symbol."""

    symbol: str
    dataset: Dataset
    interval: str | None = None
    error_message: str
    retryable: bool
    timestamp: datetime = Field(
        default_factory=lambda: datetime.now(tz=timezone.utc)
    )
    attempt: int = 1


# --------------------------------------------------------------------------- #
#  Backfill progress (written to disk for restart)
# --------------------------------------------------------------------------- #


class BackfillProgress(BaseModel):
    """
    Persisted per (symbol, interval) to allow restartable backfills.

    Written to: data/ohlcv/{SYMBOL}/{interval}/.backfill_progress.json
                data/trades/{SYMBOL}/.backfill_progress.json
    """

    symbol: str
    dataset: Dataset
    interval: str | None = None

    requested_start: datetime   # Original caller-specified start (UTC)
    requested_end: datetime     # Original caller-specified end (UTC)

    # After each successful batch, advance this cursor.
    # None means no batch has completed yet.
    last_completed_open_time: datetime | None = None

    is_complete: bool = False


# --------------------------------------------------------------------------- #
#  Collection summary
# --------------------------------------------------------------------------- #


class SymbolResult(BaseModel):
    """Per-symbol outcome within a CollectionSummary."""

    symbol: str
    success: bool
    records_written: int = 0
    records_skipped_duplicate: int = 0
    batches_fetched: int = 0
    violations: list[IntegrityViolation] = Field(default_factory=list)
    error: CollectionError | None = None


class CollectionSummary(BaseModel):
    """
    Aggregate result returned by backfill() and update().

    The data_quality_report field is populated by quality.py.
    """

    dataset: Dataset
    interval: str | None = None
    symbols_requested: int
    symbols_succeeded: int
    symbols_failed: int
    total_records_written: int
    total_records_skipped: int
    total_violations: int
    results: list[SymbolResult] = Field(default_factory=list)


# --------------------------------------------------------------------------- #
#  Data quality report
# --------------------------------------------------------------------------- #


class IntervalCoverage(BaseModel):
    """Per-symbol OHLCV coverage summary."""

    symbol: str
    interval: str
    start: datetime
    end: datetime
    expected_candles: int
    actual_candles: int
    missing_candles: int
    duplicate_candles: int
    invalid_ohlc: int
    out_of_order: int
    coverage_pct: float             # actual / expected * 100


class TradesCoverage(BaseModel):
    """Per-symbol trades coverage summary."""

    symbol: str
    start: datetime
    end: datetime
    actual_trades: int
    duplicate_trades: int
    invalid_trades: int


class QualityReport(BaseModel):
    """
    Comprehensive data-quality report for a time range and symbol set.

    Generated by quality.py; does not modify any stored data.
    """

    generated_at: datetime = Field(
        default_factory=lambda: datetime.now(tz=timezone.utc)
    )
    dataset: Dataset
    interval: str | None = None
    start: datetime
    end: datetime

    symbols_requested: list[str]
    symbols_with_data: list[str]
    symbols_missing: list[str]

    ohlcv_coverage: list[IntervalCoverage] = Field(default_factory=list)
    trades_coverage: list[TradesCoverage] = Field(default_factory=list)

    total_violations: int = 0
    all_violations: list[IntegrityViolation] = Field(default_factory=list)
