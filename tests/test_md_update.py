"""
tests/test_md_update.py

Tests for market_data/update.py

Covers:
  - update_ohlcv() fetches only the gap since last stored candle
  - update_ohlcv() returns success=False if no prior data exists
  - update_ohlcv() is idempotent when already up-to-date
  - update_trades() fetches only gap since last stored trade
  - update_trades() reports failure gracefully if no prior data
  - Incremental update does not re-download history
"""

from __future__ import annotations

from datetime import datetime, timezone, timedelta
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from market_data.config import MarketDataConfig
from market_data.models import AggTrade, Candle
from market_data.ohlcv_store import OHLCVStore
from market_data.trades_store import TradesStore
from market_data.update import update_ohlcv, update_trades


# ─── Fixtures ─────────────────────────────────────────────────────────────────


@pytest.fixture()
def cfg(tmp_path: Path) -> MarketDataConfig:
    c = MarketDataConfig()
    c.OHLCV_DIR  = tmp_path / "ohlcv"
    c.TRADES_DIR = tmp_path / "trades"
    c.RETRY_MAX_ATTEMPTS = 1
    c.RETRY_BACKOFF_BASE = 0.0
    c.MAX_CONCURRENT_REQUESTS = 3
    return c


_BASE = datetime(2026, 8, 31, 12, 0, 0, tzinfo=timezone.utc)
_NOW  = _BASE + timedelta(minutes=30)


def _candle(offset_minutes: int, symbol: str = "BTCUSDT") -> Candle:
    ts = _BASE + timedelta(minutes=offset_minutes)
    return Candle(
        symbol=symbol, interval="1m",
        open_time=ts, close_time=ts + timedelta(seconds=59, milliseconds=999),
        open=100.0, high=110.0, low=90.0, close=105.0,
        volume=1.0, quote_volume=100.0, trade_count=10,
        taker_buy_base_vol=0.5, taker_buy_quote_vol=50.0,
    )


def _trade(agg_id: int, offset_seconds: int = 0, symbol: str = "BTCUSDT") -> AggTrade:
    ts = _BASE + timedelta(seconds=offset_seconds)
    return AggTrade(
        symbol=symbol, agg_trade_id=agg_id,
        price=50000.0, quantity=0.5, quote_quantity=25000.0,
        first_trade_id=agg_id, last_trade_id=agg_id,
        timestamp=ts, buyer_is_maker=False,
    )


# ─── update_ohlcv ─────────────────────────────────────────────────────────────


class TestUpdateOHLCV:
    async def test_no_prior_data_returns_failure(self, cfg):
        """If no candles are stored, update should return failure (not crash)."""
        with patch("market_data.update.MarketDataClient") as mock_cls:
            mock_cls.return_value.__aenter__ = AsyncMock(return_value=MagicMock())
            mock_cls.return_value.__aexit__  = AsyncMock(return_value=False)

            summary = await update_ohlcv(["BTCUSDT"], "1m", cfg, as_of=_NOW)

        btc = next(r for r in summary.results if r.symbol == "BTCUSDT")
        assert btc.success is False

    async def test_fetches_only_gap(self, cfg):
        """Store 5 candles; update should request only minutes 5+."""
        store = OHLCVStore(cfg)
        store.save([_candle(i) for i in range(5)])  # 0..4 stored

        new_candles = [_candle(i) for i in range(5, 10)]  # 5..9 new
        fetched_starts = []
        call_count = [0]

        async def _klines(symbol, interval, start_ms, end_ms, limit=None):
            fetched_starts.append(start_ms)
            call_count[0] += 1
            if call_count[0] == 1:
                return new_candles
            return []

        with patch("market_data.update.MarketDataClient") as mock_cls:
            mock_client = MagicMock()
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__  = AsyncMock(return_value=False)
            mock_client.get_klines = _klines
            mock_cls.return_value = mock_client

            await update_ohlcv(["BTCUSDT"], "1m", cfg, as_of=_NOW)

        # First request should start at minute 5 (after last stored = minute 4)
        assert len(fetched_starts) > 0
        expected_start_ms = int((_BASE + timedelta(minutes=5)).timestamp() * 1000)
        assert fetched_starts[0] == expected_start_ms

    async def test_already_up_to_date_returns_zero_written(self, cfg):
        """If last candle open_time + 1 interval >= now, no fetch needed."""
        store = OHLCVStore(cfg)
        # Store candle at _NOW (already current)
        store.save([_candle(0)])

        # as_of = _BASE (before stored candle): simulate "already up to date"
        as_of = _BASE  # This is <= stored open_time

        with patch("market_data.update.MarketDataClient") as mock_cls:
            mock_client = MagicMock()
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__  = AsyncMock(return_value=False)
            mock_client.get_klines = AsyncMock(return_value=[])
            mock_cls.return_value = mock_client

            summary = await update_ohlcv(["BTCUSDT"], "1m", cfg, as_of=as_of)

        btc = next(r for r in summary.results if r.symbol == "BTCUSDT")
        assert btc.success is True
        assert btc.records_written == 0

    async def test_unsupported_interval_raises(self, cfg):
        with pytest.raises(ValueError, match="Unsupported interval"):
            await update_ohlcv(["BTCUSDT"], "99x", cfg)

    async def test_failure_isolation_across_symbols(self, cfg):
        """Store data for BTC but not ETH; ETH update should fail, BTC should succeed."""
        store = OHLCVStore(cfg)
        store.save([_candle(i, symbol="BTCUSDT") for i in range(3)])

        new_candles_btc = [_candle(i, symbol="BTCUSDT") for i in range(3, 6)]
        btc_call_count = [0]

        async def _klines(symbol, interval, start_ms, end_ms, limit=None):
            if symbol == "BTCUSDT":
                btc_call_count[0] += 1
                if btc_call_count[0] == 1:
                    return new_candles_btc
            return []

        with patch("market_data.update.MarketDataClient") as mock_cls:
            mock_client = MagicMock()
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__  = AsyncMock(return_value=False)
            mock_client.get_klines = _klines
            mock_cls.return_value = mock_client

            summary = await update_ohlcv(["BTCUSDT", "ETHUSDT"], "1m", cfg, as_of=_NOW)

        btc_r = next(r for r in summary.results if r.symbol == "BTCUSDT")
        eth_r = next(r for r in summary.results if r.symbol == "ETHUSDT")
        assert btc_r.success is True
        assert eth_r.success is False   # no prior data for ETH


