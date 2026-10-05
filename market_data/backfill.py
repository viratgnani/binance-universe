"""
market_data/backfill.py

Paginated historical data collector.

Responsibilities:
  1. Split a requested [start, end] range into Binance-sized batches.
  2. Fetch each batch with MarketDataClient.
  3. Run integrity checks on each batch.
  4. Persist via OHLCVStore / TradesStore (dedup on write).
  5. Write BackfillProgress to disk so restarts continue where left off.
  6. Continue on per-symbol failures — one failed symbol never kills others.
  7. Return a CollectionSummary with per-symbol results.

Restart behavior
----------------
Progress is tracked in a JSON file at:
  data/ohlcv/{SYMBOL}/{interval}/.backfill_progress.json   (OHLCV)
  data/trades/{SYMBOL}/.backfill_progress.json             (Trades)

On restart with the same (symbol, interval, start, end):
  - If progress.is_complete == True → skip (already done).
  - If progress.last_completed_open_time is set → resume from that cursor.
  - If no progress file → start fresh from requested start.

Idempotency
-----------
Even without restart files, the stores' dedup-on-write ensures that
rerunning a completed backfill is safe — no duplicates will be created.
"""

from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime, timezone
from pathlib import Path

from market_data.client import MarketDataAPIError, MarketDataClient
from market_data.config import MarketDataConfig, config as default_config
from market_data.integrity import run_all_candle_checks, run_all_trade_checks
from market_data.models import (
    AggTrade,
    BackfillProgress,
    Candle,
    CollectionError,
    CollectionSummary,
    Dataset,
    SymbolResult,
)
from market_data.ohlcv_store import OHLCVStore
from market_data.trades_store import TradesStore

logger = logging.getLogger(__name__)


# --------------------------------------------------------------------------- #
#  Progress persistence helpers
# --------------------------------------------------------------------------- #


def _ohlcv_progress_path(
    symbol: str,
    interval: str,
    cfg: MarketDataConfig,
) -> Path:
    return Path(cfg.OHLCV_DIR) / symbol / interval / ".backfill_progress.json"


def _trades_progress_path(symbol: str, cfg: MarketDataConfig) -> Path:
    return Path(cfg.TRADES_DIR) / symbol / ".backfill_progress.json"


def _load_progress(path: Path) -> BackfillProgress | None:
    if not path.exists():
        return None
    try:
        return BackfillProgress.model_validate_json(path.read_text(encoding="utf-8"))
    except Exception as exc:
        logger.warning("Could not read backfill progress from %s: %s", path, exc)
        return None


def _save_progress(path: Path, progress: BackfillProgress) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(progress.model_dump_json(), encoding="utf-8")


# --------------------------------------------------------------------------- #
#  OHLCV backfill
# --------------------------------------------------------------------------- #


async def backfill_ohlcv(
    symbols: list[str],
    interval: str,
    start: datetime,
    end: datetime,
    cfg: MarketDataConfig = default_config,
) -> CollectionSummary:
    """
    Backfill OHLCV data for *symbols* over [start, end].

    Parameters
    ----------
    symbols:
        List of Binance perpetual symbols, e.g. ["BTCUSDT", "ETHUSDT"].
    interval:
        Candlestick interval string, e.g. "1m".
    start, end:
        UTC-aware datetime boundaries (inclusive).
    cfg:
        Configuration object.

    Returns
    -------
    CollectionSummary with per-symbol results.
    """
    if interval not in cfg.SUPPORTED_INTERVALS:
        raise ValueError(
            f"Unsupported interval '{interval}'. "
            f"Valid: {sorted(cfg.SUPPORTED_INTERVALS)}"
        )

    start_utc = start.astimezone(timezone.utc)
    end_utc   = end.astimezone(timezone.utc)
    step_ms   = cfg.INTERVAL_MS[interval]

    store   = OHLCVStore(cfg)
    results: list[SymbolResult] = []

    async with MarketDataClient(cfg) as client:
        # Process symbols with bounded concurrency
        sem = asyncio.Semaphore(cfg.MAX_CONCURRENT_REQUESTS)

        async def _process_one(symbol: str) -> SymbolResult:
            async with sem:
                return await _backfill_symbol_ohlcv(
                    symbol=symbol,
                    interval=interval,
                    start_utc=start_utc,
                    end_utc=end_utc,
                    step_ms=step_ms,
                    client=client,
                    store=store,
                    cfg=cfg,
                )

        results = list(await asyncio.gather(*[_process_one(s) for s in symbols]))

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


