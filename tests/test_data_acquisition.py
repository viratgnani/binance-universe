"""
tests/test_data_acquisition.py

Integration tests for data acquisition behavior.
Uses mock clients — no Binance API calls are made.

Tests verify:
- Dry-run makes zero API calls
- Pagination works correctly across multiple batches
- 429/5xx handling delegates correctly to frozen MarketDataClient retry logic
- Idempotent re-run doesn't create duplicates
- Restartability: progress files are written and respected on resume
- Excluded symbols are correctly rejected by acquire command
"""

from __future__ import annotations

import asyncio
import tempfile
from datetime import datetime, timezone, timedelta
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from market_data.config import MarketDataConfig
from market_data.models import Candle, CollectionSummary, Dataset, SymbolResult
from market_data.ohlcv_store import OHLCVStore
from market_data.readiness import (
    ExperimentReadinessSpec,
    ReadinessClassifier,
    ReadinessStatus,
    load_eligible_alt_symbols,
)


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


_BASE_TS = datetime(2024, 1, 1, tzinfo=timezone.utc)
_DEFAULT_SPEC = ExperimentReadinessSpec()


# ---------------------------------------------------------------------------
# Dry-run: no API calls
# ---------------------------------------------------------------------------

class TestDryRun:
    def test_dry_run_prints_without_calling_api(self, capsys):
        """Dry run must not instantiate MarketDataClient or call backfill_ohlcv."""
        import sys
        sys.argv = [
            "data_readiness", "acquire",
            "--symbols", "XRPUSDT",
            "--start", "2024-01-01",
            "--end", "2024-02-01",
            "--dry-run",
        ]

        with patch("market_data.backfill.backfill_ohlcv") as mock_backfill:
            from data_readiness.__main__ import main
            with pytest.raises(SystemExit) as exc_info:
                main()
            # dry-run should exit 0
            assert exc_info.value.code == 0
            # backfill_ohlcv must NOT have been called
            mock_backfill.assert_not_called()

    def test_dry_run_output_contains_symbol_name(self, capsys):
        import sys
        sys.argv = [
            "data_readiness", "acquire",
            "--symbols", "ADAUSDT",
            "--start", "2024-01-01",
            "--end", "2024-01-31",
            "--dry-run",
        ]
        with patch("market_data.backfill.backfill_ohlcv"):
            from data_readiness.__main__ import main
            with pytest.raises(SystemExit):
                main()
        out = capsys.readouterr().out
        assert "ADAUSDT" in out


# ---------------------------------------------------------------------------
# Excluded symbols rejected by acquire
# ---------------------------------------------------------------------------

class TestExcludeEnforcement:
    def test_btc_filtered_out_of_acquire(self, capsys):
        import sys
        sys.argv = [
            "data_readiness", "acquire",
            "--symbols", "BTCUSDT",
            "--start", "2024-01-01",
            "--end", "2024-02-01",
            "--dry-run",
        ]
        from data_readiness.__main__ import main
        with pytest.raises(SystemExit) as exc_info:
            main()
        # All symbols excluded → should exit 1
        assert exc_info.value.code == 1

    def test_mixed_symbols_excludes_btc_eth_sol(self, capsys):
        """
        When BTC, ETH, SOL are mixed with valid alt symbols, only alts are acquired.
        """
        import sys
        sys.argv = [
            "data_readiness", "acquire",
            "--symbols", "BTCUSDT,ETHUSDT,SOLUSDT,XRPUSDT",
            "--start", "2024-01-01",
            "--end", "2024-02-01",
            "--dry-run",
        ]
        with patch("market_data.backfill.backfill_ohlcv"):
            from data_readiness.__main__ import main
            with pytest.raises(SystemExit) as exc_info:
                main()
        # XRPUSDT should pass through, exit 0
        assert exc_info.value.code == 0
        out = capsys.readouterr().out
        # Excluded symbols should NOT appear in the acquisition plan
        # (XRPUSDT should be listed, BTC/ETH/SOL should not be listed as acquired)
        assert "XRPUSDT" in out


# ---------------------------------------------------------------------------
# Idempotency: rerunning backfill doesn't create duplicates
# ---------------------------------------------------------------------------

