"""
tests/test_refresh.py

Integration-level tests for the full refresh workflow.

Key focus: failure isolation — one symbol's OI failure must not destroy
the rest of the refresh.

All Binance HTTP calls are mocked using pytest-mock / unittest.mock.
No live API calls are made.
"""

from __future__ import annotations

import json
from pathlib import Path
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from universe.binance_client import BinanceAPIError
from universe.config import UniverseConfig
from universe.models import UniverseStatus
from universe.refresh import run_refresh


# --------------------------------------------------------------------------- #
#  Shared mock data
# --------------------------------------------------------------------------- #

FIXTURE_DIR = Path(__file__).parent / "fixtures"


def _load_exchange_info() -> dict:
    with open(FIXTURE_DIR / "exchange_info.json") as fh:
        return json.load(fh)


def _make_ticker(symbol: str, quote_volume: float = 1_000_000.0) -> dict:
    return {
        "symbol": symbol,
        "volume": str(quote_volume / 50_000),
        "quoteVolume": str(quote_volume),
        "lastPrice": "50000.0",
        "bidPrice": "49999.0",
        "askPrice": "50001.0",
        "openTime": 1000000,
        "closeTime": 1000001,
    }


def _make_oi(symbol: str, oi: float = 10_000.0) -> dict:
    return {"symbol": symbol, "openInterest": str(oi), "time": 1000000}


# --------------------------------------------------------------------------- #
#  Helper to build a mocked BinanceFuturesClient
# --------------------------------------------------------------------------- #

ELIGIBLE_SYMBOLS = ["BTCUSDT", "ETHUSDT", "SOLUSDT", "ADAUSDT", "XRPUSDT"]


def _make_mock_client(oi_fail_symbol: str | None = None):
    """
    Return a mock BinanceFuturesClient configured so:
      - get_exchange_info() → fixture data
      - get_all_tickers_24hr() → tickers for all eligible symbols
      - get_open_interest(sym) → success for all, EXCEPT oi_fail_symbol (raises BinanceAPIError)
    """
    client = MagicMock()
    client.__aenter__ = AsyncMock(return_value=client)
    client.__aexit__ = AsyncMock(return_value=False)

    client.get_exchange_info = AsyncMock(return_value=_load_exchange_info())
    client.get_all_tickers_24hr = AsyncMock(
        return_value=[
            _make_ticker("BTCUSDT", 5_000_000_000),
            _make_ticker("ETHUSDT", 2_000_000_000),
            _make_ticker("SOLUSDT", 800_000_000),
            _make_ticker("ADAUSDT", 400_000_000),
            _make_ticker("XRPUSDT", 300_000_000),
        ]
    )
    client.get_all_book_tickers = AsyncMock(
        return_value=[
            {"symbol": "BTCUSDT", "bidPrice": "49999.0", "askPrice": "50001.0", "bidQty": "1.0", "askQty": "1.0"},
            {"symbol": "ETHUSDT", "bidPrice": "2999.0", "askPrice": "3001.0", "bidQty": "5.0", "askQty": "5.0"},
            {"symbol": "SOLUSDT", "bidPrice": "149.9", "askPrice": "150.1", "bidQty": "20.0", "askQty": "20.0"},
            {"symbol": "ADAUSDT", "bidPrice": "0.449", "askPrice": "0.451", "bidQty": "1000.0", "askQty": "1000.0"},
            {"symbol": "XRPUSDT", "bidPrice": "0.599", "askPrice": "0.601", "bidQty": "500.0", "askQty": "500.0"},
        ]
    )

    async def _oi_side_effect(symbol: str) -> dict:
        if symbol == oi_fail_symbol:
            raise BinanceAPIError(f"Simulated OI failure for {symbol}")
        volumes = {
            "BTCUSDT": 50_000,
            "ETHUSDT": 300_000,
            "SOLUSDT": 1_000_000,
            "ADAUSDT": 5_000_000,
            "XRPUSDT": 8_000_000,
        }
        return _make_oi(symbol, volumes.get(symbol, 10_000))

    client.get_open_interest = _oi_side_effect
    return client


# --------------------------------------------------------------------------- #
#  Tests
# --------------------------------------------------------------------------- #


class TestRefreshWorkflow:
    @pytest.fixture()
    def tmp_cfg(self, tmp_path: Path) -> UniverseConfig:
        cfg = UniverseConfig()
        cfg.SNAPSHOT_DIR = tmp_path / "snapshots"
        cfg.TOP_N = 3   # Smaller than 5 eligible → easier to verify Top-N
        return cfg

    async def test_successful_refresh_returns_result(self, tmp_cfg, monkeypatch):
        mock_client = _make_mock_client()
        with patch("universe.refresh.BinanceFuturesClient", return_value=mock_client):
            result = await run_refresh(tmp_cfg)

        assert result.total_discovered > 0
        assert result.total_eligible == 5   # fixture has 5 valid crypto perps
        assert result.total_excluded > 0    # fixture has several excluded contracts
        assert result.total_ranked == 5
        assert result.total_failed_metrics == 0

    async def test_top_n_selection_correct(self, tmp_cfg, monkeypatch):
        mock_client = _make_mock_client()
        with patch("universe.refresh.BinanceFuturesClient", return_value=mock_client):
            result = await run_refresh(tmp_cfg)

        active = [m for m in result.universe if m.universe_status == UniverseStatus.ACTIVE_TOP_100]
        watchlist = [m for m in result.universe if m.universe_status == UniverseStatus.WATCHLIST]

        assert len(active) == tmp_cfg.TOP_N
        assert len(watchlist) == 5 - tmp_cfg.TOP_N

    async def test_universe_ordered_by_rank(self, tmp_cfg, monkeypatch):
        """Returned universe list is sorted: ranked members first, ascending rank."""
        mock_client = _make_mock_client()
        with patch("universe.refresh.BinanceFuturesClient", return_value=mock_client):
            result = await run_refresh(tmp_cfg)

        ranked = [m for m in result.universe if m.rank is not None]
        for i in range(len(ranked) - 1):
            assert ranked[i].rank <= ranked[i + 1].rank

    async def test_snapshot_file_created(self, tmp_cfg, monkeypatch):
        mock_client = _make_mock_client()
        with patch("universe.refresh.BinanceFuturesClient", return_value=mock_client):
            result = await run_refresh(tmp_cfg)

        snapshot_dir = Path(tmp_cfg.SNAPSHOT_DIR)
        files = list(snapshot_dir.glob("snapshot_*.jsonl"))
        assert len(files) == 1

    async def test_snapshot_contains_correct_record_count(self, tmp_cfg, monkeypatch):
        mock_client = _make_mock_client()
        with patch("universe.refresh.BinanceFuturesClient", return_value=mock_client):
            await run_refresh(tmp_cfg)

        snapshot_dir = Path(tmp_cfg.SNAPSHOT_DIR)
        jsonl_file = next(snapshot_dir.glob("snapshot_*.jsonl"))
        lines = [json.loads(l) for l in jsonl_file.read_text().splitlines() if l.strip()]
        data_records = [l for l in lines if l["record_type"] == "DATA"]
        assert len(data_records) == 5  # one per eligible contract


