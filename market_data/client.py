"""
market_data/client.py

Async HTTP client for Binance USDS-M Futures market-data endpoints.

Endpoints used:
  GET /fapi/v1/klines      — OHLCV candlestick data
  GET /fapi/v1/aggTrades   — Aggregate trade records

Design:
  - Independent from universe/binance_client.py (universe/ is frozen).
  - Built-in retry with exponential backoff for transient failures.
  - asyncio.Semaphore enforces configurable concurrency ceiling.
  - Distinguishes retryable errors (timeout, 429, 5xx) from
    non-retryable ones (400, 404, bad parameters).
  - Pure data access: no normalisation, no persistence.

Rate limits (Binance fapi IP weight per minute: 2400):
  /fapi/v1/klines    weight: 1–10 depending on limit parameter
  /fapi/v1/aggTrades weight: 20

Usage::

    async with MarketDataClient() as client:
        candles = await client.get_klines(
            symbol="BTCUSDT",
            interval="1m",
            start_ms=1_700_000_000_000,
            end_ms=1_700_003_600_000,
            limit=1500,
        )
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from typing import Any

import httpx

from market_data.config import MarketDataConfig, config as default_config
from market_data.models import AggTrade, Candle

logger = logging.getLogger(__name__)


# --------------------------------------------------------------------------- #
#  Errors
# --------------------------------------------------------------------------- #


class MarketDataAPIError(Exception):
    """Raised when the Binance API returns an unexpected or error response."""

    def __init__(
        self,
        message: str,
        status_code: int | None = None,
        retryable: bool = True,
    ) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.retryable = retryable


# --------------------------------------------------------------------------- #
#  Raw response parsers (module-level, no I/O)
# --------------------------------------------------------------------------- #


def parse_klines(symbol: str, interval: str, raw: list[list[Any]]) -> list[Candle]:
    """
    Parse raw Binance /fapi/v1/klines response into Candle objects.

    Each element of *raw* is a 12-element list:
      [0]  open_time_ms   int
      [1]  open           str
      [2]  high           str
      [3]  low            str
      [4]  close          str
      [5]  volume         str  (base asset)
      [6]  close_time_ms  int
      [7]  quote_volume   str
      [8]  trade_count    int
      [9]  taker_buy_base_vol   str
      [10] taker_buy_quote_vol  str
      [11] ignore         str

    Timestamps: milliseconds UTC → converted to UTC-aware datetime.
    """
    now = datetime.now(tz=timezone.utc)
    candles: list[Candle] = []
    for row in raw:
        candles.append(
            Candle(
                symbol=symbol,
                interval=interval,
                open_time=datetime.fromtimestamp(row[0] / 1000.0, tz=timezone.utc),
                close_time=datetime.fromtimestamp(row[6] / 1000.0, tz=timezone.utc),
                open=float(row[1]),
                high=float(row[2]),
                low=float(row[3]),
                close=float(row[4]),
                volume=float(row[5]),
                quote_volume=float(row[7]),
                trade_count=int(row[8]),
                taker_buy_base_vol=float(row[9]),
                taker_buy_quote_vol=float(row[10]),
                collection_time=now,
            )
        )
    return candles


def parse_agg_trades(symbol: str, raw: list[dict[str, Any]]) -> list[AggTrade]:
    """
    Parse raw Binance /fapi/v1/aggTrades response into AggTrade objects.

    Each element of *raw* is a dict with keys:
      a: int   — aggregate trade ID
      p: str   — price
      q: str   — quantity (base asset)
      f: int   — first trade ID
      l: int   — last trade ID
      T: int   — timestamp (ms UTC)
      m: bool  — buyer is maker
    """
    now = datetime.now(tz=timezone.utc)
    trades: list[AggTrade] = []
    for row in raw:
        price = float(row["p"])
        qty   = float(row["q"])
        trades.append(
            AggTrade(
                symbol=symbol,
                agg_trade_id=int(row["a"]),
                price=price,
                quantity=qty,
                quote_quantity=round(price * qty, 10),
                first_trade_id=int(row["f"]),
                last_trade_id=int(row["l"]),
                timestamp=datetime.fromtimestamp(row["T"] / 1000.0, tz=timezone.utc),
                buyer_is_maker=bool(row["m"]),
                collection_time=now,
            )
        )
    return trades


# --------------------------------------------------------------------------- #
#  Client
# --------------------------------------------------------------------------- #


class MarketDataClient:
    """
    Async HTTP client for Binance USDS-M Futures market data.

    Features:
    - Context-manager lifecycle (manages httpx session).
    - Configurable concurrency via asyncio.Semaphore.
    - Transparent retry with exponential backoff for transient errors.
    - Distinct retryable / non-retryable error classification.

    Usage::

        async with MarketDataClient(cfg) as client:
            candles = await client.get_klines("BTCUSDT", "1m", start_ms, end_ms)
            trades  = await client.get_agg_trades("BTCUSDT", start_ms, end_ms)
    """

    def __init__(self, cfg: MarketDataConfig = default_config) -> None:
        self._cfg = cfg
        self._http: httpx.AsyncClient | None = None
        self._semaphore: asyncio.Semaphore | None = None

    # ------------------------------------------------------------------ #
    #  Context manager
    # ------------------------------------------------------------------ #

    async def __aenter__(self) -> "MarketDataClient":
        self._http = httpx.AsyncClient(
            base_url=self._cfg.BINANCE_FAPI_BASE_URL,
            timeout=self._cfg.REQUEST_TIMEOUT_SECONDS,
            headers={"Accept": "application/json"},
            follow_redirects=True,
        )
        self._semaphore = asyncio.Semaphore(self._cfg.MAX_CONCURRENT_REQUESTS)
        return self

    async def __aexit__(self, *_: Any) -> None:
        if self._http is not None:
            await self._http.aclose()
            self._http = None

    # ------------------------------------------------------------------ #
    #  Internal helpers
    # ------------------------------------------------------------------ #

    @property
    def _session(self) -> httpx.AsyncClient:
        if self._http is None:
            raise RuntimeError(
                "MarketDataClient must be used as an async context manager."
            )
        return self._http

    @property
    def _sem(self) -> asyncio.Semaphore:
        if self._semaphore is None:
            raise RuntimeError(
                "MarketDataClient must be used as an async context manager."
            )
        return self._semaphore

    async def _get(self, path: str, params: dict[str, Any]) -> Any:
        """
        Perform a single GET request through the semaphore with retry.

        Retryable errors: timeout, HTTP 429, HTTP 5xx.
        Non-retryable:    HTTP 400 (bad params), HTTP 404 (symbol not found).
        """
        async with self._sem:
            last_exc: Exception | None = None
            for attempt in range(1, self._cfg.RETRY_MAX_ATTEMPTS + 1):
                try:
                    resp = await self._session.get(path, params=params)
                except httpx.TimeoutException as exc:
                    wait = self._cfg.RETRY_BACKOFF_BASE * (2 ** (attempt - 1))
                    logger.warning(
                        "Timeout on %s attempt %d/%d — retrying in %.1fs",
                        path, attempt, self._cfg.RETRY_MAX_ATTEMPTS, wait,
                    )
                    last_exc = MarketDataAPIError(
                        f"Request timed out: {path}", retryable=True
                    )
                    if attempt < self._cfg.RETRY_MAX_ATTEMPTS:
                        await asyncio.sleep(wait)
                    continue
                except httpx.RequestError as exc:
                    raise MarketDataAPIError(
                        f"Network error on {path}: {exc}", retryable=True
                    ) from exc

                if resp.status_code == 200:
                    try:
                        return resp.json()
                    except Exception as exc:
                        raise MarketDataAPIError(
                            f"JSON parse error from {path}: {exc}", retryable=False
                        ) from exc

                # Non-retryable HTTP errors
                if resp.status_code in (400, 404):
                    raise MarketDataAPIError(
                        f"Binance HTTP {resp.status_code} for {path}: {resp.text[:200]}",
                        status_code=resp.status_code,
                        retryable=False,
                    )

                # Retryable HTTP errors (429, 5xx)
                wait = self._cfg.RETRY_BACKOFF_BASE * (2 ** (attempt - 1))
                if resp.status_code == 429:
                    # Respect Retry-After header if present
                    retry_after = resp.headers.get("Retry-After")
                    if retry_after:
                        try:
                            wait = max(wait, float(retry_after))
                        except ValueError:
                            pass
                logger.warning(
                    "HTTP %d on %s attempt %d/%d — retrying in %.1fs",
                    resp.status_code, path, attempt, self._cfg.RETRY_MAX_ATTEMPTS, wait,
                )
                last_exc = MarketDataAPIError(
                    f"Binance HTTP {resp.status_code} for {path}",
                    status_code=resp.status_code,
                    retryable=True,
                )
                if attempt < self._cfg.RETRY_MAX_ATTEMPTS:
                    await asyncio.sleep(wait)

            raise last_exc or MarketDataAPIError(
                f"All {self._cfg.RETRY_MAX_ATTEMPTS} attempts failed for {path}",
                retryable=True,
            )

    # ------------------------------------------------------------------ #
    #  Public API methods
    # ------------------------------------------------------------------ #

    async def get_klines(
        self,
        symbol: str,
        interval: str,
        start_ms: int,
        end_ms: int,
        limit: int | None = None,
    ) -> list[Candle]:
        """
        Fetch OHLCV candlesticks for *symbol* between *start_ms* and *end_ms*.

        Endpoint: GET /fapi/v1/klines
        Weight   : 1–10 depending on limit

        Parameters
        ----------
        symbol:
            Binance symbol, e.g. "BTCUSDT".
        interval:
            Candlestick interval string, e.g. "1m", "1h".
        start_ms:
            Start of range (milliseconds UTC, inclusive).
        end_ms:
            End of range (milliseconds UTC, inclusive).
        limit:
            Max candles per request.  Defaults to cfg.KLINES_LIMIT (1500).

        Returns
        -------
        List of :class:`Candle` objects, oldest first.
        """
        _limit = limit or self._cfg.KLINES_LIMIT
        params: dict[str, Any] = {
            "symbol":    symbol,
            "interval":  interval,
            "startTime": start_ms,
            "endTime":   end_ms,
            "limit":     _limit,
        }
        logger.debug(
            "get_klines: %s %s [%d, %d] limit=%d",
            symbol, interval, start_ms, end_ms, _limit,
        )
        raw = await self._get("/fapi/v1/klines", params)
        if not isinstance(raw, list):
            raise MarketDataAPIError(
                f"Expected list from /fapi/v1/klines, got {type(raw).__name__}",
                retryable=False,
            )
        candles = parse_klines(symbol, interval, raw)
        logger.debug("get_klines: %s %s → %d candles", symbol, interval, len(candles))
        return candles

    async def get_agg_trades(
        self,
        symbol: str,
        start_ms: int,
        end_ms: int,
        limit: int | None = None,
        from_id: int | None = None,
    ) -> list[AggTrade]:
        """
        Fetch aggregate trades for *symbol* between *start_ms* and *end_ms*.

        Endpoint: GET /fapi/v1/aggTrades
        Weight   : 20

        Limitations:
          - startTime/endTime range: max 48 hours.
          - from_id and startTime/endTime are mutually exclusive.
          - For history older than 48h, use the async export API (not V1 scope).

        Parameters
        ----------
        symbol:
            Binance symbol, e.g. "BTCUSDT".
        start_ms:
            Start of range (ms UTC). Ignored if from_id is set.
        end_ms:
            End of range (ms UTC). Ignored if from_id is set.
        limit:
            Max trades per request.  Defaults to cfg.AGTRADES_LIMIT (1000).
        from_id:
            If provided, fetch trades with agg_trade_id >= from_id.
            Cannot be combined with startTime/endTime.

        Returns
        -------
        List of :class:`AggTrade` objects, oldest first.
        """
        _limit = limit or self._cfg.AGTRADES_LIMIT
        params: dict[str, Any] = {
            "symbol": symbol,
            "limit":  _limit,
        }
        if from_id is not None:
            params["fromId"] = from_id
        else:
            params["startTime"] = start_ms
            params["endTime"]   = end_ms

        logger.debug(
            "get_agg_trades: %s [%s] limit=%d",
            symbol,
            f"fromId={from_id}" if from_id else f"{start_ms}–{end_ms}",
            _limit,
        )
        raw = await self._get("/fapi/v1/aggTrades", params)
        if not isinstance(raw, list):
            raise MarketDataAPIError(
                f"Expected list from /fapi/v1/aggTrades, got {type(raw).__name__}",
                retryable=False,
            )
        trades = parse_agg_trades(symbol, raw)
        logger.debug("get_agg_trades: %s → %d trades", symbol, len(trades))
        return trades
