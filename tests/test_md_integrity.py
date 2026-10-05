"""
tests/test_md_integrity.py

Tests for market_data/integrity.py

Covers all 8 check functions:
  - check_candle_duplicates
  - check_candle_gaps
  - check_candle_sort_order
  - check_ohlc_validity
  - check_timestamp_alignment
  - check_trade_duplicates
  - check_trade_validity
  - check_trade_sort_order
  - run_all_candle_checks (convenience wrapper)
  - run_all_trade_checks  (convenience wrapper)
"""

from __future__ import annotations

from datetime import datetime, timezone, timedelta

import pytest

from market_data.integrity import (
    check_candle_duplicates,
    check_candle_gaps,
    check_candle_sort_order,
    check_ohlc_validity,
    check_timestamp_alignment,
    check_trade_duplicates,
    check_trade_sort_order,
    check_trade_validity,
    run_all_candle_checks,
    run_all_trade_checks,
)
from market_data.models import ViolationType


# ─── Shared factory helpers ───────────────────────────────────────────────────

_BASE = datetime(2026, 8, 31, 12, 0, 0, tzinfo=timezone.utc)
_1M   = timedelta(minutes=1)


def _candle(offset_minutes: int = 0, **kwargs):
    """Create a minimal valid candle."""
    from market_data.models import Candle
    ts = _BASE + timedelta(minutes=offset_minutes)
    defaults = dict(
        symbol="BTCUSDT",
        interval="1m",
        open_time=ts,
        close_time=ts + timedelta(seconds=59, milliseconds=999),
        open=100.0, high=110.0, low=90.0, close=105.0,
        volume=1.0, quote_volume=100.0, trade_count=10,
        taker_buy_base_vol=0.5, taker_buy_quote_vol=50.0,
    )
    defaults.update(kwargs)
    return Candle(**defaults)


def _trade(agg_id: int = 1, offset_seconds: int = 0, **kwargs):
    """Create a minimal valid trade."""
    from market_data.models import AggTrade
    ts = _BASE + timedelta(seconds=offset_seconds)
    defaults = dict(
        symbol="BTCUSDT",
        agg_trade_id=agg_id,
        price=100.0,
        quantity=1.0,
        quote_quantity=100.0,
        first_trade_id=agg_id,
        last_trade_id=agg_id,
        timestamp=ts,
        buyer_is_maker=False,
    )
    defaults.update(kwargs)
    return AggTrade(**defaults)


# ─── check_candle_duplicates ──────────────────────────────────────────────────


class TestCheckCandleDuplicates:
    def test_no_duplicates_returns_empty(self):
        candles = [_candle(0), _candle(1), _candle(2)]
        assert check_candle_duplicates(candles) == []

    def test_single_duplicate_detected(self):
        candles = [_candle(0), _candle(1), _candle(1)]  # duplicate minute 1
        violations = check_candle_duplicates(candles)
        assert len(violations) == 1
        assert violations[0].violation_type == ViolationType.DUPLICATE_CANDLE

    def test_multiple_duplicates_detected(self):
        candles = [_candle(0), _candle(0), _candle(0)]  # 2 extra
        violations = check_candle_duplicates(candles)
        assert len(violations) == 2

    def test_empty_list_returns_empty(self):
        assert check_candle_duplicates([]) == []

    def test_single_candle_returns_empty(self):
        assert check_candle_duplicates([_candle(0)]) == []

    def test_violation_contains_timestamp(self):
        candles = [_candle(0), _candle(0)]
        v = check_candle_duplicates(candles)[0]
        assert "12:00:00" in v.detail or "open_time" in v.detail.lower() or _BASE.isoformat() in v.detail


# ─── check_candle_gaps ────────────────────────────────────────────────────────


class TestCheckCandleGaps:
    def test_no_gaps_returns_empty(self):
        candles = [_candle(0), _candle(1), _candle(2), _candle(3)]
        assert check_candle_gaps(candles, "1m") == []

    def test_single_gap_detected(self):
        # 12:00, 12:01, 12:03 — missing 12:02
        candles = [_candle(0), _candle(1), _candle(3)]
        violations = check_candle_gaps(candles, "1m")
        assert len(violations) == 1
        assert violations[0].violation_type == ViolationType.MISSING_CANDLE

    def test_gap_detail_mentions_count(self):
        # 12:00, 12:05 — missing 12:01, 12:02, 12:03, 12:04 (4 gaps)
        candles = [_candle(0), _candle(5)]
        violations = check_candle_gaps(candles, "1m")
        assert len(violations) == 1
        assert "4" in violations[0].detail

    def test_unsorted_input_handled(self):
        # Provide out-of-order; function should sort internally
        candles = [_candle(2), _candle(0), _candle(1)]
        assert check_candle_gaps(candles, "1m") == []

    def test_5m_interval_gap(self):
        # 12:00, 12:05, 12:15 — missing 12:10
        from market_data.models import Candle
        c0 = _candle(0)
        object.__setattr__(c0, "interval", "5m")
        c1 = _candle(5)
        object.__setattr__(c1, "interval", "5m")
        c2 = _candle(15)
        object.__setattr__(c2, "interval", "5m")
        violations = check_candle_gaps([c0, c1, c2], "5m")
        assert len(violations) == 1
        assert "5m" in violations[0].interval  # violation carries interval

    def test_two_gaps_gives_two_violations(self):
        # 12:00, 12:02, 12:04 — missing 12:01 and 12:03
        candles = [_candle(0), _candle(2), _candle(4)]
        violations = check_candle_gaps(candles, "1m")
        assert len(violations) == 2

    def test_single_candle_no_gap(self):
        assert check_candle_gaps([_candle(0)], "1m") == []

    def test_empty_list_returns_empty(self):
        assert check_candle_gaps([], "1m") == []


