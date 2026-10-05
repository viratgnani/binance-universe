"""
market_data/update.py

Incremental updater — fetches only the gap between the last stored
candle/trade and now.

Design:
  - Reads the latest stored record for each (symbol, interval).
  - Fetches only the range [last_open_time + 1 interval, now].
  - Uses the same backfill machinery under the hood.
  - Idempotent: if called again within the same interval window, dedup
    on write prevents any duplicates.

Unlike backfill, update does not write progress files — it always checks
the store directly for the freshest record.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone, timedelta

from market_data.backfill import (
    _backfill_symbol_ohlcv,
    _backfill_symbol_trades,
)
from market_data.client import MarketDataClient
from market_data.config import MarketDataConfig, config as default_config
from market_data.models import (
    CollectionSummary,
    Dataset,
    SymbolResult,
)
from market_data.ohlcv_store import OHLCVStore
from market_data.trades_store import TradesStore

logger = logging.getLogger(__name__)


async def update_ohlcv(
    symbols: list[str],
    interval: str,
    cfg: MarketDataConfig = default_config,
    as_of: datetime | None = None,
) -> CollectionSummary:
    """
    Fetch OHLCV candles that have appeared since the last stored candle.

    For each symbol:
      1. Find the latest stored open_time.
      2. If none, raise ValueError — use backfill for first-time collection.
      3. Fetch [latest + 1 interval, now).

    Parameters
    ----------
    symbols:
        Symbols to update.
    interval:
        Candlestick interval.
    cfg:
        Configuration.
    as_of:
        Reference "now" (UTC).  Defaults to datetime.now(utc).  Useful for
        testing with a fixed reference time.

    Returns
    -------
    CollectionSummary with per-symbol results.
    """
    if interval not in cfg.SUPPORTED_INTERVALS:
        raise ValueError(f"Unsupported interval '{interval}'")

    now = (as_of or datetime.now(tz=timezone.utc)).astimezone(timezone.utc)
    step = timedelta(milliseconds=cfg.INTERVAL_MS[interval])
    store = OHLCVStore(cfg)
    results: list[SymbolResult] = []

    async with MarketDataClient(cfg) as client:
        sem = asyncio.Semaphore(cfg.MAX_CONCURRENT_REQUESTS)

        async def _update_one(symbol: str) -> SymbolResult:
            async with sem:
                latest = store.get_latest(symbol, interval)
                if latest is None:
                    logger.warning(
                        "update_ohlcv: %s %s — no stored data; run backfill first",
                        symbol, interval,
                    )
                    return SymbolResult(
                        symbol=symbol,
                        success=False,
                        error=None,  # Not an API error; a usage error
                        records_written=0,
                    )

                # Start one interval after the last complete candle
                update_start = latest.open_time + step
                if update_start >= now:
                    logger.debug(
                        "update_ohlcv: %s %s — already up to date (latest=%s)",
                        symbol, interval, latest.open_time.isoformat(),
                    )
                    return SymbolResult(symbol=symbol, success=True, records_written=0)

                logger.info(
                    "update_ohlcv: %s %s — fetching gap [%s, %s]",
                    symbol, interval,
                    update_start.isoformat(),
                    now.isoformat(),
                )

                return await _backfill_symbol_ohlcv(
                    symbol=symbol,
                    interval=interval,
                    start_utc=update_start,
                    end_utc=now,
                    step_ms=cfg.INTERVAL_MS[interval],
                    client=client,
                    store=store,
                    cfg=cfg,
                )

        results = list(await asyncio.gather(*[_update_one(s) for s in symbols]))

    succeeded = [r for r in results if r.success]
    failed    = [r for r in results if not r.success]

    return CollectionSummary(
        dataset=Dataset.OHLCV,
        interval=interval,
        symbols_requested=len(symbols),
        symbols_succeeded=len(succeeded),
        symbols_failed=len(failed),
        total_records_written=sum(r.records_written for r in results),
        total_records_skipped=sum(r.records_skipped_duplicate for r in results),
        total_violations=sum(len(r.violations) for r in results),
        results=results,
    )


async def update_trades(
    symbols: list[str],
    cfg: MarketDataConfig = default_config,
    as_of: datetime | None = None,
) -> CollectionSummary:
    """
    Fetch aggregate trades that have appeared since the last stored trade.

    For each symbol:
      1. Find the latest stored trade timestamp.
      2. Fetch [latest_timestamp + 1ms, now).

    Respects the 48h aggTrades lookback limit — if the stored data is older
    than 48h, raises ValueError.

    Parameters
    ----------
    symbols:
        Symbols to update.
    cfg:
        Configuration.
    as_of:
        Reference "now".

    Returns
    -------
    CollectionSummary with per-symbol results.
    """
    now   = (as_of or datetime.now(tz=timezone.utc)).astimezone(timezone.utc)
    store = TradesStore(cfg)
    results: list[SymbolResult] = []

    async with MarketDataClient(cfg) as client:
        sem = asyncio.Semaphore(cfg.MAX_CONCURRENT_REQUESTS)

        async def _update_one(symbol: str) -> SymbolResult:
            async with sem:
                latest = store.get_latest_trade(symbol)
                if latest is None:
                    logger.warning(
                        "update_trades: %s — no stored data; run backfill first",
                        symbol,
                    )
                    return SymbolResult(symbol=symbol, success=False)

                update_start = latest.timestamp + timedelta(milliseconds=1)
                if update_start >= now:
                    return SymbolResult(symbol=symbol, success=True, records_written=0)

                # Guard the 48h limit
                hours = (now - update_start).total_seconds() / 3600
                if hours > cfg.AGTRADES_MAX_LOOKBACK_HOURS:
                    logger.error(
                        "update_trades: %s — gap of %.1fh exceeds 48h lookback. "
                        "Use backfill for older data.",
                        symbol, hours,
                    )
                    return SymbolResult(symbol=symbol, success=False)

                logger.info(
                    "update_trades: %s — fetching gap [%s, %s]",
                    symbol, update_start.isoformat(), now.isoformat(),
                )

                return await _backfill_symbol_trades(
                    symbol=symbol,
                    start_utc=update_start,
                    end_utc=now,
                    client=client,
                    store=store,
                    cfg=cfg,
                )

        results = list(await asyncio.gather(*[_update_one(s) for s in symbols]))

    succeeded = [r for r in results if r.success]
    failed    = [r for r in results if not r.success]

    return CollectionSummary(
        dataset=Dataset.TRADES,
        symbols_requested=len(symbols),
        symbols_succeeded=len(succeeded),
        symbols_failed=len(failed),
        total_records_written=sum(r.records_written for r in results),
        total_records_skipped=sum(r.records_skipped_duplicate for r in results),
        total_violations=sum(len(r.violations) for r in results),
        results=results,
    )