class TestFailureIsolation:
    """
    Verify that one symbol's OI fetch failure does not abort the refresh.
    The rest of the universe must still be ranked and persisted.
    """

    @pytest.fixture()
    def tmp_cfg(self, tmp_path: Path) -> UniverseConfig:
        cfg = UniverseConfig()
        cfg.SNAPSHOT_DIR = tmp_path / "snapshots"
        cfg.TOP_N = 3
        return cfg

    async def test_one_oi_failure_does_not_crash_refresh(self, tmp_cfg, monkeypatch):
        """SOLUSDT OI fails → refresh still completes with the other 4 ranked."""
        mock_client = _make_mock_client(oi_fail_symbol="SOLUSDT")
        with patch("universe.refresh.BinanceFuturesClient", return_value=mock_client):
            result = await run_refresh(tmp_cfg)

        # Refresh should complete
        assert result is not None

        # The failed symbol should be in the universe but marked as failed
        sol = next((m for m in result.universe if m.symbol == "SOLUSDT"), None)
        assert sol is not None
        assert sol.metrics_failed is True

        # The other 4 should have been ranked successfully
        assert result.total_ranked == 4
        assert result.total_failed_metrics == 1

    async def test_failed_symbol_not_in_top_n(self, tmp_cfg, monkeypatch):
        """A symbol with failed metrics must not be promoted to ACTIVE_TOP_100."""
        mock_client = _make_mock_client(oi_fail_symbol="BTCUSDT")
        with patch("universe.refresh.BinanceFuturesClient", return_value=mock_client):
            result = await run_refresh(tmp_cfg)

        btc = next((m for m in result.universe if m.symbol == "BTCUSDT"), None)
        assert btc is not None
        # BTC failed → should be WATCHLIST (not ranked)
        assert btc.universe_status == UniverseStatus.WATCHLIST
        assert btc.rank is None

    async def test_all_oi_failures_still_completes(self, tmp_cfg, monkeypatch):
        """Even if ALL OI calls fail, the refresh should not raise an exception."""
        client = _make_mock_client()

        async def _always_fail(symbol: str):
            raise BinanceAPIError(f"OI failed for {symbol}")

        client.get_open_interest = _always_fail

        with patch("universe.refresh.BinanceFuturesClient", return_value=client):
            result = await run_refresh(tmp_cfg)

        # No contracts rankable, but no exception
        assert result.total_ranked == 0
        assert result.total_failed_metrics == 5

    async def test_two_refreshes_both_in_snapshot(self, tmp_cfg, monkeypatch):
        """Two successive refreshes append to the same day's file."""
        mock_client = _make_mock_client()
        with patch("universe.refresh.BinanceFuturesClient", return_value=mock_client):
            await run_refresh(tmp_cfg)
            await run_refresh(tmp_cfg)

        snapshot_dir = Path(tmp_cfg.SNAPSHOT_DIR)
        files = list(snapshot_dir.glob("snapshot_*.jsonl"))
        assert len(files) == 1  # Same day → same file

        lines = [json.loads(l) for l in files[0].read_text().splitlines() if l.strip()]
        headers = [l for l in lines if l["record_type"] == "HEADER"]
        assert len(headers) == 2  # Two separate refresh runs recorded


class TestSnapshotId:
    @pytest.fixture()
    def tmp_cfg(self, tmp_path: Path) -> UniverseConfig:
        cfg = UniverseConfig()
        cfg.SNAPSHOT_DIR = tmp_path / "snapshots"
        return cfg

    async def test_snapshot_id_is_timestamped(self, tmp_cfg, monkeypatch):
        mock_client = _make_mock_client()
        with patch("universe.refresh.BinanceFuturesClient", return_value=mock_client):
            result = await run_refresh(tmp_cfg)

        # snapshot_id should be a date/time string like "20260831T185648Z"
        assert "T" in result.snapshot_id
        assert result.snapshot_id.endswith("Z")

    async def test_snapshot_timestamp_is_utc(self, tmp_cfg, monkeypatch):
        mock_client = _make_mock_client()
        with patch("universe.refresh.BinanceFuturesClient", return_value=mock_client):
            result = await run_refresh(tmp_cfg)

        assert result.snapshot_timestamp.tzinfo is not None
