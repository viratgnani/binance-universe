"""
market_data/ob_local.py

Maintains the reconstructed order book state for a single symbol.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone

from market_data.ob_models import (
    OrderBookCheckpoint,
    OrderBookEvent,
    OrderBookSnapshot,
    OBViolationType,
    OrderBookViolation,
)

logger = logging.getLogger(__name__)


class LocalOrderBook:
    """
    Maintains the local order book state by applying a snapshot and subsequent
    diff-depth WebSocket events, enforcing Binance's strict update sequence rules.
    """

    def __init__(self, symbol: str) -> None:
        self.symbol = symbol
        self.bids: dict[float, float] = {}
        self.asks: dict[float, float] = {}
        self.last_update_id: int | None = None
        self.exchange_event_time: datetime | None = None
        self.synchronized: bool = False

    def apply_snapshot(self, snapshot: OrderBookSnapshot) -> None:
        """
        Initialises the order book from a REST snapshot.
        Overwrites any existing state.
        """
        self.bids.clear()
        self.asks.clear()

        for price, qty in snapshot.bids:
            if qty > 0:
                self.bids[price] = qty

        for price, qty in snapshot.asks:
            if qty > 0:
                self.asks[price] = qty

        self.last_update_id = snapshot.last_update_id
        self.exchange_event_time = snapshot.message_output_time
        # Only become synchronized once the first valid event is applied
        self.synchronized = False
        logger.debug(
            "LocalOrderBook: applied snapshot for %s, lastUpdateId=%d",
            self.symbol,
            self.last_update_id,
        )

    def apply_event(self, event: OrderBookEvent) -> list[OrderBookViolation]:
        """
        Applies a raw diff-depth WebSocket event to the local book.
        Enforces update-ID continuity rules. Returns a list of violations if any.
        """
        violations: list[OrderBookViolation] = []

        if self.last_update_id is None:
            # We haven't received a snapshot yet.
            return []

        # Sequence validation
        if not self.synchronized:
            # We are waiting for the first valid event to bridge the snapshot
            if event.final_update_id <= self.last_update_id:
                # Obsolete event, safely ignore
                return []
            
            if event.first_update_id <= self.last_update_id and event.final_update_id >= self.last_update_id:
                # Valid bridging event found!
                self.synchronized = True
                logger.debug(
                    "LocalOrderBook: %s bridged successfully. U=%d <= %d <= u=%d",
                    self.symbol,
                    event.first_update_id,
                    self.last_update_id,
                    event.final_update_id,
                )
            else:
                # Gap detected between snapshot and this event
                self.synchronized = False
                violations.append(
                    OrderBookViolation(
                        symbol=self.symbol,
                        violation_type=OBViolationType.SEQUENCE_GAP,
                        detail=(
                            f"Bridge gap: snapshot={self.last_update_id}, "
                            f"event U={event.first_update_id}, u={event.final_update_id}"
                        ),
                    )
                )
                return violations
        else:
            # We are synchronized; check strict continuous progression
            if event.previous_final_update_id != self.last_update_id:
                self.synchronized = False
                violations.append(
                    OrderBookViolation(
                        symbol=self.symbol,
                        violation_type=OBViolationType.SEQUENCE_GAP,
                        detail=(
                            f"Sequence gap: expected pu={self.last_update_id}, "
                            f"got pu={event.previous_final_update_id} (u={event.final_update_id})"
                        ),
                    )
                )
                return violations

        # Process the event modifications
        for price, qty in event.bids:
            if price <= 0:
                violations.append(
                    OrderBookViolation(
                        symbol=self.symbol,
                        violation_type=OBViolationType.INVALID_PRICE,
                        detail=f"Invalid bid price: {price}",
                    )
                )
            elif qty < 0:
                violations.append(
                    OrderBookViolation(
                        symbol=self.symbol,
                        violation_type=OBViolationType.INVALID_QTY,
                        detail=f"Invalid bid quantity: {qty} at price {price}",
                    )
                )
            elif qty == 0.0:
                self.bids.pop(price, None)
            else:
                self.bids[price] = qty

        for price, qty in event.asks:
            if price <= 0:
                violations.append(
                    OrderBookViolation(
                        symbol=self.symbol,
                        violation_type=OBViolationType.INVALID_PRICE,
                        detail=f"Invalid ask price: {price}",
                    )
                )
            elif qty < 0:
                violations.append(
                    OrderBookViolation(
                        symbol=self.symbol,
                        violation_type=OBViolationType.INVALID_QTY,
                        detail=f"Invalid ask quantity: {qty} at price {price}",
                    )
                )
            elif qty == 0.0:
                self.asks.pop(price, None)
            else:
                self.asks[price] = qty

        self.last_update_id = event.final_update_id
        self.exchange_event_time = event.event_time

        return violations

    def check_crossed_book(self) -> OrderBookViolation | None:
        """
        Check if best bid >= best ask.
        Note: Transient crossed books can occasionally occur during extreme volatility,
        but it represents a significant anomaly worth flagging.
        """
        if not self.synchronized:
            return None

        if not self.bids or not self.asks:
            return None

        best_bid = max(self.bids.keys())
        best_ask = min(self.asks.keys())

        if best_bid >= best_ask:
            return OrderBookViolation(
                symbol=self.symbol,
                violation_type=OBViolationType.CROSSED_BOOK,
                detail=f"Crossed book: best_bid={best_bid} >= best_ask={best_ask}",
            )
        return None

    def get_checkpoint(self, depth: int | None = None) -> OrderBookCheckpoint:
        """
        Export the current state of the order book as a Checkpoint.
        Price levels are sorted (bids descending, asks ascending).
        """
        sorted_bids = sorted(self.bids.items(), key=lambda x: x[0], reverse=True)
        sorted_asks = sorted(self.asks.items(), key=lambda x: x[0])

        if depth is not None:
            sorted_bids = sorted_bids[:depth]
            sorted_asks = sorted_asks[:depth]

        return OrderBookCheckpoint(
            symbol=self.symbol,
            last_update_id=self.last_update_id or 0,
            exchange_event_time=self.exchange_event_time or datetime.now(tz=timezone.utc),
            bids=sorted_bids,
            asks=sorted_asks,
            synchronized=self.synchronized,
            local_checkpoint_time=datetime.now(tz=timezone.utc),
        )