# ─── check_candle_sort_order ──────────────────────────────────────────────────


class TestCheckCandleSortOrder:
    def test_sorted_returns_empty(self):
        candles = [_candle(0), _candle(1), _candle(2)]
        assert check_candle_sort_order(candles) == []

    def test_single_inversion_detected(self):
        candles = [_candle(1), _candle(0), _candle(2)]  # 1 > 0 → inversion
        violations = check_candle_sort_order(candles)
        assert len(violations) == 1
        assert violations[0].violation_type == ViolationType.OUT_OF_ORDER

    def test_fully_reversed_returns_violations(self):
        candles = [_candle(2), _candle(1), _candle(0)]
        violations = check_candle_sort_order(candles)
        assert len(violations) == 2  # position 0>1 and 1>2

    def test_empty_returns_empty(self):
        assert check_candle_sort_order([]) == []

    def test_one_candle_returns_empty(self):
        assert check_candle_sort_order([_candle(0)]) == []


# ─── check_ohlc_validity ──────────────────────────────────────────────────────


class TestCheckOHLCValidity:
    def test_valid_candle_returns_empty(self):
        c = _candle()  # high=110, low=90, open=100, close=105 — all valid
        assert check_ohlc_validity([c]) == []

    def test_high_less_than_low(self):
        c = _candle(high=80.0, low=90.0)  # high < low — impossible
        violations = check_ohlc_validity([c])
        assert any(v.violation_type == ViolationType.INVALID_OHLC for v in violations)

    def test_high_less_than_open(self):
        c = _candle(open=115.0, high=110.0, low=90.0, close=105.0)
        violations = check_ohlc_validity([c])
        assert len(violations) == 1

    def test_high_less_than_close(self):
        c = _candle(open=100.0, high=104.0, low=90.0, close=105.0)  # high < close
        violations = check_ohlc_validity([c])
        assert len(violations) == 1

    def test_low_greater_than_open(self):
        c = _candle(open=85.0, high=110.0, low=90.0, close=105.0)  # low > open
        violations = check_ohlc_validity([c])
        assert len(violations) == 1

    def test_low_greater_than_close(self):
        c = _candle(open=100.0, high=110.0, low=90.0, close=85.0)  # low > close
        violations = check_ohlc_validity([c])
        assert len(violations) == 1

    def test_negative_volume(self):
        c = _candle(volume=-1.0)
        violations = check_ohlc_validity([c])
        assert len(violations) == 1

    def test_multiple_bad_candles(self):
        good = _candle(0)
        bad1 = _candle(1, high=80.0, low=90.0)
        bad2 = _candle(2, volume=-5.0)
        violations = check_ohlc_validity([good, bad1, bad2])
        assert len(violations) == 2

    def test_doji_candle_is_valid(self):
        """open == close == high == low is valid (zero-range doji)."""
        c = _candle(open=100.0, high=100.0, low=100.0, close=100.0)
        assert check_ohlc_validity([c]) == []

    def test_empty_list_returns_empty(self):
        assert check_ohlc_validity([]) == []


# ─── check_timestamp_alignment ───────────────────────────────────────────────


class TestCheckTimestampAlignment:
    def test_aligned_1m_returns_empty(self):
        """12:00:00, 12:01:00, 12:02:00 are all on 1-minute boundaries."""
        candles = [_candle(0), _candle(1), _candle(2)]
        assert check_timestamp_alignment(candles, "1m") == []

    def test_misaligned_returns_violation(self):
        """A candle at 12:00:30 (30s offset) is not on a 1m boundary."""
        from market_data.models import Candle
        ts_misaligned = _BASE + timedelta(seconds=30)
        c = _candle()
        # Override open_time directly
        c2 = Candle(
            symbol="BTCUSDT",
            interval="1m",
            open_time=ts_misaligned,
            close_time=ts_misaligned + timedelta(seconds=29),
            open=100.0, high=110.0, low=90.0, close=105.0,
            volume=1.0, quote_volume=100.0, trade_count=10,
            taker_buy_base_vol=0.5, taker_buy_quote_vol=50.0,
        )
        violations = check_timestamp_alignment([c2], "1m")
        assert len(violations) == 1
        assert violations[0].violation_type == ViolationType.TIMESTAMP_MISALIGN

    def test_unknown_interval_raises(self):
        c = _candle()
        with pytest.raises(ValueError, match="Unknown interval"):
            check_timestamp_alignment([c], "99x")

    def test_empty_returns_empty(self):
        assert check_timestamp_alignment([], "1m") == []


