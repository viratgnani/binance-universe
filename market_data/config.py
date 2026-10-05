"""
market_data/config.py

Single source of truth for all Market Data Layer configuration.

Kept separate from universe/config.py so the two packages remain
independently deployable and testable.
"""

from __future__ import annotations

from pathlib import Path


class MarketDataConfig:
    # ------------------------------------------------------------------ #
    #  Binance API
    # ------------------------------------------------------------------ #

    BINANCE_FAPI_BASE_URL: str = "https://fapi.binance.com"

    # Seconds before an individual HTTP request is timed out.
    REQUEST_TIMEOUT_SECONDS: float = 15.0

    # ------------------------------------------------------------------ #
    #  Pagination limits
    #
    #  Binance USDS-M Futures:
    #    /fapi/v1/klines    — max 1500 candles per request
    #    /fapi/v1/aggTrades — max 1000 trades per request
    # ------------------------------------------------------------------ #

    KLINES_LIMIT: int = 1500
    AGTRADES_LIMIT: int = 1000

    # Maximum 48-hour lookback window for aggTrades when using startTime/endTime.
    # Older history requires the async export endpoints (not in V1 scope).
    AGTRADES_MAX_LOOKBACK_HOURS: int = 48

    # ------------------------------------------------------------------ #
    #  Concurrency and retry
    # ------------------------------------------------------------------ #

    # Max simultaneous in-flight Binance requests across all symbols.
    MAX_CONCURRENT_REQUESTS: int = 5

    # Max retry attempts for transient failures (timeouts, 429, 5xx).
    RETRY_MAX_ATTEMPTS: int = 3

    # Base backoff in seconds; doubled each attempt (1s, 2s, 4s).
    RETRY_BACKOFF_BASE: float = 1.0

    # ------------------------------------------------------------------ #
    #  Supported intervals
    # ------------------------------------------------------------------ #

    SUPPORTED_INTERVALS: frozenset[str] = frozenset(
        {"1m", "5m", "15m", "1h", "4h", "1d"}
    )

    # Mapping from interval string → duration in milliseconds.
    # Used for gap detection and batch-size calculations.
    INTERVAL_MS: dict[str, int] = {
        "1m":  60_000,
        "5m":  300_000,
        "15m": 900_000,
        "1h":  3_600_000,
        "4h":  14_400_000,
        "1d":  86_400_000,
    }

    # ------------------------------------------------------------------ #
    #  Storage directories
    # ------------------------------------------------------------------ #

    # data/ohlcv/{SYMBOL}/{interval}/{YYYYMMDD}.jsonl
    OHLCV_DIR: Path = Path("data/ohlcv")

    # data/trades/{SYMBOL}/{YYYYMMDD}.jsonl
    TRADES_DIR: Path = Path("data/trades")

    # ------------------------------------------------------------------ #
    #  Logging
    # ------------------------------------------------------------------ #

    LOG_PROGRESS_EVERY_N_BATCHES: int = 10


# Module-level singleton — import this instead of constructing a new object.
config = MarketDataConfig()
