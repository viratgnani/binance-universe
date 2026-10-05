"""
market_data/ob_client.py

Client functions for fetching REST snapshots and parsing WebSocket events.
Uses existing MarketDataClient for the REST call.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

from market_data.client import MarketDataAPIError, MarketDataClient
from market_data.ob_models import OrderBookEvent, OrderBookSnapshot

logger = logging.getLogger(__name__)


def parse_ob_event(raw: dict[str, Any]) -> OrderBookEvent:
    """
    Parses a raw Binance WebSocket @depth event dictionary.
    """
    return OrderBookEvent(
        symbol=raw["s"],
        event_time=datetime.fromtimestamp(raw["E"] / 1000.0, tz=timezone.utc),
        transaction_time=datetime.fromtimestamp(raw["T"] / 1000.0, tz=timezone.utc),
        first_update_id=raw["U"],
        final_update_id=raw["u"],
        previous_final_update_id=raw["pu"],
        bids=[(float(p), float(q)) for p, q in raw.get("b", [])],
        asks=[(float(p), float(q)) for p, q in raw.get("a", [])],
        local_receipt_time=datetime.now(tz=timezone.utc),
    )


async def fetch_ob_snapshot(
    client: MarketDataClient,
    symbol: str,
    limit: int = 1000,
) -> OrderBookSnapshot:
    """
    Fetches the REST snapshot for a symbol.
    """
    params = {
        "symbol": symbol,
        "limit": limit,
    }
    
    # Need to access internal _get of client. It's safe within our module boundaries
    # if we document it or we can just add a public method to client.
    # We will use the private method here since it's already implemented.
    raw = await client._get("/fapi/v1/depth", params)
    
    if not isinstance(raw, dict) or "lastUpdateId" not in raw:
        raise MarketDataAPIError(
            f"Expected dict with lastUpdateId from /fapi/v1/depth, got {type(raw).__name__}",
            retryable=False,
        )

    return OrderBookSnapshot(
        symbol=symbol,
        last_update_id=raw["lastUpdateId"],
        message_output_time=datetime.fromtimestamp(raw["E"] / 1000.0, tz=timezone.utc) if "E" in raw else datetime.now(tz=timezone.utc),
        transaction_time=datetime.fromtimestamp(raw["T"] / 1000.0, tz=timezone.utc) if "T" in raw else datetime.now(tz=timezone.utc),
        bids=[(float(p), float(q)) for p, q in raw.get("bids", [])],
        asks=[(float(p), float(q)) for p, q in raw.get("asks", [])],
        local_receipt_time=datetime.now(tz=timezone.utc),
    )