# ─── check_trade_duplicates ───────────────────────────────────────────────────


class TestCheckTradeDuplicates:
    def test_no_duplicates(self):
        trades = [_trade(1), _trade(2), _trade(3)]
        assert check_trade_duplicates(trades) == []

    def test_single_duplicate(self):
        trades = [_trade(1), _trade(2), _trade(2)]  # id 2 duplicated
        violations = check_trade_duplicates(trades)
        assert len(violations) == 1
        assert violations[0].violation_type == ViolationType.DUPLICATE_TRADE

    def test_multiple_duplicates(self):
        trades = [_trade(1), _trade(1), _trade(1)]
        violations = check_trade_duplicates(trades)
        assert len(violations) == 2

    def test_empty_returns_empty(self):
        assert check_trade_duplicates([]) == []


# ─── check_trade_validity ─────────────────────────────────────────────────────


class TestCheckTradeValidity:
    def test_valid_trade_returns_empty(self):
        assert check_trade_validity([_trade()]) == []

    def test_zero_price(self):
        t = _trade(price=0.0)
        violations = check_trade_validity([t])
        assert len(violations) == 1
        assert violations[0].violation_type in (
            ViolationType.INVALID_TRADE_PRICE, ViolationType.INVALID_TRADE_QTY
        )

    def test_negative_price(self):
        t = _trade(price=-1.0)
        violations = check_trade_validity([t])
        assert len(violations) == 1

    def test_zero_quantity(self):
        t = _trade(quantity=0.0)
        violations = check_trade_validity([t])
        assert len(violations) == 1

    def test_future_timestamp(self):
        future = datetime.now(tz=timezone.utc) + timedelta(hours=2)
        t = _trade(timestamp=future)
        violations = check_trade_validity([t])
        assert len(violations) == 1

    def test_pre_binance_timestamp(self):
        """Timestamp before Jan 2019 (Binance Futures launch) should be invalid."""
        ancient = datetime(2010, 1, 1, tzinfo=timezone.utc)
        t = _trade(timestamp=ancient)
        violations = check_trade_validity([t])
        assert len(violations) == 1

    def test_empty_returns_empty(self):
        assert check_trade_validity([]) == []


# ─── check_trade_sort_order ───────────────────────────────────────────────────


class TestCheckTradeSortOrder:
    def test_sorted_returns_empty(self):
        trades = [_trade(1, 0), _trade(2, 1), _trade(3, 2)]
        assert check_trade_sort_order(trades) == []

    def test_out_of_order_detected(self):
        trades = [_trade(2, 1), _trade(1, 0), _trade(3, 2)]  # t[0] > t[1]
        violations = check_trade_sort_order(trades)
        assert len(violations) == 1
        assert violations[0].violation_type == ViolationType.OUT_OF_ORDER

    def test_empty_returns_empty(self):
        assert check_trade_sort_order([]) == []


# ─── run_all_candle_checks (wrapper) ──────────────────────────────────────────


class TestRunAllCandleChecks:
    def test_clean_data_returns_empty(self):
        candles = [_candle(i) for i in range(5)]
        assert run_all_candle_checks(candles, "1m") == []

    def test_multiple_issue_types_detected(self):
        good = _candle(0)
        dup  = _candle(0)              # duplicate of candle 0
        bad  = _candle(2, high=50.0, low=90.0)  # gap at 1, invalid OHLC
        violations = run_all_candle_checks([good, dup, bad], "1m")
        # Should have: duplicate, gap, invalid OHLC (at minimum)
        vtypes = {v.violation_type for v in violations}
        assert ViolationType.DUPLICATE_CANDLE in vtypes
        assert ViolationType.MISSING_CANDLE   in vtypes
        assert ViolationType.INVALID_OHLC     in vtypes

    def test_empty_returns_empty(self):
        assert run_all_candle_checks([], "1m") == []


# ─── run_all_trade_checks (wrapper) ───────────────────────────────────────────


class TestRunAllTradeChecks:
    def test_clean_data_returns_empty(self):
        trades = [_trade(i + 1, i) for i in range(5)]
        assert run_all_trade_checks(trades) == []

    def test_empty_returns_empty(self):
        assert run_all_trade_checks([]) == []
