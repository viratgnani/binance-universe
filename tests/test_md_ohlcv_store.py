"""
tests/test_md_ohlcv_store.py

Tests for market_data/ohlcv_store.py

Covers:
  - save() writes new candles to JSONL
  - save() skips duplicates (idempotent)
  - save() splits across date files correctly
  - load() returns candles in [start, end]
  - load() returns empty for unknown symbol
  - get_latest() returns most recent candle
  - get_latest() returns None if no data
  - count_stored() correct count
  - list_symbols() returns stored symbols
  - File stays sorted after incremental append
"""

from __future__ import annotations

from datetime import datetime, timezone, timedelta
from pathlib import Path

import pytest

from market_data.config import MarketDataConfig
from market_data.models import Candle
from market_data.ohlcv_store import OHLCVStore


# ─── Fixtures ─────────────────────────────────────────────────────────────────


@pytest.fixture()
def cfg(tmp_path: Path) -> MarketDataConfig:
    c = MarketDataConfig()
    c.OHLCV_DIR = tmp_path / "ohlcv"
    return c


@pytest.fixture()
def store(cfg: MarketDataConfig) -> OHLCVStore:
    return OHLCVStore(cfg)


# ─── Helpers ──────────────────────────────────────────────────────────────────

_BASE = datetime(2026, 8, 31, 12, 0, 0, tzinfo=timezone.utc)


def _candle(offset_minutes: int = 0, symbol: str = "BTCUSDT", interval: str = "1m") -> Candle:
    ts = _BASE + timedelta(minutes=offset_minutes)
    return Candle(
        symbol=symbol,
        interval=interval,
        open_time=ts,
        close_time=ts + timedelta(seconds=59, milliseconds=999),
        open=100.0, high=110.0, low=90.0, close=105.0,
        volume=1.0, quote_volume=100.0, trade_count=10,
        taker_buy_base_vol=0.5, taker_buy_quote_vol=50.0,
    )


def _day_after_candle(offset_minutes: int = 0) -> Candle:
    """Candle on the next UTC day (2026-09-01)."""
    base_next = datetime(2026, 9, 1, 0, 0, 0, tzinfo=timezone.utc)
    ts = base_next + timedelta(minutes=offset_minutes)
    return Candle(
        symbol="BTCUSDT",
        interval="1m",
        open_time=ts,
        close_time=ts + timedelta(seconds=59, milliseconds=999),
        open=100.0, high=110.0, low=90.0, close=105.0,
        volume=1.0, quote_volume=100.0, trade_count=10,
        taker_buy_base_vol=0.5, taker_buy_quote_vol=50.0,
    )


# ─── Tests ────────────────────────────────────────────────────────────────────


class TestOHLCVStoreSave:
    def test_save_returns_count(self, store):
        candles = [_candle(i) for i in range(5)]
        written, skipped = store.save(candles)
        assert written  == 5
        assert skipped  == 0

    def test_save_creates_jsonl_file(self, cfg, store):
        store.save([_candle(0)])
        expected = cfg.OHLCV_DIR / "BTCUSDT" / "1m" / "20260831.jsonl"
        assert expected.exists()

    def test_idempotent_save_skips_duplicates(self, store):
        candles = [_candle(i) for i in range(3)]
        store.save(candles)
        written2, skipped2 = store.save(candles)
        assert written2 == 0
        assert skipped2 == 3

    def test_partial_duplicate_only_writes_new(self, store):
        store.save([_candle(0), _candle(1)])
        written, skipped = store.save([_candle(1), _candle(2)])
        assert written  == 1
        assert skipped  == 1

    def test_multi_date_creates_separate_files(self, cfg, store):
        store.save([_candle(0), _day_after_candle(0)])
        f1 = cfg.OHLCV_DIR / "BTCUSDT" / "1m" / "20260831.jsonl"
        f2 = cfg.OHLCV_DIR / "BTCUSDT" / "1m" / "20260901.jsonl"
        assert f1.exists()
        assert f2.exists()

    def test_save_empty_list_returns_zero(self, store):
        w, s = store.save([])
        assert w == 0
        assert s == 0

    def test_saved_candles_are_sorted_in_file(self, cfg, store):
        """Even if candles are provided out-of-order, file should be sorted."""
        store.save([_candle(2), _candle(0), _candle(1)])
        candles = store.load("BTCUSDT", "1m", _BASE, _BASE + timedelta(minutes=5))
        for i in range(len(candles) - 1):
            assert candles[i].open_time <= candles[i + 1].open_time


class TestOHLCVStoreLoad:
    def test_load_returns_all_in_range(self, store):
        candles = [_candle(i) for i in range(5)]
        store.save(candles)
        loaded = store.load("BTCUSDT", "1m", _BASE, _BASE + timedelta(minutes=10))
        assert len(loaded) == 5

    def test_load_filters_by_range(self, store):
        candles = [_candle(i) for i in range(10)]
        store.save(candles)
        start = _BASE + timedelta(minutes=2)
        end   = _BASE + timedelta(minutes=4)
        loaded = store.load("BTCUSDT", "1m", start, end)
        assert len(loaded) == 3   # minutes 2, 3, 4

    def test_load_returns_sorted(self, store):
        store.save([_candle(2), _candle(0), _candle(1)])
        candles = store.load("BTCUSDT", "1m", _BASE, _BASE + timedelta(minutes=5))
        for i in range(len(candles) - 1):
            assert candles[i].open_time < candles[i + 1].open_time

    def test_load_unknown_symbol_returns_empty(self, store):
        assert store.load("XYZUSDT", "1m", _BASE, _BASE + timedelta(hours=1)) == []

    def test_load_spans_dates(self, store):
        store.save([_candle(0), _day_after_candle(0)])
        start = _BASE
        end   = datetime(2026, 9, 1, 1, 0, 0, tzinfo=timezone.utc)
        loaded = store.load("BTCUSDT", "1m", start, end)
        assert len(loaded) == 2

    def test_load_returns_candle_with_correct_fields(self, store):
        store.save([_candle(0)])
        loaded = store.load("BTCUSDT", "1m", _BASE, _BASE + timedelta(minutes=1))
        assert loaded[0].open_time == _BASE
        assert loaded[0].open  == 100.0
        assert loaded[0].high  == 110.0


class TestOHLCVStoreGetLatest:
    def test_get_latest_returns_most_recent(self, store):
        store.save([_candle(i) for i in range(5)])
        latest = store.get_latest("BTCUSDT", "1m")
        assert latest is not None
        assert latest.open_time == _BASE + timedelta(minutes=4)

    def test_get_latest_returns_none_if_no_data(self, store):
        assert store.get_latest("XYZUSDT", "1m") is None

    def test_get_latest_across_dates(self, store):
        store.save([_candle(0), _day_after_candle(5)])
        latest = store.get_latest("BTCUSDT", "1m")
        expected = datetime(2026, 9, 1, 0, 5, 0, tzinfo=timezone.utc)
        assert latest.open_time == expected


class TestOHLCVStoreCountAndList:
    def test_count_stored(self, store):
        store.save([_candle(i) for i in range(3)])
        count = store.count_stored("BTCUSDT", "1m", _BASE, _BASE + timedelta(minutes=10))
        assert count == 3

    def test_list_symbols(self, store):
        store.save([_candle(0, symbol="BTCUSDT")])
        store.save([_candle(0, symbol="ETHUSDT")])
        symbols = store.list_symbols()
        assert "BTCUSDT" in symbols
        assert "ETHUSDT" in symbols

    def test_list_symbols_empty_store(self, store):
        assert store.list_symbols() == []