async def _backfill_symbol_ohlcv(
    symbol: str,
    interval: str,
    start_utc: datetime,
    end_utc: datetime,
    step_ms: int,
    client: MarketDataClient,
    store: OHLCVStore,
    cfg: MarketDataConfig,
) -> SymbolResult:
    """Backfill one symbol's OHLCV data.  Never raises — errors become SymbolResult."""
    progress_path = _ohlcv_progress_path(symbol, interval, cfg)
    progress      = _load_progress(progress_path)

    # Check if already complete
    if (
        progress is not None
        and progress.is_complete
        and progress.requested_start <= start_utc
        and progress.requested_end   >= end_utc
    ):
        logger.info(
            "OHLCV backfill: %s %s already complete - skipping", symbol, interval
        )
        existing = store.count_stored(symbol, interval, start_utc, end_utc)
        return SymbolResult(
            symbol=symbol,
            success=True,
            records_written=0,
            records_skipped_duplicate=existing,
        )

    # Determine start cursor
    cursor_ms: int
    if (
        progress is not None
        and progress.last_completed_open_time is not None
        and not progress.is_complete
    ):
        # Resume from where we left off (add one interval step to avoid re-fetching)
        cursor_ms = int(progress.last_completed_open_time.timestamp() * 1000) + step_ms
        logger.info(
            "OHLCV backfill: %s %s resuming from %s",
            symbol, interval, progress.last_completed_open_time.isoformat(),
        )
    else:
        cursor_ms = int(start_utc.timestamp() * 1000)
        # Initialise progress file
        progress = BackfillProgress(
            symbol=symbol,
            dataset=Dataset.OHLCV,
            interval=interval,
            requested_start=start_utc,
            requested_end=end_utc,
        )
        _save_progress(progress_path, progress)

    end_ms        = int(end_utc.timestamp() * 1000)
    batch_size_ms = step_ms * cfg.KLINES_LIMIT

    total_written  = 0
    total_skipped  = 0
    total_batches  = 0
    all_violations = []

    try:
        while cursor_ms < end_ms:
            batch_end_ms = min(cursor_ms + batch_size_ms - step_ms, end_ms)

            candles = await client.get_klines(
                symbol=symbol,
                interval=interval,
                start_ms=cursor_ms,
                end_ms=batch_end_ms,
                limit=cfg.KLINES_LIMIT,
            )

            if not candles:
                # No data in this range — advance and continue
                cursor_ms = batch_end_ms + step_ms
                continue

            # Sort before integrity check
            candles.sort(key=lambda c: c.open_time)

            # Integrity checks (do not stop on violations — record them)
            violations = run_all_candle_checks(candles, interval)
            if violations:
                logger.warning(
                    "OHLCV integrity: %s %s batch %d — %d violation(s)",
                    symbol, interval, total_batches + 1, len(violations),
                )
            all_violations.extend(violations)

            written, skipped = store.save(candles)
            total_written += written
            total_skipped += skipped
            total_batches += 1

            # Advance cursor past the last received candle
            last_open_ms = int(candles[-1].open_time.timestamp() * 1000)
            cursor_ms    = last_open_ms + step_ms

            # Update restart checkpoint
            progress.last_completed_open_time = candles[-1].open_time
            _save_progress(progress_path, progress)

            if total_batches % cfg.LOG_PROGRESS_EVERY_N_BATCHES == 0:
                logger.info(
                    "OHLCV backfill: %s %s — batch %d, written=%d, cursor=%s",
                    symbol, interval, total_batches, total_written,
                    candles[-1].open_time.isoformat(),
                )

        # Mark complete
        progress.is_complete = True
        _save_progress(progress_path, progress)

        logger.info(
            "OHLCV backfill complete: %s %s - %d written, %d skipped, %d violations",
            symbol, interval, total_written, total_skipped, len(all_violations),
        )

        return SymbolResult(
            symbol=symbol,
            success=True,
            records_written=total_written,
            records_skipped_duplicate=total_skipped,
            batches_fetched=total_batches,
            violations=all_violations,
        )

    except MarketDataAPIError as exc:
        logger.error(
            "OHLCV backfill FAILED: %s %s — %s (retryable=%s)",
            symbol, interval, exc, exc.retryable,
        )
        return SymbolResult(
            symbol=symbol,
            success=False,
            records_written=total_written,
            records_skipped_duplicate=total_skipped,
            batches_fetched=total_batches,
            violations=all_violations,
            error=CollectionError(
                symbol=symbol,
                dataset=Dataset.OHLCV,
                interval=interval,
                error_message=str(exc),
                retryable=exc.retryable,
            ),
        )
    except Exception as exc:
        logger.error(
            "OHLCV backfill unexpected error: %s %s — %s",
            symbol, interval, exc, exc_info=True,
        )
        return SymbolResult(
            symbol=symbol,
            success=False,
            records_written=total_written,
            records_skipped_duplicate=total_skipped,
            batches_fetched=total_batches,
            violations=all_violations,
            error=CollectionError(
                symbol=symbol,
                dataset=Dataset.OHLCV,
                interval=interval,
                error_message=f"Unexpected: {exc}",
                retryable=False,
            ),
        )


