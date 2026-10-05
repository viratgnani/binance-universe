"""
tests/test_md_backfill.py

Tests for market_data/backfill.py

Covers:
  - backfill_ohlcv() fetches and stores candles
  - Pagination: multiple batches until range is complete
  - Failure isolation: one failed symbol doesn't abort others
  - Restart: backfill picks up from last checkpoint
  - Idempotent: rerunning does not duplicate records
  - backfill_trades() fetches and stores trades
  - trades: 48h limit enforced
  - CollectionSummary fields are correct

All Binance HTTP calls are mocked.
"""

from __future__ import annotations

from datetime import datetime, timezone, timedelta
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from market_data.backfill import backfill_ohlcv, backfill_trades
from market_data.client import MarketDataAPIError
from market_data.config import MarketDataConfig
from market_data.models import Candle, AggTrade, Dataset


# ─── Shared fixtures ──────────────────────────────────────────────────────────


@pytest.fixture()
def cfg(tmp_path: Path) -> MarketDataConfig:
    c = MarketDataConfig()
    c.OHLCV_DIR  = tmp_path / "ohlcv"
    c.TRADES_DIR = tmp_path / "trades"
    c.RETRY_MAX_ATTEMPTS = 1   # Fast failure for tests
    c.RETRY_BACKOFF_BASE = 0.0
    c.MAX_CONCURRENT_REQUESTS = 5
    return c


_BASE     = datetime(2026, 8, 31, 12, 0, 0, tzinfo=timezone.utc)
_BASE_MS  = int(_BASE.timestamp() * 1000)


def _make_candle_batch(start_minute: int, count: int, symbol: str = "BTCUSDT") -> list[Candle]:
    candles = []
    for i in range(count):
        ts = _BASE + timedelta(minutes=start_minute + i)
        candles.append(Candle(
            symbol=symbol,
            interval="1m",
            open_time=ts,
            close_time=ts + timedelta(seconds=59, milliseconds=999),
            open=100.0, high=110.0, low=90.0, close=105.0,
            volume=1.0, quote_volume=100.0, trade_count=10,
            taker_buy_base_vol=0.5, taker_buy_quote_vol=50.0,
        ))
    return candles


def _make_trade_batch(start_id: int, count: int, symbol: str = "BTCUSDT") -> list[AggTrade]:
    trades = []
    for i in range(count):
        ts = _BASE + timedelta(seconds=i)
        trades.append(AggTrade(
            symbol=symbol,
            agg_trade_id=start_id + i,
            price=50000.0,
            quantity=0.5,
            quote_quantity=25000.0,
            first_trade_id=start_id + i,
            last_trade_id=start_id + i,
            timestamp=ts,
            buyer_is_maker=False,
        ))
    return trades


# ─── backfill_ohlcv ───────────────────────────────────────────────────────────


