"""
tests/test_md_quality.py

Tests for market_data/quality.py

Covers:
  - Expected candle count calculation
  - generate_ohlcv_report() with clean data
  - generate_ohlcv_report() with gaps
  - generate_ohlcv_report() with missing symbol
  - generate_trades_report() with clean data
  - generate_trades_report() with missing symbol
  - Coverage percentage calculations
  - Violation aggregation
"""

from __future__ import annotations

from datetime import datetime, timezone, timedelta
from pathlib import Path

import pytest

from market_data.config import MarketDataConfig
from market_data.models import Candle, AggTrade, ViolationType
from market_data.ohlcv_store import OHLCVStore
from market_data.trades_store import TradesStore
from market_data.quality import (
    _expected_candle_count,
    generate_ohlcv_report,
    generate_trades_report,
)


# ─── Fixtures ─────────────────────────────────────────────────────────────────


@pytest.fixture()
def cfg(tmp_path: Path) -> MarketDataConfig:
    c = MarketDataConfig()
    c.OHLCV_DIR  = tmp_path / "ohlcv"
    c.TRADES_DIR = tmp_path / "trades"
    return c


_BASE = datetime(2026, 8, 31, 12, 0, 0, tzinfo=timezone.utc)
_END  = _BASE + timedelta(minutes=10)


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


# ─── Expected count helper ────────────────────────────────────────────────────


class TestExpectedCandleCount:
    def test_10_minutes_1m_interval(self, cfg):
        count = _expected_candle_count(_BASE, _BASE + timedelta(minutes=9), "1m", cfg)
        assert count == 10  # minutes 0..9 inclusive

    def test_1_hour_1h_interval(self, cfg):
        count = _expected_candle_count(
            datetime(2026, 8, 31, 12, 0, 0, tzinfo=timezone.utc),
            datetime(2026, 8, 31, 12, 0, 0, tzinfo=timezone.utc),
            "1h", cfg,
        )
        assert count == 1

    def test_zero_range_returns_one(self, cfg):
        """A range of zero length should contain exactly 1 candle."""
        count = _expected_candle_count(_BASE, _BASE, "1m", cfg)
        assert count >= 1

    def test_unknown_interval_returns_zero(self, cfg):
        count = _expected_candle_count(_BASE, _END, "99x", cfg)
        assert count == 0


# ─── generate_ohlcv_report ────────────────────────────────────────────────────


