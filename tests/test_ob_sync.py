"""
tests/test_ob_sync.py
"""

import pytest
from datetime import datetime, timezone
import asyncio
from unittest.mock import AsyncMock

from market_data.ob_sync import OrderBookSyncManager
from market_data.ob_models import OrderBookSnapshot, OrderBookEvent
from market_data.client import MarketDataClient


@pytest.fixture
def mock_client():
    client = MarketDataClient()
    client._get = AsyncMock()
    return client

@pytest.mark.asyncio
async def test_sync_manager_buffers_and_bridges(mock_client):
    manager = OrderBookSyncManager("BTCUSDT", mock_client)
    
    # Send some raw events to buffer
    # snapshot will have last_update_id = 100
    
    # Obsolete event
    manager.on_raw_event({
        "s": "BTCUSDT", "E": 1000, "T": 1000,
        "U": 90, "u": 95, "pu": 89, "b": [], "a": []
    })
    
    # Bridge event
    manager.on_raw_event({
        "s": "BTCUSDT", "E": 1001, "T": 1001,
        "U": 96, "u": 105, "pu": 95, "b": [["100", "1"]], "a": []
    })
    
    # Next valid event
    manager.on_raw_event({
        "s": "BTCUSDT", "E": 1002, "T": 1002,
        "U": 106, "u": 110, "pu": 105, "b": [["101", "1"]], "a": []
    })
    
    assert len(manager.event_buffer) == 3
    assert not manager.local_book.synchronized
    
    # Provide the snapshot
    mock_client._get.return_value = {
        "lastUpdateId": 100,
        "E": 1000,
        "T": 1000,
        "bids": [],
        "asks": []
    }
    
    # trigger sync routine directly
    await manager._sync_routine()
    
    assert manager.local_book.synchronized
    assert manager.local_book.last_update_id == 110
    assert manager.events_processed == 2
    assert manager.duplicate_events == 1
    assert 101.0 in manager.local_book.bids

@pytest.mark.asyncio
async def test_sync_fails_if_no_bridge(mock_client):
    manager = OrderBookSyncManager("BTCUSDT", mock_client)
    
    # Obsolete
    manager.on_raw_event({
        "s": "BTCUSDT", "E": 1000, "T": 1000,
        "U": 90, "u": 95, "pu": 89, "b": [], "a": []
    })
    
    mock_client._get.return_value = {
        "lastUpdateId": 100,
        "E": 1000, "T": 1000, "bids": [], "asks": []
    }
    
    await manager._sync_routine()
    
    assert not manager.local_book.synchronized
    assert not manager.is_syncing
