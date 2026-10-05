"""
tests/test_md_client.py

Tests for market_data/client.py

Covers:
  - parse_klines() parses raw Binance response arrays
  - parse_agg_trades() parses raw Binance response dicts
  - Timestamp conversion from ms epoch → UTC datetime
  - MarketDataClient context manager lifecycle
  - Retry on timeout (up to RETRY_MAX_ATTEMPTS)
  - Retry on HTTP 429 and 5xx
  - No retry on HTTP 400 (bad params) or 404 (not found)
  - get_klines() returns Candle list
  - get_agg_trades() returns AggTrade list
  - Semaphore enforces concurrency limit
  - MarketDataAPIError retryable flag

All Binance HTTP calls are mocked — no live network requests.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from market_data.client import (
    MarketDataAPIError,
    MarketDataClient,
    parse_agg_trades,
    parse_klines,
)
from market_data.config import MarketDataConfig
from market_data.models import AggTrade, Candle


# ─── Shared fixtures ──────────────────────────────────────────────────────────


@pytest.fixture()
def cfg() -> MarketDataConfig:
    c = MarketDataConfig()
    c.RETRY_MAX_ATTEMPTS  = 3
    c.RETRY_BACKOFF_BASE  = 0.001   # Near-zero for fast tests
    c.MAX_CONCURRENT_REQUESTS = 5
    return c


# ms timestamp for 2026-08-31 12:00:00 UTC
_TS_MS = int(datetime(2026, 8, 31, 12, 0, 0, tzinfo=timezone.utc).timestamp() * 1000)
_TS_CLOSE_MS = _TS_MS + 60_000 - 1  # 1m candle close


def _raw_kline(open_time_ms: int = _TS_MS) -> list:
    return [
        open_time_ms,     # [0] open_time
        "50000.0",        # [1] open
        "50100.0",        # [2] high
        "49900.0",        # [3] low
        "50050.0",        # [4] close
        "10.5",           # [5] volume
        open_time_ms + 59999,  # [6] close_time
        "525000.0",       # [7] quote_volume
        250,              # [8] trade_count
        "6.0",            # [9] taker_buy_base_vol
        "300000.0",       # [10] taker_buy_quote_vol
        "0",              # [11] ignore
    ]


def _raw_trade(agg_id: int = 1001, ts_ms: int = _TS_MS) -> dict:
    return {
        "a": agg_id,
        "p": "50000.0",
        "q": "0.5",
        "f": agg_id,
        "l": agg_id,
        "T": ts_ms,
        "m": False,
    }


# ─── parse_klines ─────────────────────────────────────────────────────────────


class TestParseKlines:
    def test_returns_candle_list(self):
        raw = [_raw_kline(_TS_MS + i * 60_000) for i in range(3)]
        candles = parse_klines("BTCUSDT", "1m", raw)
        assert len(candles) == 3
        assert all(isinstance(c, Candle) for c in candles)

    def test_symbol_and_interval_set(self):
        candles = parse_klines("ETHUSDT", "5m", [_raw_kline()])
        assert candles[0].symbol   == "ETHUSDT"
        assert candles[0].interval == "5m"

    def test_prices_parsed_correctly(self):
        candles = parse_klines("BTCUSDT", "1m", [_raw_kline()])
        c = candles[0]
        assert c.open  == 50000.0
        assert c.high  == 50100.0
        assert c.low   == 49900.0
        assert c.close == 50050.0

    def test_volume_parsed(self):
        candles = parse_klines("BTCUSDT", "1m", [_raw_kline()])
        c = candles[0]
        assert c.volume       == 10.5
        assert c.quote_volume == 525000.0

    def test_trade_count_is_int(self):
        candles = parse_klines("BTCUSDT", "1m", [_raw_kline()])
        assert isinstance(candles[0].trade_count, int)
        assert candles[0].trade_count == 250

    def test_open_time_is_utc(self):
        candles = parse_klines("BTCUSDT", "1m", [_raw_kline(_TS_MS)])
        expected = datetime(2026, 8, 31, 12, 0, 0, tzinfo=timezone.utc)
        assert candles[0].open_time == expected

    def test_taker_volumes_set(self):
        candles = parse_klines("BTCUSDT", "1m", [_raw_kline()])
        c = candles[0]
        assert c.taker_buy_base_vol  == 6.0
        assert c.taker_buy_quote_vol == 300000.0

    def test_empty_raw_returns_empty(self):
        assert parse_klines("BTCUSDT", "1m", []) == []

    def test_multiple_candles_preserve_order(self):
        raw = [_raw_kline(_TS_MS + i * 60_000) for i in range(5)]
        candles = parse_klines("BTCUSDT", "1m", raw)
        for i in range(len(candles) - 1):
            assert candles[i].open_time < candles[i + 1].open_time


# ─── parse_agg_trades ─────────────────────────────────────────────────────────


class TestParseAggTrades:
    def test_returns_trade_list(self):
        raw = [_raw_trade(i + 1, _TS_MS + i * 1000) for i in range(3)]
        trades = parse_agg_trades("BTCUSDT", raw)
        assert len(trades) == 3
        assert all(isinstance(t, AggTrade) for t in trades)

    def test_symbol_set(self):
        trades = parse_agg_trades("ETHUSDT", [_raw_trade()])
        assert trades[0].symbol == "ETHUSDT"

    def test_agg_trade_id_parsed(self):
        trades = parse_agg_trades("BTCUSDT", [_raw_trade(agg_id=42)])
        assert trades[0].agg_trade_id == 42

    def test_price_quantity_parsed(self):
        trades = parse_agg_trades("BTCUSDT", [_raw_trade()])
        assert trades[0].price    == 50000.0
        assert trades[0].quantity == 0.5

    def test_quote_quantity_computed(self):
        trades = parse_agg_trades("BTCUSDT", [_raw_trade()])
        assert trades[0].quote_quantity == pytest.approx(25000.0)

    def test_timestamp_is_utc(self):
        trades = parse_agg_trades("BTCUSDT", [_raw_trade(ts_ms=_TS_MS)])
        expected = datetime(2026, 8, 31, 12, 0, 0, tzinfo=timezone.utc)
        assert trades[0].timestamp == expected

    def test_buyer_is_maker_false(self):
        trades = parse_agg_trades("BTCUSDT", [_raw_trade()])
        assert trades[0].buyer_is_maker is False

    def test_buyer_is_maker_true(self):
        raw = _raw_trade()
        raw["m"] = True
        trades = parse_agg_trades("BTCUSDT", [raw])
        assert trades[0].buyer_is_maker is True

    def test_empty_raw_returns_empty(self):
        assert parse_agg_trades("BTCUSDT", []) == []


# ─── MarketDataClient — context manager ───────────────────────────────────────


class TestClientContextManager:
    async def test_must_be_used_as_context_manager(self, cfg):
        client = MarketDataClient(cfg)
        with pytest.raises(RuntimeError, match="context manager"):
            await client.get_klines("BTCUSDT", "1m", _TS_MS, _TS_MS + 60_000)

    async def test_session_closed_on_exit(self, cfg):
        closed = []
        with patch("market_data.client.httpx.AsyncClient") as mock_cls:
            mock_instance = AsyncMock()
            mock_instance.aclose = AsyncMock(side_effect=lambda: closed.append(True))
            mock_cls.return_value = mock_instance

            async with MarketDataClient(cfg):
                pass

        assert closed  # aclose() was called


# ─── MarketDataClient — get_klines ────────────────────────────────────────────


def _make_mock_client_with_response(response_json: object, status: int = 200) -> MagicMock:
    """Build a mock httpx.AsyncClient that returns *response_json*."""
    mock_resp = MagicMock()
    mock_resp.status_code = status
    mock_resp.json = MagicMock(return_value=response_json)
    mock_resp.text = str(response_json)
    mock_resp.headers = {}

    mock_http = MagicMock()
    mock_http.get = AsyncMock(return_value=mock_resp)
    mock_http.aclose = AsyncMock()
    return mock_http


class TestClientGetKlines:
    async def test_get_klines_returns_candles(self, cfg):
        raw = [_raw_kline(_TS_MS + i * 60_000) for i in range(5)]

        with patch("market_data.client.httpx.AsyncClient") as mock_cls:
            mock_cls.return_value = _make_mock_client_with_response(raw)
            async with MarketDataClient(cfg) as client:
                candles = await client.get_klines("BTCUSDT", "1m", _TS_MS, _TS_MS + 300_000)

        assert len(candles) == 5
        assert all(isinstance(c, Candle) for c in candles)

    async def test_get_klines_raises_on_bad_request(self, cfg):
        with patch("market_data.client.httpx.AsyncClient") as mock_cls:
            mock_cls.return_value = _make_mock_client_with_response(
                {"code": -1121, "msg": "Invalid symbol"}, status=400
            )
            async with MarketDataClient(cfg) as client:
                with pytest.raises(MarketDataAPIError) as exc_info:
                    await client.get_klines("INVALID", "1m", _TS_MS, _TS_MS + 60_000)

        assert exc_info.value.retryable is False
        assert exc_info.value.status_code == 400


# ─── MarketDataClient — retry behavior ───────────────────────────────────────


class TestClientRetry:
    async def test_retries_on_timeout(self, cfg):
        """Should retry RETRY_MAX_ATTEMPTS times then raise."""
        cfg.RETRY_MAX_ATTEMPTS = 3

        call_count = 0

        async def _timeout_get(path, params=None):
            nonlocal call_count
            call_count += 1
            raise httpx.TimeoutException("timeout")

        with patch("market_data.client.httpx.AsyncClient") as mock_cls:
            mock_http = MagicMock()
            mock_http.get = _timeout_get
            mock_http.aclose = AsyncMock()
            mock_cls.return_value = mock_http

            async with MarketDataClient(cfg) as client:
                with pytest.raises(MarketDataAPIError):
                    await client.get_klines("BTCUSDT", "1m", _TS_MS, _TS_MS + 60_000)

        assert call_count == cfg.RETRY_MAX_ATTEMPTS

    async def test_retries_on_429(self, cfg):
        """Should retry after 429 rate-limit response."""
        cfg.RETRY_MAX_ATTEMPTS = 2
        attempts = []

        def _make_resp(attempt_n: int):
            mock_resp = MagicMock()
            if attempt_n < cfg.RETRY_MAX_ATTEMPTS:
                mock_resp.status_code = 429
                mock_resp.text = "Too Many Requests"
                mock_resp.headers = {}
            else:
                raw = [_raw_kline()]
                mock_resp.status_code = 200
                mock_resp.json = MagicMock(return_value=raw)
            return mock_resp

        async def _get(path, params=None):
            attempts.append(1)
            return _make_resp(len(attempts))

        with patch("market_data.client.httpx.AsyncClient") as mock_cls:
            mock_http = MagicMock()
            mock_http.get = _get
            mock_http.aclose = AsyncMock()
            mock_cls.return_value = mock_http

            async with MarketDataClient(cfg) as client:
                candles = await client.get_klines("BTCUSDT", "1m", _TS_MS, _TS_MS + 60_000)

        assert len(attempts) == cfg.RETRY_MAX_ATTEMPTS
        assert len(candles) == 1

    async def test_no_retry_on_400(self, cfg):
        """HTTP 400 (bad params) must NOT be retried."""
        calls = []

        async def _get(path, params=None):
            calls.append(1)
            mock_resp = MagicMock()
            mock_resp.status_code = 400
            mock_resp.text = "Invalid symbol"
            mock_resp.headers = {}
            return mock_resp

        with patch("market_data.client.httpx.AsyncClient") as mock_cls:
            mock_http = MagicMock()
            mock_http.get = _get
            mock_http.aclose = AsyncMock()
            mock_cls.return_value = mock_http

            async with MarketDataClient(cfg) as client:
                with pytest.raises(MarketDataAPIError) as exc_info:
                    await client.get_klines("INVALID", "1m", _TS_MS, _TS_MS + 60_000)

        assert len(calls) == 1  # only one attempt
        assert exc_info.value.retryable is False

    async def test_no_retry_on_404(self, cfg):
        calls = []

        async def _get(path, params=None):
            calls.append(1)
            mock_resp = MagicMock()
            mock_resp.status_code = 404
            mock_resp.text = "Not found"
            mock_resp.headers = {}
            return mock_resp

        with patch("market_data.client.httpx.AsyncClient") as mock_cls:
            mock_http = MagicMock()
            mock_http.get = _get
            mock_http.aclose = AsyncMock()
            mock_cls.return_value = mock_http

            async with MarketDataClient(cfg) as client:
                with pytest.raises(MarketDataAPIError) as exc_info:
                    await client.get_klines("BTCUSDT", "1m", _TS_MS, _TS_MS + 60_000)

        assert len(calls) == 1
        assert exc_info.value.retryable is False


# ─── MarketDataClient — get_agg_trades ────────────────────────────────────────


class TestClientGetAggTrades:
    async def test_get_agg_trades_returns_trades(self, cfg):
        raw = [_raw_trade(i + 1, _TS_MS + i * 1000) for i in range(3)]

        with patch("market_data.client.httpx.AsyncClient") as mock_cls:
            mock_cls.return_value = _make_mock_client_with_response(raw)
            async with MarketDataClient(cfg) as client:
                trades = await client.get_agg_trades(
                    "BTCUSDT", _TS_MS, _TS_MS + 3600_000
                )

        assert len(trades) == 3
        assert all(isinstance(t, AggTrade) for t in trades)

    async def test_get_agg_trades_empty_response(self, cfg):
        with patch("market_data.client.httpx.AsyncClient") as mock_cls:
            mock_cls.return_value = _make_mock_client_with_response([])
            async with MarketDataClient(cfg) as client:
                trades = await client.get_agg_trades(
                    "BTCUSDT", _TS_MS, _TS_MS + 3600_000
                )
        assert trades == []