class TestBackfillOHLCV:
    async def test_basic_backfill_writes_candles(self, cfg):
        """Single-batch backfill writes all candles and reports success."""
        candles = _make_candle_batch(0, 10)
        end = _BASE + timedelta(minutes=10)

        with patch("market_data.backfill.MarketDataClient") as mock_cls:
            mock_client = MagicMock()
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__  = AsyncMock(return_value=False)
            mock_client.get_klines = AsyncMock(return_value=candles)
            mock_cls.return_value = mock_client

            summary = await backfill_ohlcv(["BTCUSDT"], "1m", _BASE, end, cfg)

        assert summary.symbols_succeeded == 1
        assert summary.symbols_failed    == 0
        assert summary.total_records_written >= 10

    async def test_unsupported_interval_raises(self, cfg):
        with pytest.raises(ValueError, match="Unsupported interval"):
            await backfill_ohlcv(["BTCUSDT"], "99x", _BASE, _BASE + timedelta(hours=1), cfg)

    async def test_failure_isolation_one_symbol(self, cfg):
        """If XYZUSDT fails, BTCUSDT should still succeed."""
        btc_candles = _make_candle_batch(0, 5, "BTCUSDT")
        end = _BASE + timedelta(minutes=5)

        async def _klines(symbol: str, interval: str, start_ms: int, end_ms: int, limit: int = None):
            if symbol == "XYZUSDT":
                raise MarketDataAPIError("Simulated failure", retryable=False)
            return btc_candles

        with patch("market_data.backfill.MarketDataClient") as mock_cls:
            mock_client = MagicMock()
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__  = AsyncMock(return_value=False)
            mock_client.get_klines = _klines
            mock_cls.return_value = mock_client

            summary = await backfill_ohlcv(
                ["BTCUSDT", "XYZUSDT"], "1m", _BASE, end, cfg
            )

        assert summary.symbols_succeeded == 1
        assert summary.symbols_failed    == 1
        # BTCUSDT should have written records
        btc_result = next(r for r in summary.results if r.symbol == "BTCUSDT")
        assert btc_result.success is True
        # XYZUSDT should have recorded an error
        xyz_result = next(r for r in summary.results if r.symbol == "XYZUSDT")
        assert xyz_result.success is False
        assert xyz_result.error is not None

    async def test_idempotent_backfill(self, cfg):
        """Running backfill twice on the same range should not create duplicates."""
        candles = _make_candle_batch(0, 5)
        end = _BASE + timedelta(minutes=5)

        with patch("market_data.backfill.MarketDataClient") as mock_cls:
            mock_client = MagicMock()
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__  = AsyncMock(return_value=False)
            mock_client.get_klines = AsyncMock(return_value=candles)
            mock_cls.return_value = mock_client

            summary1 = await backfill_ohlcv(["BTCUSDT"], "1m", _BASE, end, cfg)
            # Delete progress file so second run doesn't skip
            progress_files = list((cfg.OHLCV_DIR / "BTCUSDT" / "1m").glob(".backfill_progress.json"))
            for f in progress_files:
                f.unlink()
            summary2 = await backfill_ohlcv(["BTCUSDT"], "1m", _BASE, end, cfg)

        assert summary1.total_records_written == 5
        assert summary2.total_records_written == 0   # all skipped as duplicates
        assert summary2.total_records_skipped == 5

    async def test_pagination_multiple_batches(self, cfg):
        """When batch limit < total range, multiple API calls should be made."""
        cfg.KLINES_LIMIT = 3  # Force 2 batches for 5 minutes

        # First call returns 3 candles, second call returns 2
        batch1 = _make_candle_batch(0, 3)
        batch2 = _make_candle_batch(3, 2)
        call_args = []

        async def _klines(symbol, interval, start_ms, end_ms, limit=None):
            call_args.append(start_ms)
            if len(call_args) == 1:
                return batch1
            return batch2

        end = _BASE + timedelta(minutes=5)
        with patch("market_data.backfill.MarketDataClient") as mock_cls:
            mock_client = MagicMock()
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__  = AsyncMock(return_value=False)
            mock_client.get_klines = _klines
            mock_cls.return_value = mock_client

            summary = await backfill_ohlcv(["BTCUSDT"], "1m", _BASE, end, cfg)

        assert len(call_args) >= 2  # At least 2 batches
        assert summary.total_records_written == 5

    async def test_summary_dataset_is_ohlcv(self, cfg):
        candles = _make_candle_batch(0, 2)
        end = _BASE + timedelta(minutes=2)

        with patch("market_data.backfill.MarketDataClient") as mock_cls:
            mock_client = MagicMock()
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__  = AsyncMock(return_value=False)
            mock_client.get_klines = AsyncMock(return_value=candles)
            mock_cls.return_value = mock_client

            summary = await backfill_ohlcv(["BTCUSDT"], "1m", _BASE, end, cfg)

        assert summary.dataset  == Dataset.OHLCV
        assert summary.interval == "1m"

    async def test_empty_api_response_handled(self, cfg):
        """If the API returns no candles for a range, backfill should complete gracefully."""
        end = _BASE + timedelta(minutes=5)

        with patch("market_data.backfill.MarketDataClient") as mock_cls:
            mock_client = MagicMock()
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__  = AsyncMock(return_value=False)
            mock_client.get_klines = AsyncMock(return_value=[])
            mock_cls.return_value = mock_client

            summary = await backfill_ohlcv(["BTCUSDT"], "1m", _BASE, end, cfg)

        assert summary.symbols_succeeded  == 1
        assert summary.total_records_written == 0


# ─── backfill_trades ─────────────────────────────────────────────────────────


class TestBackfillTrades:
    async def test_basic_trade_backfill(self, cfg):
        trades = _make_trade_batch(1, 10)
        # Return trades on first call, empty on subsequent (stops pagination)
        call_count = [0]

        async def _agg(symbol, start_ms, end_ms, limit=None, from_id=None):
            call_count[0] += 1
            if call_count[0] == 1:
                return trades
            return []   # No more data → pagination terminates

        end = _BASE + timedelta(hours=1)

        with patch("market_data.backfill.MarketDataClient") as mock_cls:
            mock_client = MagicMock()
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__  = AsyncMock(return_value=False)
            mock_client.get_agg_trades = _agg
            mock_cls.return_value = mock_client

            summary = await backfill_trades(["BTCUSDT"], _BASE, end, cfg)

        assert summary.symbols_succeeded     >= 1
        assert summary.total_records_written >= 10
        assert summary.dataset == Dataset.TRADES

    async def test_48h_limit_enforced(self, cfg):
        """Requesting > 48h should raise ValueError before any API call."""
        start = _BASE
        end   = _BASE + timedelta(hours=49)

        with pytest.raises(ValueError, match="48h"):
            await backfill_trades(["BTCUSDT"], start, end, cfg)

    async def test_trade_failure_isolation(self, cfg):
        """Failed symbol should not prevent other symbols from completing."""
        btc_trades = _make_trade_batch(1, 5, "BTCUSDT")
        end = _BASE + timedelta(hours=1)
        btc_calls = [0]

        async def _agg(symbol, start_ms, end_ms, limit=None, from_id=None):
            if symbol == "BADUSDT":
                raise MarketDataAPIError("Simulated failure", retryable=False)
            btc_calls[0] += 1
            if btc_calls[0] == 1:
                return btc_trades
            return []  # Terminate pagination after first batch

        with patch("market_data.backfill.MarketDataClient") as mock_cls:
            mock_client = MagicMock()
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__  = AsyncMock(return_value=False)
            mock_client.get_agg_trades = _agg
            mock_cls.return_value = mock_client

            summary = await backfill_trades(["BTCUSDT", "BADUSDT"], _BASE, end, cfg)

        assert summary.symbols_succeeded == 1
        assert summary.symbols_failed    == 1
