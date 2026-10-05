"""
tests/test_md_models.py

Tests for market_data/models.py

Covers:
  - Candle construction and field types
  - AggTrade construction and computed quote_quantity
  - UTC enforcement on datetime fields
  - Millisecond-epoch timestamp conversion
  - JSONL round-trip serialization
  - Model immutability (fields can still be set — not frozen)
  - ViolationType and Dataset enums
"""

from __future__ import annotations

import json
from datetime import datetime, timezone, timedelta

import pytest

from market_data.models import (
    AggTrade,
    BackfillProgress,
    Candle,
    CollectionError,
    Dataset,
    IntegrityViolation,
    IntervalCoverage,
    QualityReport,
    SymbolResult,
    TradesCoverage,
    ViolationType,
)


# ─── Helpers ──────────────────────────────────────────────────────────────────

_TS = datetime(2026, 8, 31, 12, 0, 0, tzinfo=timezone.utc)
_TS1 = _TS + timedelta(minutes=1)


def _make_candle(**kwargs) -> Candle:
    defaults = dict(
        symbol="BTCUSDT",
        interval="1m",
        open_time=_TS,
        close_time=_TS + timedelta(seconds=59, milliseconds=999),
        open=50000.0,
        high=50100.0,
        low=49900.0,
        close=50050.0,
        volume=10.5,
        quote_volume=525_000.0,
        trade_count=250,
        taker_buy_base_vol=6.0,
        taker_buy_quote_vol=300_000.0,
    )
    defaults.update(kwargs)
    return Candle(**defaults)


def _make_trade(**kwargs) -> AggTrade:
    defaults = dict(
        symbol="BTCUSDT",
        agg_trade_id=1001,
        price=50000.0,
        quantity=0.5,
        quote_quantity=25000.0,
        first_trade_id=2001,
        last_trade_id=2005,
        timestamp=_TS,
        buyer_is_maker=False,
    )
    defaults.update(kwargs)
    return AggTrade(**defaults)


# ─── Candle ───────────────────────────────────────────────────────────────────


class TestCandleModel:
    def test_basic_construction(self):
        c = _make_candle()
        assert c.symbol   == "BTCUSDT"
        assert c.interval == "1m"
        assert c.open     == 50000.0
        assert c.high     == 50100.0
        assert c.low      == 49900.0
        assert c.close    == 50050.0
        assert c.trade_count == 250

    def test_open_time_is_utc_aware(self):
        c = _make_candle()
        assert c.open_time.tzinfo is not None
        assert c.open_time.tzinfo == timezone.utc

    def test_close_time_is_utc_aware(self):
        c = _make_candle()
        assert c.close_time.tzinfo is not None

    def test_collection_time_is_utc_aware(self):
        c = _make_candle()
        assert c.collection_time.tzinfo is not None

    def test_naive_datetime_gets_utc(self):
        """A naive datetime passed to open_time should be made UTC-aware."""
        naive = datetime(2026, 8, 31, 12, 0, 0)  # no tzinfo
        c = _make_candle(open_time=naive)
        assert c.open_time.tzinfo is not None

    def test_iso_string_open_time(self):
        """ISO string timestamps should be accepted and converted."""
        c = _make_candle(open_time="2026-08-31T12:00:00+00:00")
        assert c.open_time == _TS

    def test_iso_z_suffix(self):
        """ISO strings with Z suffix should work."""
        c = _make_candle(open_time="2026-08-31T12:00:00Z")
        assert c.open_time.tzinfo is not None

    def test_jsonl_roundtrip(self):
        """Serialise to JSON, deserialise back — all fields preserved."""
        c  = _make_candle()
        j  = c.model_dump_json()
        c2 = Candle.model_validate_json(j)
        assert c2.symbol      == c.symbol
        assert c2.open_time   == c.open_time
        assert c2.close_time  == c.close_time
        assert c2.open        == c.open
        assert c2.high        == c.high
        assert c2.low         == c.low
        assert c2.close       == c.close
        assert c2.volume      == c.volume
        assert c2.trade_count == c.trade_count

    def test_collection_time_not_required(self):
        """collection_time should be auto-populated if not provided."""
        c = _make_candle()
        assert c.collection_time is not None

    def test_taker_volumes_preserved(self):
        c = _make_candle(taker_buy_base_vol=3.0, taker_buy_quote_vol=150_000.0)
        assert c.taker_buy_base_vol == 3.0
        assert c.taker_buy_quote_vol == 150_000.0


# ─── AggTrade ─────────────────────────────────────────────────────────────────