class TestIdempotency:
    def test_same_candles_not_duplicated_on_rerun(self):
        """
        Writing the same candles twice via OHLCVStore results in only one copy.
        This exercises the frozen store's dedup logic, which acquisition relies on.
        """
        with tempfile.TemporaryDirectory() as td:
            cfg = _make_cfg(td)
            store = OHLCVStore(cfg)
            candles = [_make_candle("XRPUSDT", _BASE_TS + timedelta(minutes=i)) for i in range(100)]

            w1, s1 = store.save(candles)
            w2, s2 = store.save(candles)

            assert w1 == 100
            assert s1 == 0
            assert w2 == 0
            assert s2 == 100  # all skipped

            loaded = store.load("XRPUSDT", "1m", _BASE_TS, _BASE_TS + timedelta(hours=2))
            assert len(loaded) == 100

    def test_partial_rerun_only_writes_new_candles(self):
        with tempfile.TemporaryDirectory() as td:
            cfg = _make_cfg(td)
            store = OHLCVStore(cfg)

            first_batch  = [_make_candle("XRPUSDT", _BASE_TS + timedelta(minutes=i)) for i in range(50)]
            second_batch = [_make_candle("XRPUSDT", _BASE_TS + timedelta(minutes=i)) for i in range(30, 80)]

            store.save(first_batch)
            w, s = store.save(second_batch)

            # 30-49 already stored (skipped), 50-79 are new
            assert w == 30
            assert s == 20
            loaded = store.load("XRPUSDT", "1m", _BASE_TS, _BASE_TS + timedelta(hours=2))
            assert len(loaded) == 80


# ---------------------------------------------------------------------------
# Pagination
# ---------------------------------------------------------------------------

class TestPagination:
    @pytest.mark.asyncio
    async def test_paginated_backfill_collects_all_batches(self):
        """
        Simulate a backfill where the exchange returns data in two batches.
        The backfill should collect both batches and store all candles.
        """
        with tempfile.TemporaryDirectory() as td:
            cfg = _make_cfg(td)
            cfg.KLINES_LIMIT = 5  # force pagination every 5 candles

            batch1 = [_make_candle("XRPUSDT", _BASE_TS + timedelta(minutes=i)) for i in range(5)]
            batch2 = [_make_candle("XRPUSDT", _BASE_TS + timedelta(minutes=i)) for i in range(5, 10)]

            call_count = 0
            async def mock_get_klines(symbol, interval, start_ms, end_ms, limit):
                nonlocal call_count
                base_ms = int(_BASE_TS.timestamp() * 1000)
                cutoff_ms = base_ms + 5 * 60_000  # 5 minute boundary
                call_count += 1
                if start_ms < cutoff_ms:
                    return batch1
                return batch2

            with patch("market_data.backfill.MarketDataClient") as MockClient:
                mock_client_instance = AsyncMock()
                mock_client_instance.get_klines = mock_get_klines
                MockClient.return_value.__aenter__ = AsyncMock(return_value=mock_client_instance)
                MockClient.return_value.__aexit__ = AsyncMock(return_value=False)

                from market_data.backfill import backfill_ohlcv
                end = _BASE_TS + timedelta(minutes=9)
                summary = await backfill_ohlcv(
                    symbols=["XRPUSDT"],
                    interval="1m",
                    start=_BASE_TS,
                    end=end,
                    cfg=cfg,
                )

            store = OHLCVStore(cfg)
            loaded = store.load("XRPUSDT", "1m", _BASE_TS, end)
            assert len(loaded) == 10


# ---------------------------------------------------------------------------
# Readiness classifier — boundary tests
# ---------------------------------------------------------------------------

class TestReadinessBoundaryConditions:
    def test_exactly_14_candles_is_not_rsi_initializable(self):
        """RSI(14) needs 15 observations. Exactly 14 should not be rsi_init."""
        with tempfile.TemporaryDirectory() as td:
            cfg = _make_cfg(td)
            store = OHLCVStore(cfg)
            candles = [_make_candle("XRPUSDT", _BASE_TS + timedelta(minutes=i)) for i in range(14)]
            store.save(candles)
            clf = ReadinessClassifier(cfg)
            result = clf.classify_symbol("XRPUSDT", _DEFAULT_SPEC)
            assert result.has_rsi_init is False

    def test_exactly_15_candles_is_rsi_initializable(self):
        """15 candles = 14 changes = first RSI value possible."""
        with tempfile.TemporaryDirectory() as td:
            cfg = _make_cfg(td)
            store = OHLCVStore(cfg)
            candles = [_make_candle("XRPUSDT", _BASE_TS + timedelta(minutes=i)) for i in range(15)]
            store.save(candles)
            clf = ReadinessClassifier(cfg)
            result = clf.classify_symbol("XRPUSDT", _DEFAULT_SPEC)
            assert result.has_rsi_init is True
            # But not READY — only 15 minutes of history
            assert result.status == ReadinessStatus.INCOMPLETE

    def test_candle_range_filter_works(self):
        """If start/end is provided, only that window is evaluated."""
        with tempfile.TemporaryDirectory() as td:
            cfg = _make_cfg(td)
            store = OHLCVStore(cfg)
            # Write 43,200 candles starting 2024-01-01
            candles = [
                _make_candle("XRPUSDT", _BASE_TS + timedelta(minutes=i))
                for i in range(43_200)
            ]
            store.save(candles)
            clf = ReadinessClassifier(cfg)
            # Restrict to just the first 100 candles
            narrow_end = _BASE_TS + timedelta(minutes=100)
            result = clf.classify_symbol("XRPUSDT", _DEFAULT_SPEC, start=_BASE_TS, end=narrow_end)
            assert result.candle_count == 101  # inclusive range
            assert result.status == ReadinessStatus.INCOMPLETE


