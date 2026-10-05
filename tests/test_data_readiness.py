"""
tests/test_data_readiness.py

Tests for market_data/readiness.py — ReadinessClassifier and related helpers.

All tests use in-memory mock data or temp directories.
No Binance API calls are made.
No frozen layer modules are modified.
"""

from __future__ import annotations

import tempfile
from datetime import datetime, timezone, timedelta
from pathlib import Path

import pytest

from market_data.config import MarketDataConfig
from market_data.models import Candle
from market_data.ohlcv_store import OHLCVStore
from market_data.readiness import (
    ExperimentReadinessSpec,
    ReadinessClassifier,
    ReadinessStatus,
    SymbolReadiness,
    _compute_max_gap_minutes,
    _sum_missing_candles,
    load_universe_snapshot_status,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

def _make_cfg(tmp_dir: str) -> MarketDataConfig:
    cfg = MarketDataConfig()
    cfg.OHLCV_DIR = Path(tmp_dir) / "ohlcv"
    return cfg


def _make_candle(symbol: str, open_time: datetime, close: float = 100.0) -> Candle:
    return Candle(
        symbol=symbol,
        interval="1m",
        open_time=open_time,
        close_time=open_time + timedelta(seconds=59, milliseconds=999),
        open=close,
        high=close + 0.1,
        low=close - 0.1,
        close=close,
        volume=1000.0,
        quote_volume=100000.0,
        trade_count=100,
        taker_buy_base_vol=500.0,
        taker_buy_quote_vol=50000.0,
        collection_time=datetime.now(timezone.utc),
    )


def _write_candles(
    store: OHLCVStore,
    symbol: str,
    start: datetime,
    count: int,
    gap_after: int | None = None,
) -> list[Candle]:
    """Generate sequential 1m candles and write to store, optionally with a gap."""
    candles = []
    ts = start
    for i in range(count):
        if gap_after is not None and i == gap_after:
            ts += timedelta(minutes=5)  # introduce a 5-minute gap (4 missing)
        candles.append(_make_candle(symbol, ts))
        ts += timedelta(minutes=1)
    store.save(candles)
    return candles


_BASE_TS = datetime(2024, 1, 1, tzinfo=timezone.utc)
_DEFAULT_SPEC = ExperimentReadinessSpec()


# ---------------------------------------------------------------------------
# ExperimentReadinessSpec
# ---------------------------------------------------------------------------

class TestExperimentReadinessSpec:
    def test_default_values(self):
        spec = ExperimentReadinessSpec()
        assert spec.interval == "1m"
        assert spec.rsi_period == 14
        assert spec.rsi_min_candles == 15
        assert spec.preferred_history_days == 30
        assert spec.required_forward_minutes == 10
        assert "BTCUSDT" in spec.exclude_symbols
        assert "ETHUSDT" in spec.exclude_symbols
        assert "SOLUSDT" in spec.exclude_symbols

    def test_immutable(self):
        spec = ExperimentReadinessSpec()
        with pytest.raises((TypeError, AttributeError)):
            spec.rsi_period = 7  # type: ignore

    def test_invalid_rsi_min_candles_raises(self):
        with pytest.raises(ValueError):
            ExperimentReadinessSpec(rsi_period=14, rsi_min_candles=10)  # 10 < 15

    def test_custom_excluded_symbols(self):
        spec = ExperimentReadinessSpec(
            exclude_symbols=frozenset({"BTCUSDT", "ETHUSDT"})
        )
        assert "SOLUSDT" not in spec.exclude_symbols
        assert "BTCUSDT" in spec.exclude_symbols


# ---------------------------------------------------------------------------
# ReadinessClassifier — MISSING
# ---------------------------------------------------------------------------

class TestMissingSymbol:
    def test_missing_no_data_stored(self):
        with tempfile.TemporaryDirectory() as td:
            cfg = _make_cfg(td)
            clf = ReadinessClassifier(cfg)
            result = clf.classify_symbol("XRPUSDT", _DEFAULT_SPEC)
            assert result.status == ReadinessStatus.MISSING
            assert result.candle_count == 0
            assert result.earliest is None
            assert result.latest is None

    def test_missing_returns_zero_counts(self):
        with tempfile.TemporaryDirectory() as td:
            cfg = _make_cfg(td)
            clf = ReadinessClassifier(cfg)
            result = clf.classify_symbol("ADAUSDT", _DEFAULT_SPEC)
            assert result.gaps == 0
            assert result.duplicate_candles == 0
            assert result.invalid_candles == 0
            assert result.coverage_pct == 0.0
            assert result.has_rsi_init is False
            assert result.has_preferred_history is False


# ---------------------------------------------------------------------------
# ReadinessClassifier — EXCLUDED
# ---------------------------------------------------------------------------

class TestExcludedSymbol:
    def test_btc_is_excluded(self):
        with tempfile.TemporaryDirectory() as td:
            cfg = _make_cfg(td)
            store = OHLCVStore(cfg)
            _write_candles(store, "BTCUSDT", _BASE_TS, 50000)  # lots of data
            clf = ReadinessClassifier(cfg)
            result = clf.classify_symbol("BTCUSDT", _DEFAULT_SPEC)
            assert result.status == ReadinessStatus.EXCLUDED

    def test_eth_is_excluded(self):
        with tempfile.TemporaryDirectory() as td:
            cfg = _make_cfg(td)
            clf = ReadinessClassifier(cfg)
            result = clf.classify_symbol("ETHUSDT", _DEFAULT_SPEC)
            assert result.status == ReadinessStatus.EXCLUDED

    def test_sol_is_excluded(self):
        with tempfile.TemporaryDirectory() as td:
            cfg = _make_cfg(td)
            clf = ReadinessClassifier(cfg)
            result = clf.classify_symbol("SOLUSDT", _DEFAULT_SPEC)
            assert result.status == ReadinessStatus.EXCLUDED

    def test_excluded_symbol_not_ready_even_with_data(self):
        with tempfile.TemporaryDirectory() as td:
            cfg = _make_cfg(td)
            store = OHLCVStore(cfg)
            _write_candles(store, "BTCUSDT", _BASE_TS, 100_000)
            clf = ReadinessClassifier(cfg)
            result = clf.classify_symbol("BTCUSDT", _DEFAULT_SPEC)
            assert result.status == ReadinessStatus.EXCLUDED


# ---------------------------------------------------------------------------
# ReadinessClassifier — INCOMPLETE
# ---------------------------------------------------------------------------

class TestIncompleteSymbol:
    def test_fewer_than_rsi_min_candles(self):
        with tempfile.TemporaryDirectory() as td:
            cfg = _make_cfg(td)
            store = OHLCVStore(cfg)
            _write_candles(store, "XRPUSDT", _BASE_TS, 10)  # < 15
            clf = ReadinessClassifier(cfg)
            result = clf.classify_symbol("XRPUSDT", _DEFAULT_SPEC)
            assert result.status == ReadinessStatus.INCOMPLETE
            assert result.has_rsi_init is False

    def test_exactly_rsi_min_candles_but_insufficient_history(self):
        with tempfile.TemporaryDirectory() as td:
            cfg = _make_cfg(td)
            store = OHLCVStore(cfg)
            _write_candles(store, "XRPUSDT", _BASE_TS, 15)  # RSI can init, but only 15 minutes
            clf = ReadinessClassifier(cfg)
            result = clf.classify_symbol("XRPUSDT", _DEFAULT_SPEC)
            assert result.status == ReadinessStatus.INCOMPLETE
            assert result.has_rsi_init is True
            assert result.has_preferred_history is False

    def test_insufficient_history_days(self):
        with tempfile.TemporaryDirectory() as td:
            cfg = _make_cfg(td)
            store = OHLCVStore(cfg)
            _write_candles(store, "XRPUSDT", _BASE_TS, 100)  # 100 minutes < 30 days
            clf = ReadinessClassifier(cfg)
            result = clf.classify_symbol("XRPUSDT", _DEFAULT_SPEC)
            assert result.status == ReadinessStatus.INCOMPLETE
            assert result.has_preferred_history is False


# ---------------------------------------------------------------------------
# ReadinessClassifier — READY
# ---------------------------------------------------------------------------

class TestReadySymbol:
    def test_ready_with_30_days_of_data(self):
        with tempfile.TemporaryDirectory() as td:
            cfg = _make_cfg(td)
            store = OHLCVStore(cfg)
            # 30 days exactly: need 30*1440 + 1 = 43,201 candles
            # (duration = (43200 minutes) = 43200/1440 = 30.0 days exactly)
            _write_candles(store, "XRPUSDT", _BASE_TS, 43_201)
            clf = ReadinessClassifier(cfg)
            result = clf.classify_symbol("XRPUSDT", _DEFAULT_SPEC)
            assert result.status == ReadinessStatus.READY
            assert result.has_rsi_init is True
            assert result.has_preferred_history is True
            assert result.candle_count == 43_201

    def test_ready_symbol_reports_correct_duration(self):
        with tempfile.TemporaryDirectory() as td:
            cfg = _make_cfg(td)
            store = OHLCVStore(cfg)
            n = 43_201  # 43200 minutes = exactly 30.0 days
            _write_candles(store, "XRPUSDT", _BASE_TS, n)
            clf = ReadinessClassifier(cfg)
            result = clf.classify_symbol("XRPUSDT", _DEFAULT_SPEC)
            assert result.duration_days == pytest.approx(30.0, abs=0.01)

    def test_ready_symbol_has_full_coverage(self):
        with tempfile.TemporaryDirectory() as td:
            cfg = _make_cfg(td)
            store = OHLCVStore(cfg)
            _write_candles(store, "XRPUSDT", _BASE_TS, 43_201)
            clf = ReadinessClassifier(cfg)
            result = clf.classify_symbol("XRPUSDT", _DEFAULT_SPEC)
            assert result.coverage_pct == pytest.approx(100.0, abs=0.1)
            assert result.gaps == 0
            assert result.missing_candles == 0


# ---------------------------------------------------------------------------
# ReadinessClassifier — Gap detection
# ---------------------------------------------------------------------------

class TestGapDetection:
    def test_gap_detected_and_counted(self):
        with tempfile.TemporaryDirectory() as td:
            cfg = _make_cfg(td)
            store = OHLCVStore(cfg)
            # Write 43201 candles with a 5-minute gap after candle 1000
            _write_candles(store, "XRPUSDT", _BASE_TS, 43_201, gap_after=1000)
            clf = ReadinessClassifier(cfg)
            result = clf.classify_symbol("XRPUSDT", _DEFAULT_SPEC)
            assert result.gaps >= 1
            assert result.missing_candles >= 4  # 5 min gap = 4 missing

    def test_max_gap_minutes_reported(self):
        with tempfile.TemporaryDirectory() as td:
            cfg = _make_cfg(td)
            store = OHLCVStore(cfg)
            _write_candles(store, "XRPUSDT", _BASE_TS, 43_201, gap_after=1000)
            clf = ReadinessClassifier(cfg)
            result = clf.classify_symbol("XRPUSDT", _DEFAULT_SPEC)
            assert result.max_gap_minutes >= 4

    def test_no_gap_when_continuous(self):
        with tempfile.TemporaryDirectory() as td:
            cfg = _make_cfg(td)
            store = OHLCVStore(cfg)
            _write_candles(store, "XRPUSDT", _BASE_TS, 1000)
            clf = ReadinessClassifier(cfg)
            result = clf.classify_symbol("XRPUSDT", _DEFAULT_SPEC)
            assert result.gaps == 0
            assert result.max_gap_minutes == 0


# ---------------------------------------------------------------------------
# Aggregate summary
# ---------------------------------------------------------------------------

class TestClassifyAll:
    def test_aggregate_counts_correct(self):
        with tempfile.TemporaryDirectory() as td:
            cfg = _make_cfg(td)
            store = OHLCVStore(cfg)
            # XRP: READY (43,201 candles = exactly 30 days)
            _write_candles(store, "XRPUSDT", _BASE_TS, 43_201)
            # BNB: INCOMPLETE (10 candles)
            _write_candles(store, "BNBUSDT", _BASE_TS, 10)
            clf = ReadinessClassifier(cfg)
            spec = ExperimentReadinessSpec(exclude_symbols=frozenset())  # nothing excluded
            summary = clf.classify_all(["XRPUSDT", "BNBUSDT", "MISSINGUSDT"], spec)
            assert summary.symbols_ready == 1
            assert summary.symbols_incomplete == 1
            assert summary.symbols_missing == 1
            assert summary.symbols_evaluated == 3

    def test_excluded_counted_separately(self):
        with tempfile.TemporaryDirectory() as td:
            cfg = _make_cfg(td)
            clf = ReadinessClassifier(cfg)
            summary = clf.classify_all(["BTCUSDT", "XRPUSDT"], _DEFAULT_SPEC)
            assert summary.symbols_excluded == 1   # BTC
            assert summary.symbols_missing == 1    # XRP

    def test_total_candles_aggregated(self):
        with tempfile.TemporaryDirectory() as td:
            cfg = _make_cfg(td)
            store = OHLCVStore(cfg)
            _write_candles(store, "XRPUSDT", _BASE_TS, 100)
            _write_candles(store, "ADAUSDT", _BASE_TS, 200)
            clf = ReadinessClassifier(cfg)
            spec = ExperimentReadinessSpec(exclude_symbols=frozenset())
            summary = clf.classify_all(["XRPUSDT", "ADAUSDT"], spec)
            assert summary.total_candles == 300

    def test_global_date_bounds_correct(self):
        with tempfile.TemporaryDirectory() as td:
            cfg = _make_cfg(td)
            store = OHLCVStore(cfg)
            start_a = datetime(2024, 1, 1, tzinfo=timezone.utc)
            start_b = datetime(2024, 2, 1, tzinfo=timezone.utc)
            _write_candles(store, "XRPUSDT", start_a, 100)
            _write_candles(store, "ADAUSDT", start_b, 100)
            clf = ReadinessClassifier(cfg)
            spec = ExperimentReadinessSpec(exclude_symbols=frozenset())
            summary = clf.classify_all(["XRPUSDT", "ADAUSDT"], spec)
            assert summary.earliest_global == start_a
            assert summary.latest_global >= start_b

    def test_experiment_ready_false_when_zero_ready(self):
        with tempfile.TemporaryDirectory() as td:
            cfg = _make_cfg(td)
            clf = ReadinessClassifier(cfg)
            spec = ExperimentReadinessSpec(exclude_symbols=frozenset())
            summary = clf.classify_all(["XRPUSDT"], spec)
            assert summary.experiment_ready is False

    def test_experiment_ready_true_when_any_ready(self):
        with tempfile.TemporaryDirectory() as td:
            cfg = _make_cfg(td)
            store = OHLCVStore(cfg)
            _write_candles(store, "XRPUSDT", _BASE_TS, 43_201)
            clf = ReadinessClassifier(cfg)
            spec = ExperimentReadinessSpec(exclude_symbols=frozenset())
            summary = clf.classify_all(["XRPUSDT"], spec)
            assert summary.experiment_ready is True


# ---------------------------------------------------------------------------
# coverage_pct calculation
# ---------------------------------------------------------------------------

class TestCoveragePct:
    def test_full_coverage_is_100(self):
        with tempfile.TemporaryDirectory() as td:
            cfg = _make_cfg(td)
            store = OHLCVStore(cfg)
            _write_candles(store, "XRPUSDT", _BASE_TS, 1440)  # 1 day exactly
            clf = ReadinessClassifier(cfg)
            result = clf.classify_symbol("XRPUSDT", _DEFAULT_SPEC)
            assert result.coverage_pct == pytest.approx(100.0, abs=0.1)

    def test_coverage_proportional_to_stored(self):
        with tempfile.TemporaryDirectory() as td:
            cfg = _make_cfg(td)
            store = OHLCVStore(cfg)
            # Write 500 out of expected 1000 (50% coverage)
            candles = [_make_candle("XRPUSDT", _BASE_TS + timedelta(minutes=i * 2)) for i in range(500)]
            store.save(candles)
            clf = ReadinessClassifier(cfg)
            result = clf.classify_symbol("XRPUSDT", _DEFAULT_SPEC)
            # Coverage < 100% because we have gaps
            assert result.coverage_pct < 100.0


# ---------------------------------------------------------------------------
# Universe snapshot status
# ---------------------------------------------------------------------------

class TestUniverseSnapshotStatus:
    def test_no_snapshot_returns_not_found(self, monkeypatch, tmp_path):
        monkeypatch.chdir(tmp_path)
        status = load_universe_snapshot_status()
        assert status["snapshot_found"] is False
        assert status["historical_ranked_available"] is False
        assert status["limitation"] is not None

    def test_snapshot_with_no_ranks_reports_limitation(self, tmp_path, monkeypatch):
        import json
        monkeypatch.chdir(tmp_path)
        snap_dir = tmp_path / "data" / "snapshots"
        snap_dir.mkdir(parents=True)
        snap_file = snap_dir / "snapshot_20240101.jsonl"
        records = [
            {"record_type": "HEADER", "snapshot_timestamp": "2024-01-01T00:00:00Z",
             "snapshot_id": "20240101T000000Z", "total_eligible": 2, "total_ranked": 0,
             "total_failed": 0, "top_n": 100},
            {"record_type": "DATA", "symbol": "XRPUSDT", "rank": None, "score": None,
             "universe_status": "WATCHLIST", "snapshot_timestamp": "2024-01-01T00:00:00Z",
             "snapshot_id": "20240101T000000Z", "volume_24h_quote": 1e9,
             "open_interest": 1e8, "spread_bps": None, "metrics_failed": False},
        ]
        snap_file.write_text("\n".join(json.dumps(r) for r in records), encoding="utf-8")
        status = load_universe_snapshot_status()
        assert status["snapshot_found"] is True
        assert status["ranked_count"] == 0
        assert status["historical_ranked_available"] is False
        assert status["limitation"] is not None
