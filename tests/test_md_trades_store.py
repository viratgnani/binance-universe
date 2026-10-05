"""
tests/test_md_trades_store.py

Tests for market_data/trades_store.py

Covers:
  - save() writes new trades
  - save() skips duplicate agg_trade_ids
  - save() splits by UTC date
  - load() returns trades in [start, end]
  - load() empty for unknown symbol
  - get_latest_id() returns max agg_trade_id
  - get_latest_trade() returns most recent trade
  - count_stored() returns correct count
  - list_symbols() lists stored symbols
"""

from __future__ import annotations

from datetime import datetime, timezone, timedelta
from pathlib import Path

import pytest

from market_data.config import MarketDataConfig
from market_data.models import AggTrade
from market_data.trades_store import TradesStore


# ─── Fixtures ─────────────────────────────────────────────────────────────────


@pytest.fixture()
def cfg(tmp_path: Path) -> MarketDataConfig:
    c = MarketDataConfig()
    c.TRADES_DIR = tmp_path / "trades"
    return c


@pytest.fixture()
def store(cfg: MarketDataConfig) -> TradesStore:
    return TradesStore(cfg)


# ─── Helpers ──────────────────────────────────────────────────────────────────

_BASE = datetime(2026, 8, 31, 12, 0, 0, tzinfo=timezone.utc)


def _trade(
    agg_id: int = 1,
    offset_seconds: int = 0,
    symbol: str = "BTCUSDT",
    price: float = 50000.0,
    quantity: float = 0.5,
) -> AggTrade:
    ts = _BASE + timedelta(seconds=offset_seconds)
    return AggTrade(
        symbol=symbol,
        agg_trade_id=agg_id,
        price=price,
        quantity=quantity,
        quote_quantity=price * quantity,
        first_trade_id=agg_id,
        last_trade_id=agg_id,
        timestamp=ts,
        buyer_is_maker=False,
    )


def _next_day_trade(agg_id: int = 1000, offset_seconds: int = 0) -> AggTrade:
    base_next = datetime(2026, 9, 1, 0, 0, 0, tzinfo=timezone.utc)
    ts = base_next + timedelta(seconds=offset_seconds)
    return AggTrade(
        symbol="BTCUSDT",
        agg_trade_id=agg_id,
        price=50000.0,
        quantity=0.5,
        quote_quantity=25000.0,
        first_trade_id=agg_id,
        last_trade_id=agg_id,
        timestamp=ts,
        buyer_is_maker=False,
    )


# ─── Tests ────────────────────────────────────────────────────────────────────


class TestTradesStoreSave:
    def test_save_returns_count(self, store):
        trades = [_trade(i + 1, i * 10) for i in range(5)]
        written, skipped = store.save(trades)
        assert written == 5
        assert skipped == 0

    def test_save_creates_jsonl_file(self, cfg, store):
        store.save([_trade(1)])
        expected = cfg.TRADES_DIR / "BTCUSDT" / "20260831.jsonl"
        assert expected.exists()

    def test_idempotent_save_skips_duplicates(self, store):
        trades = [_trade(i + 1, i * 10) for i in range(3)]
        store.save(trades)
        written2, skipped2 = store.save(trades)
        assert written2 == 0
        assert skipped2 == 3

    def test_partial_duplicate(self, store):
        store.save([_trade(1, 0), _trade(2, 10)])
        written, skipped = store.save([_trade(2, 10), _trade(3, 20)])
        assert written  == 1
        assert skipped  == 1

    def test_multi_date_creates_separate_files(self, cfg, store):
        store.save([_trade(1, 0), _next_day_trade(1000, 0)])
        f1 = cfg.TRADES_DIR / "BTCUSDT" / "20260831.jsonl"
        f2 = cfg.TRADES_DIR / "BTCUSDT" / "20260901.jsonl"
        assert f1.exists()
        assert f2.exists()

    def test_empty_list_returns_zero(self, store):
        w, s = store.save([])
        assert w == 0
        assert s == 0

    def test_saved_trades_sorted_in_file(self, store):
        """Trades provided out-of-order should be sorted before writing."""
        store.save([_trade(3, 20), _trade(1, 0), _trade(2, 10)])
        loaded = store.load(
            "BTCUSDT", _BASE, _BASE + timedelta(hours=1)
        )
        for i in range(len(loaded) - 1):
            assert (loaded[i].timestamp, loaded[i].agg_trade_id) <= \
                   (loaded[i + 1].timestamp, loaded[i + 1].agg_trade_id)