# --------------------------------------------------------------------------- #
#  Trades backfill
# --------------------------------------------------------------------------- #


async def backfill_trades(
    symbols: list[str],
    start: datetime,
    end: datetime,
    cfg: MarketDataConfig = default_config,
) -> CollectionSummary:
    """
    Backfill aggregate trades for *symbols* over [start, end].

    Limitation: Binance aggTrades API supports at most 48h lookback via
    startTime/endTime.  This function enforces that limit and raises
    ValueError for ranges exceeding it.

    Parameters
    ----------
    symbols, start, end, cfg:
        As in backfill_ohlcv.

    Returns
    -------
    CollectionSummary with per-symbol results.
    """
    start_utc = start.astimezone(timezone.utc)
    end_utc   = end.astimezone(timezone.utc)

    hours = (end_utc - start_utc).total_seconds() / 3600
    if hours > cfg.AGTRADES_MAX_LOOKBACK_HOURS:
        raise ValueError(
            f"Requested range is {hours:.1f}h but aggTrades API supports only "
            f"{cfg.AGTRADES_MAX_LOOKBACK_HOURS}h lookback. "
            "Use the Binance async export API for older history (not in V1 scope)."
        )

    store   = TradesStore(cfg)
    results: list[SymbolResult] = []

    async with MarketDataClient(cfg) as client:
        sem = asyncio.Semaphore(cfg.MAX_CONCURRENT_REQUESTS)

        async def _process_one(symbol: str) -> SymbolResult:
            async with sem:
                return await _backfill_symbol_trades(
                    symbol=symbol,
                    start_utc=start_utc,
                    end_utc=end_utc,
                    client=client,
                    store=store,
                    cfg=cfg,
                )

        results = list(await asyncio.gather(*[_process_one(s) for s in symbols]))

    succeeded = [r for r in results if r.success]
    failed    = [r for r in results if not r.success]

    return CollectionSummary(
        dataset=Dataset.TRADES,
        interval=None,
        symbols_requested=len(symbols),
        symbols_succeeded=len(succeeded),
        symbols_failed=len(failed),
        total_records_written=sum(r.records_written for r in results),
        total_records_skipped=sum(r.records_skipped_duplicate for r in results),
        total_violations=sum(len(r.violations) for r in results),
        results=results,
    )