# ─── update_trades ────────────────────────────────────────────────────────────


class TestUpdateTrades:
    async def test_no_prior_data_returns_failure(self, cfg):
        with patch("market_data.update.MarketDataClient") as mock_cls:
            mock_client = MagicMock()
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__  = AsyncMock(return_value=False)
            mock_cls.return_value = mock_client

            summary = await update_trades(["BTCUSDT"], cfg, as_of=_NOW)

        btc = next(r for r in summary.results if r.symbol == "BTCUSDT")
        assert btc.success is False

    async def test_fetches_only_gap_since_last_trade(self, cfg):
        """Store 5 trades; update should request only data after last trade."""
        store = TradesStore(cfg)
        store.save([_trade(i + 1, i * 10) for i in range(5)])  # last ts at 40s

        new_trades = [_trade(i + 100, i * 10 + 50) for i in range(3)]
        fetched_starts = []
        call_count = [0]

        async def _agg(symbol, start_ms, end_ms, limit=None, from_id=None):
            fetched_starts.append(start_ms)
            call_count[0] += 1
            if call_count[0] == 1:
                return new_trades
            return []  # terminate pagination

        with patch("market_data.update.MarketDataClient") as mock_cls:
            mock_client = MagicMock()
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__  = AsyncMock(return_value=False)
            mock_client.get_agg_trades = _agg
            mock_cls.return_value = mock_client

            await update_trades(["BTCUSDT"], cfg, as_of=_NOW)

        # First fetch should start 1ms after the last stored trade timestamp
        assert len(fetched_starts) > 0
        last_stored_ts = _BASE + timedelta(seconds=40)
        expected_ms = int(last_stored_ts.timestamp() * 1000) + 1
        assert fetched_starts[0] == expected_ms

    async def test_already_up_to_date(self, cfg):
        """If last stored trade is at _NOW - 1s, update with as_of=last should skip."""
        store = TradesStore(cfg)
        # Store a trade 1s before "now"
        store.save([_trade(1, 0)])

        as_of = _BASE  # before stored trade

        with patch("market_data.update.MarketDataClient") as mock_cls:
            mock_client = MagicMock()
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__  = AsyncMock(return_value=False)
            mock_client.get_agg_trades = AsyncMock(return_value=[])
            mock_cls.return_value = mock_client

            summary = await update_trades(["BTCUSDT"], cfg, as_of=as_of)

        btc = next(r for r in summary.results if r.symbol == "BTCUSDT")
        assert btc.success is True
        assert btc.records_written == 0