class TestAggTradeModel:
    def test_basic_construction(self):
        t = _make_trade()
        assert t.symbol       == "BTCUSDT"
        assert t.agg_trade_id == 1001
        assert t.price        == 50000.0
        assert t.quantity     == 0.5
        assert t.buyer_is_maker is False

    def test_timestamp_is_utc_aware(self):
        t = _make_trade()
        assert t.timestamp.tzinfo is not None

    def test_millisecond_epoch_timestamp(self):
        """An integer millisecond epoch should be converted to datetime."""
        epoch_ms = int(_TS.timestamp() * 1000)
        t = _make_trade(timestamp=epoch_ms)
        assert t.timestamp == _TS

    def test_naive_timestamp_gets_utc(self):
        naive = datetime(2026, 8, 31, 12, 0, 0)
        t = _make_trade(timestamp=naive)
        assert t.timestamp.tzinfo is not None

    def test_iso_z_suffix(self):
        t = _make_trade(timestamp="2026-08-31T12:00:00Z")
        assert t.timestamp.tzinfo is not None
        assert t.timestamp == _TS

    def test_buyer_is_maker_false(self):
        t = _make_trade(buyer_is_maker=False)
        assert t.buyer_is_maker is False

    def test_buyer_is_maker_true(self):
        t = _make_trade(buyer_is_maker=True)
        assert t.buyer_is_maker is True

    def test_jsonl_roundtrip(self):
        t  = _make_trade()
        j  = t.model_dump_json()
        t2 = AggTrade.model_validate_json(j)
        assert t2.agg_trade_id == t.agg_trade_id
        assert t2.timestamp    == t.timestamp
        assert t2.price        == t.price
        assert t2.quantity     == t.quantity
        assert t2.buyer_is_maker == t.buyer_is_maker

    def test_quote_quantity_field(self):
        """quote_quantity is caller-supplied (price * qty — no auto-derivation)."""
        t = _make_trade(price=50000.0, quantity=2.0, quote_quantity=100000.0)
        assert t.quote_quantity == 100000.0


# ─── IntegrityViolation ───────────────────────────────────────────────────────


class TestIntegrityViolation:
    def test_construction(self):
        v = IntegrityViolation(
            symbol="BTCUSDT",
            dataset=Dataset.OHLCV,
            interval="1m",
            violation_type=ViolationType.DUPLICATE_CANDLE,
            detail="Duplicate at 12:00:00",
        )
        assert v.symbol         == "BTCUSDT"
        assert v.dataset        == Dataset.OHLCV
        assert v.violation_type == ViolationType.DUPLICATE_CANDLE

    def test_trade_violation_no_interval(self):
        v = IntegrityViolation(
            symbol="ETHUSDT",
            dataset=Dataset.TRADES,
            violation_type=ViolationType.DUPLICATE_TRADE,
            detail="Duplicate agg_trade_id: 999",
        )
        assert v.interval is None


# ─── BackfillProgress ─────────────────────────────────────────────────────────


class TestBackfillProgress:
    def test_initial_state(self):
        p = BackfillProgress(
            symbol="BTCUSDT",
            dataset=Dataset.OHLCV,
            interval="1m",
            requested_start=_TS,
            requested_end=_TS1,
        )
        assert p.is_complete is False
        assert p.last_completed_open_time is None

    def test_jsonl_roundtrip(self):
        p = BackfillProgress(
            symbol="BTCUSDT",
            dataset=Dataset.OHLCV,
            interval="1m",
            requested_start=_TS,
            requested_end=_TS1,
            last_completed_open_time=_TS,
        )
        j  = p.model_dump_json()
        p2 = BackfillProgress.model_validate_json(j)
        assert p2.symbol   == p.symbol
        assert p2.interval == p.interval
        assert p2.last_completed_open_time == _TS


# ─── Dataset / ViolationType enums ────────────────────────────────────────────


class TestEnums:
    def test_dataset_values(self):
        assert Dataset.OHLCV  == "ohlcv"
        assert Dataset.TRADES == "trades"

    def test_violation_types_exist(self):
        for name in (
            "DUPLICATE_CANDLE",
            "MISSING_CANDLE",
            "OUT_OF_ORDER",
            "INVALID_OHLC",
            "INVALID_VOLUME",
            "TIMESTAMP_MISALIGN",
            "DUPLICATE_TRADE",
            "INVALID_TRADE_PRICE",
            "INVALID_TRADE_QTY",
        ):
            assert hasattr(ViolationType, name), f"Missing ViolationType.{name}"