async def _backfill_symbol_trades(
    symbol: str,
    start_utc: datetime,
    end_utc: datetime,
    client: MarketDataClient,
    store: TradesStore,
    cfg: MarketDataConfig,
) -> SymbolResult:
    """Backfill one symbol's trade data.  Never raises."""
    progress_path = _trades_progress_path(symbol, cfg)
    progress      = _load_progress(progress_path)

    if (
        progress is not None
        and progress.is_complete
        and progress.requested_start <= start_utc
        and progress.requested_end   >= end_utc
    ):
        logger.info("Trades backfill: %s already complete - skipping", symbol)
        existing = store.count_stored(symbol, start_utc, end_utc)
        return SymbolResult(
            symbol=symbol,
            success=True,
            records_skipped_duplicate=existing,
        )

    # Paginate using time windows of 1h (well within 48h limit)
    # Each window requests up to AGTRADES_LIMIT records
    WINDOW_MS = 3_600_000  # 1 hour in ms

    start_ms  = int(start_utc.timestamp() * 1000)
    end_ms    = int(end_utc.timestamp()   * 1000)
    cursor_ms = start_ms

    if progress is not None and progress.last_completed_open_time is not None:
        cursor_ms = int(progress.last_completed_open_time.timestamp() * 1000) + 1
    else:
        progress = BackfillProgress(
            symbol=symbol,
            dataset=Dataset.TRADES,
            requested_start=start_utc,
            requested_end=end_utc,
        )
        _save_progress(progress_path, progress)

    total_written  = 0
    total_skipped  = 0
    total_batches  = 0
    all_violations = []

    try:
        while cursor_ms < end_ms:
            window_end_ms = min(cursor_ms + WINDOW_MS - 1, end_ms)

            trades = await client.get_agg_trades(
                symbol=symbol,
                start_ms=cursor_ms,
                end_ms=window_end_ms,
                limit=cfg.AGTRADES_LIMIT,
            )

            if not trades:
                cursor_ms = window_end_ms + 1
                continue

            trades.sort(key=lambda t: (t.timestamp, t.agg_trade_id))

            violations = run_all_trade_checks(trades)
            if violations:
                logger.warning(
                    "Trades integrity: %s batch %d — %d violation(s)",
                    symbol, total_batches + 1, len(violations),
                )
            all_violations.extend(violations)

            written, skipped = store.save(trades)
            total_written += written
            total_skipped += skipped
            total_batches += 1

            # Advance past last received trade
            last_ts_ms = int(trades[-1].timestamp.timestamp() * 1000)
            cursor_ms  = last_ts_ms + 1

            progress.last_completed_open_time = trades[-1].timestamp
            _save_progress(progress_path, progress)

        progress.is_complete = True
        _save_progress(progress_path, progress)

        logger.info(
            "Trades backfill complete: %s — %d written, %d skipped",
            symbol, total_written, total_skipped,
        )

        return SymbolResult(
            symbol=symbol,
            success=True,
            records_written=total_written,
            records_skipped_duplicate=total_skipped,
            batches_fetched=total_batches,
            violations=all_violations,
        )

    except MarketDataAPIError as exc:
        logger.error("Trades backfill FAILED: %s — %s", symbol, exc)
        return SymbolResult(
            symbol=symbol,
            success=False,
            records_written=total_written,
            records_skipped_duplicate=total_skipped,
            batches_fetched=total_batches,
            violations=all_violations,
            error=CollectionError(
                symbol=symbol,
                dataset=Dataset.TRADES,
                error_message=str(exc),
                retryable=exc.retryable,
            ),
        )
    except Exception as exc:
        logger.error("Trades backfill unexpected error: %s — %s", symbol, exc, exc_info=True)
        return SymbolResult(
            symbol=symbol,
            success=False,
            records_written=total_written,
            records_skipped_duplicate=total_skipped,
            batches_fetched=total_batches,
            violations=all_violations,
            error=CollectionError(
                symbol=symbol,
                dataset=Dataset.TRADES,
                error_message=f"Unexpected: {exc}",
                retryable=False,
            ),
        )
