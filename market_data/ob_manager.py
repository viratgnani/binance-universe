"""
market_data/ob_manager.py

Orchestrates WebSocket connections and sync managers for multiple symbols.
"""

from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime, timezone
from typing import Any

import websockets
from websockets.exceptions import ConnectionClosed

from market_data.client import MarketDataClient
from market_data.ob_store import OrderBookCheckpointStore, OrderBookStore
from market_data.ob_sync import OrderBookSyncManager

logger = logging.getLogger(__name__)


class OrderBookManager:
    def __init__(
        self,
        symbols: list[str],
        checkpoint_interval_sec: float = 10.0,
        depth_limit: int = 1000,
        checkpoint_depth: int | None = 50,
        stale_timeout_sec: float = 30.0,
    ) -> None:
        self.symbols = symbols
        self.checkpoint_interval_sec = checkpoint_interval_sec
        self.depth_limit = depth_limit
        self.checkpoint_depth = checkpoint_depth
        self.stale_timeout_sec = stale_timeout_sec
        
        self.sync_managers: dict[str, OrderBookSyncManager] = {}
        self.raw_store = OrderBookStore()
        self.checkpoint_store = OrderBookCheckpointStore()
        self.ws_task: asyncio.Task[None] | None = None
        self.checkpoint_task: asyncio.Task[None] | None = None
        self._running = False
        self.client: MarketDataClient | None = None

    async def start(self) -> None:
        self._running = True
        self.client = MarketDataClient()
        await self.client.__aenter__()

        for symbol in self.symbols:
            self.sync_managers[symbol] = OrderBookSyncManager(
                symbol=symbol,
                client=self.client,
                depth_limit=self.depth_limit,
            )

        self.ws_task = asyncio.create_task(self._ws_loop())
        self.checkpoint_task = asyncio.create_task(self._checkpoint_loop())
        logger.info("OrderBookManager started for %d symbols", len(self.symbols))

    async def stop(self) -> None:
        self._running = False
        if self.ws_task:
            self.ws_task.cancel()
        if self.checkpoint_task:
            self.checkpoint_task.cancel()
        if self.client:
            await self.client.__aexit__()
        logger.info("OrderBookManager stopped.")

    async def _ws_loop(self) -> None:
        """
        Maintains a multiplexed WebSocket connection to Binance.
        """
        streams = "/".join([f"{s.lower()}@depth" for s in self.symbols])
        ws_url = f"wss://fstream.binance.com/stream?streams={streams}"
        
        backoff = 1.0
        while self._running:
            try:
                async with websockets.connect(ws_url, ping_interval=20, ping_timeout=20) as ws:
                    logger.info("Connected to Binance multiplexed WS.")
                    backoff = 1.0  # Reset backoff on successful connect
                    
                    # Ensure all managers re-sync on a fresh connection
                    for mgr in self.sync_managers.values():
                        mgr._trigger_sync()

                    async for message in ws:
                        if not self._running:
                            break
                        self._handle_message(message)
            except ConnectionClosed as exc:
                logger.warning("WS connection closed: %s. Reconnecting in %.1fs...", exc, backoff)
            except Exception as exc:
                logger.error("WS error: %s. Reconnecting in %.1fs...", exc, backoff)
            
            if self._running:
                await asyncio.sleep(backoff)
                backoff = min(backoff * 2, 60.0)

    def _handle_message(self, message: str) -> None:
        try:
            payload = json.loads(message)
        except json.JSONDecodeError:
            logger.error("Invalid JSON received from WS")
            return

        # Multiplexed payload looks like: {"stream": "btcusdt@depth", "data": {...}}
        if "data" not in payload or "stream" not in payload:
            return

        data = payload["data"]
        # Symbol in 's' is uppercase (e.g. BTCUSDT)
        if "s" not in data:
            return
            
        symbol = data["s"]
        if symbol in self.sync_managers:
            event = self.sync_managers[symbol].on_raw_event(data)
            if event is not None:
                # We can batch save these or save them individually.
                # In a high throughput system, we'd batch, but for now we'll write directly
                self.raw_store.save_events([event])

    async def _checkpoint_loop(self) -> None:
        import time
        from market_data.ob_models import OBViolationType, OrderBookViolation
        while self._running:
            await asyncio.sleep(self.checkpoint_interval_sec)
            try:
                checkpoints = []
                now = time.monotonic()
                for symbol, mgr in self.sync_managers.items():
                    # Stale check
                    if mgr.last_receipt_time is not None and now - mgr.last_receipt_time > self.stale_timeout_sec:
                        if mgr.local_book.synchronized:
                            logger.warning("Stream for %s is stale (>%.1fs). Triggering resync.", symbol, self.stale_timeout_sec)
                            mgr.stale_incidents += 1
                            anomaly = OrderBookViolation(
                                symbol=symbol,
                                violation_type=OBViolationType.STALE_STREAM,
                                detail=f"No events received for > {self.stale_timeout_sec}s"
                            )
                            mgr.violations_history.append(anomaly)
                            mgr._trigger_sync()
                            continue

                    if mgr.local_book.synchronized:
                        chk = mgr.local_book.get_checkpoint(depth=self.checkpoint_depth)
                        checkpoints.append(chk)
                        
                        # Also check for crossed book anomaly
                        anomaly = mgr.local_book.check_crossed_book()
                        if anomaly:
                            mgr.violations_history.append(anomaly)
                            logger.warning(anomaly.detail)
                            
                if checkpoints:
                    written = self.checkpoint_store.save_checkpoints(checkpoints)
                    logger.debug("Saved %d checkpoints across %d symbols", written, len(checkpoints))
            except Exception as exc:
                logger.error("Error in checkpoint loop: %s", exc)
