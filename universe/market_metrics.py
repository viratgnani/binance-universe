"""
universe/market_metrics.py

Fetches and assembles per-contract market quality metrics for a list of
eligible contracts.

Responsibilities:
  - One bulk call to /fapi/v1/ticker/24hr to get volume, price, bid/ask for all.
  - Concurrent per-symbol calls to /fapi/v1/openInterest (semaphore-limited).
  - Per-symbol failure isolation: one bad OI fetch does NOT abort the refresh.
  - Returns a list of MarketMetrics, one per eligible symbol.

This module owns market data collection only.
Normalisation and ranking live in separate modules.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from universe.binance_client import BinanceFuturesClient, BinanceAPIError
from universe.config import UniverseConfig, config as default_config
from universe.models import ContractInfo, MarketMetrics

logger = logging.getLogger(__name__)


class MarketMetricsFetcher:
    """
    Collects market metrics for a list of eligible contracts.

    Parameters
    ----------
    client:
        An already-connected :class:`BinanceFuturesClient` instance.
    cfg:
        Configuration, used for OI concurrency limit.
    """

    def __init__(
        self,
        client: BinanceFuturesClient,
        cfg: UniverseConfig = default_config,
    ) -> None:
        self._client = client
        self._cfg = cfg

    # ------------------------------------------------------------------ #
    #  Public interface
    # ------------------------------------------------------------------ #

    async def fetch_all(
        self, contracts: list[ContractInfo]
    ) -> list[MarketMetrics]:
        """
        Fetch complete market metrics for every contract in *contracts*.

        Workflow:
          1. Bulk ticker call → dict keyed by symbol.
          2. Concurrent OI calls with semaphore.
          3. Merge results into MarketMetrics objects.

        One symbol's OI failure is recorded in MarketMetrics.metrics_failed;
        ticker data is still preserved.
        """
        if not contracts:
            return []

        symbols = {c.symbol for c in contracts}

        # Step 1a: Bulk 24hr ticker (volume, price, price-change stats)
        ticker_map = await self._fetch_ticker_map(symbols)

        # Step 1b: Bulk book ticker (bid/ask) — /ticker/24hr does NOT include bid/ask
        book_map = await self._fetch_book_ticker_map(symbols)

        # Step 2: Concurrent OI calls
        oi_map = await self._fetch_oi_map(list(symbols))

        # Step 3: Merge
        metrics_list: list[MarketMetrics] = []
        for contract in contracts:
            symbol = contract.symbol
            ticker = ticker_map.get(symbol)
            book = book_map.get(symbol)
            oi_entry = oi_map.get(symbol)

            if ticker is None:
                # Symbol was not in the bulk ticker response — record failure
                metrics_list.append(
                    MarketMetrics(
                        symbol=symbol,
                        metrics_failed=True,
                        failure_reason="Symbol absent from /ticker/24hr response",
                    )
                )
                logger.warning("%s: absent from bulk ticker response", symbol)
                continue

            metrics = self._build_metrics_from_ticker(symbol, ticker, book)

            # Attach OI
            if oi_entry is not None:
                if isinstance(oi_entry, Exception):
                    metrics.metrics_failed = True
                    metrics.failure_reason = f"OI fetch failed: {oi_entry}"
                    logger.warning("%s: OI fetch failed: %s", symbol, oi_entry)
                else:
                    try:
                        metrics.open_interest = float(oi_entry.get("openInterest", 0) or 0)
                    except (ValueError, TypeError) as exc:
                        logger.warning("%s: Could not parse OI value: %s", symbol, exc)
                        metrics.metrics_failed = True
                        metrics.failure_reason = f"OI parse error: {exc}"
            else:
                logger.warning("%s: OI result missing from map", symbol)
                metrics.metrics_failed = True
                metrics.failure_reason = "OI result absent"

            metrics_list.append(metrics)

        success = sum(1 for m in metrics_list if not m.metrics_failed)
        failed = len(metrics_list) - success
        logger.info(
            "Market metrics: %d successful, %d failed (of %d contracts)",
            success,
            failed,
            len(contracts),
        )
        return metrics_list

    # ------------------------------------------------------------------ #
    #  Private helpers
    # ------------------------------------------------------------------ #

    async def _fetch_ticker_map(
        self, symbols: set[str]
    ) -> dict[str, dict[str, Any]]:
        """
        Call /ticker/24hr (all symbols) and build a symbol → ticker dict.

        Contains: volume, lastPrice, but NOT bid/ask.
        """
        try:
            tickers: list[dict[str, Any]] = await self._client.get_all_tickers_24hr()
        except BinanceAPIError as exc:
            logger.error("Bulk ticker fetch failed: %s", exc)
            raise

        ticker_map: dict[str, dict[str, Any]] = {}
        for t in tickers:
            sym = t.get("symbol", "")
            if sym in symbols:
                ticker_map[sym] = t

        logger.debug(
            "Ticker map: %d entries matched (of %d returned by Binance)",
            len(ticker_map),
            len(tickers),
        )
        return ticker_map

    async def _fetch_book_ticker_map(
        self, symbols: set[str]
    ) -> dict[str, dict[str, Any]]:
        """
        Call /bookTicker (all symbols) and build a symbol → book ticker dict.

        Contains: bidPrice, bidQty, askPrice, askQty.
        """
        try:
            book_tickers: list[dict[str, Any]] = await self._client.get_all_book_tickers()
        except BinanceAPIError as exc:
            # Non-fatal: spread won't be computable, but volume/OI still work
            logger.warning("Bulk book ticker fetch failed: %s — spread_bps will be unavailable", exc)
            return {}

        book_map: dict[str, dict[str, Any]] = {}
        for b in book_tickers:
            sym = b.get("symbol", "")
            if sym in symbols:
                book_map[sym] = b

        logger.debug(
            "Book ticker map: %d entries matched (of %d returned)",
            len(book_map),
            len(book_tickers),
        )
        return book_map

    async def _fetch_oi_map(
        self, symbols: list[str]
    ) -> dict[str, dict[str, Any] | Exception]:
        """
        Fetch open interest for all *symbols* concurrently.

        Uses a semaphore to limit concurrent requests to
        config.OI_CONCURRENCY_LIMIT.

        Returns a dict mapping symbol → raw OI dict (on success) or
        Exception (on failure).  Caller decides what to do with failures.
        """
        semaphore = asyncio.Semaphore(self._cfg.OI_CONCURRENCY_LIMIT)

        async def _fetch_one(symbol: str) -> tuple[str, dict[str, Any] | Exception]:
            async with semaphore:
                try:
                    result = await self._client.get_open_interest(symbol)
                    return symbol, result
                except BinanceAPIError as exc:
                    return symbol, exc

        tasks = [_fetch_one(sym) for sym in symbols]
        results = await asyncio.gather(*tasks)
        return dict(results)

    @staticmethod
    def _build_metrics_from_ticker(
        symbol: str,
        ticker: dict[str, Any],
        book: dict[str, Any] | None,
    ) -> MarketMetrics:
        """
        Convert a raw /ticker/24hr entry + optional /bookTicker entry into
        a partial MarketMetrics object.

        OI is populated separately.  spread_bps is calculated by the model's
        validator if bid, ask, and last are all present.
        """

        def _safe_float(d: dict, key: str) -> float | None:
            val = d.get(key)
            if val is None or val == "" or val == "0" or val == "0.00000000":
                return None
            try:
                f = float(val)
                return f if f > 0 else None
            except (ValueError, TypeError):
                logger.debug("%s: could not parse field %r = %r", symbol, key, val)
                return None

        bid_price = _safe_float(book, "bidPrice") if book else None
        ask_price = _safe_float(book, "askPrice") if book else None

        return MarketMetrics(
            symbol=symbol,
            volume_24h_quote=_safe_float(ticker, "quoteVolume"),
            volume_24h_base=_safe_float(ticker, "volume"),
            last_price=_safe_float(ticker, "lastPrice"),
            bid_price=bid_price,
            ask_price=ask_price,
            # spread_bps is computed by the model validator if bid/ask/last available
        )
