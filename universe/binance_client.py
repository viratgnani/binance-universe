"""
universe/binance_client.py

Thin async HTTP wrapper around the Binance USDS-M Futures public API.

Responsibilities:
  - Provide typed responses for the three endpoints used by the universe engine.
  - Handle HTTP errors, timeouts, and rate-limit headers.
  - Expose a clean async context manager so callers never manage the HTTP
    session lifecycle directly.

Binance public endpoints used (no API key required):
  GET /fapi/v1/exchangeInfo   — symbol metadata
  GET /fapi/v1/ticker/24hr    — bulk 24h statistics (volume, price)
  GET /fapi/v1/bookTicker     — bulk best bid/ask for all symbols
  GET /fapi/v1/openInterest   — open interest per symbol

This module contains ONLY Binance API mechanics.
Filtering, normalisation, and ranking logic lives in separate modules.
"""

from __future__ import annotations

import logging
from typing import Any

import httpx

from universe.config import UniverseConfig, config as default_config

logger = logging.getLogger(__name__)


class BinanceAPIError(Exception):
    """Raised when the Binance API returns an unexpected response."""

    def __init__(self, message: str, status_code: int | None = None) -> None:
        super().__init__(message)
        self.status_code = status_code


class BinanceFuturesClient:
    """
    Async Binance USDS-M Futures API client.

    Usage::

        async with BinanceFuturesClient() as client:
            info = await client.get_exchange_info()
            tickers = await client.get_all_tickers_24hr()
            oi = await client.get_open_interest("BTCUSDT")

    All public methods raise :class:`BinanceAPIError` on non-2xx responses
    or JSON parse failures, so callers can catch a single exception type.
    """

    def __init__(self, cfg: UniverseConfig = default_config) -> None:
        self._cfg = cfg
        self._client: httpx.AsyncClient | None = None

    # ------------------------------------------------------------------ #
    #  Context manager
    # ------------------------------------------------------------------ #

    async def __aenter__(self) -> "BinanceFuturesClient":
        self._client = httpx.AsyncClient(
            base_url=self._cfg.BINANCE_FAPI_BASE_URL,
            timeout=self._cfg.REQUEST_TIMEOUT_SECONDS,
            headers={"Accept": "application/json"},
            follow_redirects=True,
        )
        return self

    async def __aexit__(self, *_: Any) -> None:
        if self._client is not None:
            await self._client.aclose()
            self._client = None

    # ------------------------------------------------------------------ #
    #  Internal helpers
    # ------------------------------------------------------------------ #

    @property
    def _http(self) -> httpx.AsyncClient:
        if self._client is None:
            raise RuntimeError(
                "BinanceFuturesClient must be used as an async context manager."
            )
        return self._client

    async def _get(self, path: str, params: dict[str, Any] | None = None) -> Any:
        """
        Perform a GET request and return the parsed JSON body.

        Raises BinanceAPIError on HTTP errors or JSON decode failures.
        """
        try:
            response = await self._http.get(path, params=params)
        except httpx.TimeoutException as exc:
            raise BinanceAPIError(f"Request timed out: {path}") from exc
        except httpx.RequestError as exc:
            raise BinanceAPIError(f"Network error on {path}: {exc}") from exc

        if response.status_code != 200:
            raise BinanceAPIError(
                f"Binance returned HTTP {response.status_code} for {path}: "
                f"{response.text[:200]}",
                status_code=response.status_code,
            )

        try:
            return response.json()
        except Exception as exc:
            raise BinanceAPIError(
                f"Failed to parse JSON from {path}: {exc}"
            ) from exc

    # ------------------------------------------------------------------ #
    #  Public API methods
    # ------------------------------------------------------------------ #

    async def get_exchange_info(self) -> dict[str, Any]:
        """
        Fetch exchange-wide trading rules and all symbol definitions.

        Endpoint: GET /fapi/v1/exchangeInfo
        Weight   : 1 (IP)

        Returns the raw JSON dict.  Parsing into ContractInfo models is done
        by universe_discovery.py, not here.
        """
        logger.debug("Fetching Binance exchange info")
        data = await self._get("/fapi/v1/exchangeInfo")
        symbols_count = len(data.get("symbols", []))
        logger.debug("Exchange info received: %d symbol entries", symbols_count)
        return data

    async def get_all_tickers_24hr(self) -> list[dict[str, Any]]:
        """
        Fetch 24-hour rolling price change statistics for ALL symbols at once.

        Endpoint: GET /fapi/v1/ticker/24hr  (no symbol param → all symbols)
        Weight   : 40 (IP)

        Returns a list of ticker dicts with fields including:
          symbol, lastPrice, openPrice, volume, quoteVolume, etc.

        Note: does NOT include bid/ask prices — use get_all_book_tickers() for those.
        """
        logger.debug("Fetching all 24hr tickers (bulk)")
        data = await self._get("/fapi/v1/ticker/24hr")
        if not isinstance(data, list):
            raise BinanceAPIError(
                f"Expected list from /ticker/24hr, got {type(data).__name__}"
            )
        logger.debug("Received %d ticker records", len(data))
        return data  # type: ignore[return-value]

    async def get_all_book_tickers(self) -> list[dict[str, Any]]:
        """
        Fetch the best bid/ask price for ALL symbols at once.

        Endpoint: GET /fapi/v1/bookTicker  (no symbol param → all symbols)
        Weight   : 2 (IP)

        Returns a list of dicts with fields: symbol, bidPrice, bidQty, askPrice, askQty.
        """
        logger.debug("Fetching all book tickers (bulk bid/ask)")
        data = await self._get("/fapi/v1/ticker/bookTicker")
        if not isinstance(data, list):
            raise BinanceAPIError(
                f"Expected list from /bookTicker, got {type(data).__name__}"
            )
        logger.debug("Received %d book ticker records", len(data))
        return data  # type: ignore[return-value]

    async def get_open_interest(self, symbol: str) -> dict[str, Any]:
        """
        Fetch current open interest for a single symbol.

        Endpoint: GET /fapi/v1/openInterest?symbol=<symbol>
        Weight   : 1 (IP)

        Returns the raw JSON dict containing 'openInterest' and 'symbol'.
        Raises BinanceAPIError on failure (caller handles per-symbol failures).
        """
        logger.debug("Fetching open interest for %s", symbol)
        return await self._get("/fapi/v1/openInterest", params={"symbol": symbol})  # type: ignore[return-value]