class TestTradesStoreLoad:
    def test_load_returns_all_in_range(self, store):
        trades = [_trade(i + 1, i * 60) for i in range(5)]
        store.save(trades)
        loaded = store.load("BTCUSDT", _BASE, _BASE + timedelta(hours=1))
        assert len(loaded) == 5

    def test_load_filters_by_range(self, store):
        # Trade at 0s, 60s, 120s, 180s, 240s
        trades = [_trade(i + 1, i * 60) for i in range(5)]
        store.save(trades)
        start = _BASE + timedelta(seconds=60)
        end   = _BASE + timedelta(seconds=120)
        loaded = store.load("BTCUSDT", start, end)
        assert len(loaded) == 2

    def test_load_returns_sorted(self, store):
        store.save([_trade(3, 20), _trade(1, 0), _trade(2, 10)])
        loaded = store.load("BTCUSDT", _BASE, _BASE + timedelta(hours=1))
        for i in range(len(loaded) - 1):
            assert loaded[i].agg_trade_id < loaded[i + 1].agg_trade_id

    def test_load_unknown_symbol_returns_empty(self, store):
        result = store.load("XYZUSDT", _BASE, _BASE + timedelta(hours=1))
        assert result == []

    def test_load_spans_dates(self, store):
        store.save([_trade(1, 0), _next_day_trade(1000, 0)])
        start = _BASE
        end   = datetime(2026, 9, 1, 1, 0, 0, tzinfo=timezone.utc)
        loaded = store.load("BTCUSDT", start, end)
        assert len(loaded) == 2

    def test_load_preserves_fields(self, store):
        store.save([_trade(42, 0, price=60000.0, quantity=2.0)])
        loaded = store.load("BTCUSDT", _BASE, _BASE + timedelta(minutes=1))
        assert loaded[0].agg_trade_id == 42
        assert loaded[0].price == 60000.0
        assert loaded[0].quantity == 2.0


class TestTradesStoreLatest:
    def test_get_latest_id_returns_max(self, store):
        store.save([_trade(1, 0), _trade(5, 10), _trade(3, 5)])
        assert store.get_latest_id("BTCUSDT") == 5

    def test_get_latest_id_none_if_empty(self, store):
        assert store.get_latest_id("XYZUSDT") is None

    def test_get_latest_trade_returns_most_recent(self, store):
        store.save([_trade(1, 0), _trade(2, 10), _trade(3, 5)])
        latest = store.get_latest_trade("BTCUSDT")
        assert latest.agg_trade_id == 2  # highest timestamp at 10s

    def test_get_latest_trade_none_if_empty(self, store):
        assert store.get_latest_trade("XYZUSDT") is None

    def test_get_latest_id_across_dates(self, store):
        store.save([_trade(1, 0), _next_day_trade(9999, 0)])
        assert store.get_latest_id("BTCUSDT") == 9999


class TestTradesStoreCountAndList:
    def test_count_stored(self, store):
        store.save([_trade(i + 1, i * 10) for i in range(4)])
        count = store.count_stored("BTCUSDT", _BASE, _BASE + timedelta(hours=1))
        assert count == 4

    def test_list_symbols(self, store):
        store.save([_trade(1, 0, symbol="BTCUSDT")])
        store.save([_trade(2, 0, symbol="ETHUSDT")])
        syms = store.list_symbols()
        assert "BTCUSDT" in syms
        assert "ETHUSDT" in syms

    def test_list_symbols_empty(self, store):
        assert store.list_symbols() == []