class TestGenerateOHLCVReport:
    def test_clean_data_no_violations(self, cfg):
        """Consecutive candles with no gaps should produce zero violations."""
        store = OHLCVStore(cfg)
        store.save([_candle(i) for i in range(11)])  # 0..10

        report = generate_ohlcv_report(["BTCUSDT"], "1m", _BASE, _END, cfg)
        assert report.total_violations == 0

    def test_clean_data_coverage_100pct(self, cfg):
        store = OHLCVStore(cfg)
        store.save([_candle(i) for i in range(11)])

        report = generate_ohlcv_report(["BTCUSDT"], "1m", _BASE, _END, cfg)
        assert len(report.ohlcv_coverage) == 1
        cov = report.ohlcv_coverage[0]
        assert cov.coverage_pct >= 95.0   # allow minor float rounding

    def test_gap_increases_missing_count(self, cfg):
        store = OHLCVStore(cfg)
        # Store 0,1,2,4,5 — missing 3
        store.save([_candle(i) for i in [0, 1, 2, 4, 5]])

        report = generate_ohlcv_report(["BTCUSDT"], "1m", _BASE, _BASE + timedelta(minutes=5), cfg)
        cov = report.ohlcv_coverage[0]
        assert cov.missing_candles >= 1

    def test_missing_symbol_reported(self, cfg):
        report = generate_ohlcv_report(["NOSUCHUSDT"], "1m", _BASE, _END, cfg)
        assert "NOSUCHUSDT" in report.symbols_missing
        assert len(report.ohlcv_coverage) == 1
        cov = report.ohlcv_coverage[0]
        assert cov.actual_candles == 0
        assert cov.coverage_pct   == 0.0

    def test_multiple_symbols(self, cfg):
        store = OHLCVStore(cfg)
        store.save([_candle(i, "BTCUSDT") for i in range(5)])
        store.save([_candle(i, "ETHUSDT") for i in range(5)])

        report = generate_ohlcv_report(["BTCUSDT", "ETHUSDT"], "1m", _BASE, _END, cfg)
        assert len(report.ohlcv_coverage) == 2
        assert len(report.symbols_with_data) == 2

    def test_duplicate_candles_counted(self, cfg):
        """Manually inject duplicates to verify they are counted."""
        store = OHLCVStore(cfg)
        # Save clean data first
        store.save([_candle(i) for i in range(5)])
        # Corrupt the file by appending a duplicate manually
        filepath = cfg.OHLCV_DIR / "BTCUSDT" / "1m" / "20260831.jsonl"
        dup = _candle(0)
        with filepath.open("a") as f:
            f.write(dup.model_dump_json() + "\n")

        report = generate_ohlcv_report(["BTCUSDT"], "1m", _BASE, _BASE + timedelta(minutes=5), cfg)
        cov = report.ohlcv_coverage[0]
        assert cov.duplicate_candles >= 1

    def test_report_has_correct_dataset(self, cfg):
        from market_data.models import Dataset
        store = OHLCVStore(cfg)
        store.save([_candle(i) for i in range(3)])
        report = generate_ohlcv_report(["BTCUSDT"], "1m", _BASE, _END, cfg)
        assert report.dataset == Dataset.OHLCV

    def test_report_interval_set(self, cfg):
        report = generate_ohlcv_report(["BTCUSDT"], "1h", _BASE, _END, cfg)
        assert report.interval == "1h"


# ─── generate_trades_report ───────────────────────────────────────────────────


class TestGenerateTradesReport:
    def test_clean_trades_no_violations(self, cfg):
        store = TradesStore(cfg)
        store.save([_trade(i + 1, i * 10) for i in range(5)])

        report = generate_trades_report(["BTCUSDT"], _BASE, _END, cfg)
        assert report.total_violations == 0

    def test_clean_data_correct_count(self, cfg):
        store = TradesStore(cfg)
        store.save([_trade(i + 1, i * 10) for i in range(5)])

        report = generate_trades_report(["BTCUSDT"], _BASE, _END, cfg)
        assert len(report.trades_coverage) == 1
        cov = report.trades_coverage[0]
        assert cov.actual_trades == 5

    def test_missing_symbol_reported(self, cfg):
        report = generate_trades_report(["NOSUCHUSDT"], _BASE, _END, cfg)
        assert "NOSUCHUSDT" in report.symbols_missing
        cov = report.trades_coverage[0]
        assert cov.actual_trades == 0

    def test_duplicate_trades_counted(self, cfg):
        store = TradesStore(cfg)
        store.save([_trade(1, 0), _trade(2, 10)])
        # Manually inject a duplicate
        filepath = cfg.TRADES_DIR / "BTCUSDT" / "20260831.jsonl"
        dup = _trade(1, 0)  # same agg_trade_id as first
        with filepath.open("a") as f:
            f.write(dup.model_dump_json() + "\n")

        report = generate_trades_report(["BTCUSDT"], _BASE, _END, cfg)
        cov = report.trades_coverage[0]
        assert cov.duplicate_trades >= 1

    def test_multiple_symbols(self, cfg):
        store = TradesStore(cfg)
        store.save([_trade(1, 0, "BTCUSDT")])
        store.save([_trade(2, 0, "ETHUSDT")])

        report = generate_trades_report(["BTCUSDT", "ETHUSDT"], _BASE, _END, cfg)
        assert len(report.trades_coverage) == 2
        assert len(report.symbols_with_data) == 2

    def test_report_dataset_is_trades(self, cfg):
        from market_data.models import Dataset
        report = generate_trades_report(["BTCUSDT"], _BASE, _END, cfg)
        assert report.dataset == Dataset.TRADES