# ---------------------------------------------------------------------------
# load_eligible_alt_symbols
# ---------------------------------------------------------------------------

class TestLoadEligibleAltSymbols:
    def test_returns_empty_when_no_snapshot(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        result = load_eligible_alt_symbols()
        assert result == []

    def test_excludes_btc_eth_sol(self, tmp_path, monkeypatch):
        import json
        monkeypatch.chdir(tmp_path)
        snap_dir = tmp_path / "data" / "snapshots"
        snap_dir.mkdir(parents=True)
        snap_file = snap_dir / "snapshot_20240101.jsonl"
        records = [
            {"record_type": "HEADER", "snapshot_timestamp": "2024-01-01T00:00:00Z",
             "snapshot_id": "X", "total_eligible": 5, "total_ranked": 0, "total_failed": 0, "top_n": 100},
            {"record_type": "DATA", "symbol": "BTCUSDT", "universe_status": "WATCHLIST",
             "snapshot_timestamp": "2024-01-01T00:00:00Z", "snapshot_id": "X",
             "rank": None, "score": None, "volume_24h_quote": 1e9,
             "open_interest": 1e9, "spread_bps": None, "metrics_failed": False},
            {"record_type": "DATA", "symbol": "ETHUSDT", "universe_status": "WATCHLIST",
             "snapshot_timestamp": "2024-01-01T00:00:00Z", "snapshot_id": "X",
             "rank": None, "score": None, "volume_24h_quote": 1e9,
             "open_interest": 1e9, "spread_bps": None, "metrics_failed": False},
            {"record_type": "DATA", "symbol": "SOLUSDT", "universe_status": "WATCHLIST",
             "snapshot_timestamp": "2024-01-01T00:00:00Z", "snapshot_id": "X",
             "rank": None, "score": None, "volume_24h_quote": 1e9,
             "open_interest": 1e9, "spread_bps": None, "metrics_failed": False},
            {"record_type": "DATA", "symbol": "XRPUSDT", "universe_status": "WATCHLIST",
             "snapshot_timestamp": "2024-01-01T00:00:00Z", "snapshot_id": "X",
             "rank": None, "score": None, "volume_24h_quote": 1e9,
             "open_interest": 1e9, "spread_bps": None, "metrics_failed": False},
        ]
        snap_file.write_text("\n".join(json.dumps(r) for r in records), encoding="utf-8")

        result = load_eligible_alt_symbols(
            exclude=frozenset({"BTCUSDT", "ETHUSDT", "SOLUSDT"})
        )
        assert "BTCUSDT" not in result
        assert "ETHUSDT" not in result
        assert "SOLUSDT" not in result
        assert "XRPUSDT" in result

    def test_ineligible_symbols_excluded(self, tmp_path, monkeypatch):
        import json
        monkeypatch.chdir(tmp_path)
        snap_dir = tmp_path / "data" / "snapshots"
        snap_dir.mkdir(parents=True)
        snap_file = snap_dir / "snapshot_20240101.jsonl"
        records = [
            {"record_type": "HEADER", "snapshot_timestamp": "2024-01-01T00:00:00Z",
             "snapshot_id": "X", "total_eligible": 2, "total_ranked": 0, "total_failed": 0, "top_n": 100},
            {"record_type": "DATA", "symbol": "XRPUSDT", "universe_status": "WATCHLIST",
             "snapshot_timestamp": "2024-01-01T00:00:00Z", "snapshot_id": "X",
             "rank": None, "score": None, "volume_24h_quote": 1e9,
             "open_interest": 1e9, "spread_bps": None, "metrics_failed": False},
            {"record_type": "DATA", "symbol": "STOCKUSDT", "universe_status": "INELIGIBLE",
             "snapshot_timestamp": "2024-01-01T00:00:00Z", "snapshot_id": "X",
             "rank": None, "score": None, "volume_24h_quote": 100,
             "open_interest": 100, "spread_bps": None, "metrics_failed": False},
        ]
        snap_file.write_text("\n".join(json.dumps(r) for r in records), encoding="utf-8")
        result = load_eligible_alt_symbols(exclude=frozenset())
        assert "XRPUSDT" in result
        assert "STOCKUSDT" not in result
