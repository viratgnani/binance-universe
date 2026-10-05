"""
market_data/__init__.py

Public API of the Market Data Layer V1.

Exports the most commonly needed names so callers can write:

    from market_data import backfill_ohlcv, update_ohlcv, MarketDataClient
"""

from __future__ import annotations

from market_data.backfill import backfill_ohlcv, backfill_trades
from market_data.client import MarketDataAPIError, MarketDataClient, parse_klines, parse_agg_trades
from market_data.config import MarketDataConfig, config
from market_data.integrity import (
    run_all_candle_checks,
    run_all_trade_checks,
)
from market_data.models import (
    AggTrade,
    BackfillProgress,
    Candle,
    CollectionError,
    CollectionSummary,
    Dataset,
    IntegrityViolation,
    IntervalCoverage,
    QualityReport,
    SymbolResult,
    TradesCoverage,
    ViolationType,
)
from market_data.ohlcv_store import OHLCVStore
from market_data.quality import generate_ohlcv_report, generate_trades_report
from market_data.trades_store import TradesStore
from market_data.update import update_ohlcv, update_trades

__all__ = [
    # Config
    "MarketDataConfig",
    "config",
    # Client
    "MarketDataClient",
    "MarketDataAPIError",
    "parse_klines",
    "parse_agg_trades",
    # Models
    "Candle",
    "AggTrade",
    "IntegrityViolation",
    "CollectionError",
    "BackfillProgress",
    "SymbolResult",
    "CollectionSummary",
    "IntervalCoverage",
    "TradesCoverage",
    "QualityReport",
    "Dataset",
    "ViolationType",
    # Storage
    "OHLCVStore",
    "TradesStore",
    # Integrity
    "run_all_candle_checks",
    "run_all_trade_checks",
    # Backfill & update
    "backfill_ohlcv",
    "backfill_trades",
    "update_ohlcv",
    "update_trades",
    # Quality
    "generate_ohlcv_report",
    "generate_trades_report",
]
