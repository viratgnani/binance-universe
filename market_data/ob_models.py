"""
market_data/ob_models.py

Pydantic models for the Order Book V2 implementation.
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class OrderBookEvent(BaseModel):
    """
    Raw Binance WebSocket diff.depth event.
    Preserves exact exchange timestamps and update IDs.
    """
    model_config = ConfigDict(frozen=True)

    symbol: str
    event_time: datetime
    transaction_time: datetime
    first_update_id: int
    final_update_id: int
    previous_final_update_id: int
    bids: list[tuple[float, float]]  # [(price, qty), ...]
    asks: list[tuple[float, float]]
    local_receipt_time: datetime


class OrderBookSnapshot(BaseModel):
    """
    Raw Binance REST snapshot response.
    """
    model_config = ConfigDict(frozen=True)

    symbol: str
    last_update_id: int
    message_output_time: datetime
    transaction_time: datetime
    bids: list[tuple[float, float]]
    asks: list[tuple[float, float]]
    local_receipt_time: datetime


class OrderBookCheckpoint(BaseModel):
    """
    A fully reconstructed local order book state at a given moment.
    """
    model_config = ConfigDict(frozen=True)

    symbol: str
    last_update_id: int
    exchange_event_time: datetime
    bids: list[tuple[float, float]]  # Ordered descending by price
    asks: list[tuple[float, float]]  # Ordered ascending by price
    synchronized: bool
    local_checkpoint_time: datetime


class OBViolationType(str, Enum):
    CROSSED_BOOK = "CROSSED_BOOK"
    SEQUENCE_GAP = "SEQUENCE_GAP"
    INVALID_PRICE = "INVALID_PRICE"
    INVALID_QTY = "INVALID_QTY"
    STALE_STREAM = "STALE_STREAM"


class OrderBookViolation(BaseModel):
    """
    Represents an integrity anomaly detected during reconstruction.
    """
    model_config = ConfigDict(frozen=True)

    symbol: str
    violation_type: OBViolationType
    detail: str
    detected_at: datetime = Field(default_factory=datetime.utcnow)

