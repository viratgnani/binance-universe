"""
market_data/ob_sync.py

Manages the synchronization lifecycle of an order book combining
buffered WebSocket events with a REST snapshot.
"""

from __future__ import annotations

import asyncio
import logging
from collections import deque
from typing import Any

from market_data.client import MarketDataAPIError, MarketDataClient
from market_data.ob_client import fetch_ob_snapshot, parse_ob_event
from market_data.ob_local import LocalOrderBook
from market_data.ob_models import OrderBookEvent, OrderBookViolation

logger = logging.getLogger(__name__)


class OrderBookSyncManager:
    """
    Manages the synchronization lifecycle for a single symbol's order book.
    """

    def __init__(self, symbol: str, client: MarketDataClient, depth_limit: int = 1000) -> None:
        self.symbol = symbol
        self.client = client
        self.depth_limit = depth_limit

        self.local_book = LocalOrderBook(symbol)
        self.event_buffer: deque[OrderBookEvent] = deque(maxlen=5000)
        
        # State tracking
        self.is_syncing: bool = False
        self.sync_task: asyncio.Task[None] | None = None
        self.violations_history: list[OrderBookViolation] = []
        self.resync_count: int = 0
        self.events_processed: int = 0
        self.duplicate_events: int = 0
        self.last_receipt_time: float | None = None
        self.stale_incidents: int = 0

    def on_raw_event(self, raw_event: dict[str, Any]) -> OrderBookEvent | None:
        """
        Receives a raw depthUpdate event from the WebSocket.
        """
        try:
            event = parse_ob_event(raw_event)
        except Exception as exc:
            logger.error("Failed to parse event for %s: %s", self.symbol, exc)
            return None

        import time
        self.last_receipt_time = time.monotonic()

        if not self.local_book.synchronized:
            # If not already syncing, trigger a sync
            if not self.is_syncing:
                self._trigger_sync()
            self.event_buffer.append(event)
        else:
            # We are synchronized, apply event directly
            violations = self.local_book.apply_event(event)
            if violations:
                self.violations_history.extend(violations)
                # Any violation (gap, invalid data) breaks sync
                logger.warning(
                    "Sync lost for %s due to %d violations. First: %s",
                    self.symbol, len(violations), violations[0].violation_type
                )
                self.resync_count += 1
                self._trigger_sync()
            else:
                self.events_processed += 1

        return event

    def _trigger_sync(self) -> None:
        """
        Initiates the asynchronous REST snapshot fetch.
        """
        if self.is_syncing:
            return
        
        self.is_syncing = True
        self.local_book.synchronized = False
        self.event_buffer.clear()
        
        # We spawn a background task to fetch the snapshot so we don't block the WS reader
        self.sync_task = asyncio.create_task(self._sync_routine())

    async def _sync_routine(self) -> None:
        """
        Fetches the snapshot, waits for buffer to fill if needed, and applies the logic.
        """
        logger.info("Starting synchronization for %s", self.symbol)
        try:
            snapshot = await fetch_ob_snapshot(self.client, self.symbol, limit=self.depth_limit)
        except MarketDataAPIError as exc:
            logger.error("Failed to fetch snapshot for %s: %s", self.symbol, exc)
            self.is_syncing = False
            return
        except Exception as exc:
            logger.error("Unexpected error fetching snapshot for %s: %s", self.symbol, exc)
            self.is_syncing = False
            return

        # Snapshot received. Apply it to the local book.
        self.local_book.apply_snapshot(snapshot)

        # Wait briefly to ensure we have buffered events covering the snapshot
        # Since the WS is already buffering, we should have events that overlap
        await asyncio.sleep(0.5)

        # Drain the buffer and find the bridging event
        bridged = False
        while self.event_buffer:
            event = self.event_buffer.popleft()
            
            # Apply the event. The local book knows how to handle pre-sync events.
            violations = self.local_book.apply_event(event)
            
            if violations:
                # If we get a violation during sync drain (e.g. gap), we abort this sync attempt
                self.violations_history.extend(violations)
                logger.warning("Violation during buffer drain for %s: %s", self.symbol, violations[0].detail)
                self.is_syncing = False
                return
            
            if self.local_book.synchronized:
                bridged = True
                self.events_processed += 1
                break
            else:
                # Still searching for bridge (obsolete event dropped)
                self.duplicate_events += 1

        if bridged:
            # Drain the rest of the buffer sequentially
            while self.event_buffer:
                event = self.event_buffer.popleft()
                violations = self.local_book.apply_event(event)
                if violations:
                    self.violations_history.extend(violations)
                    self.resync_count += 1
                    self.is_syncing = False
                    return
                self.events_processed += 1
            
            logger.info("Successfully synchronized %s", self.symbol)
        else:
            logger.warning("Failed to bridge snapshot for %s (no valid events in buffer)", self.symbol)
            
        self.is_syncing = False
