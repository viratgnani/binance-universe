"""
tests/test_ob_stale.py
"""

from datetime import datetime, timezone
import pytest
import asyncio
from unittest.mock import AsyncMock

from market_data.ob_manager import OrderBookManager
from market_data.ob_models import OrderBookSnapshot


@pytest.fixture
def manager():
    mgr = OrderBookManager(symbols=["BTCUSDT"], checkpoint_interval_sec=0.1, stale_timeout_sec=0.2)
    return mgr


@pytest.mark.asyncio
async def test_stale_stream_triggers_resync(manager):
    await manager.start()
    
    # Mock client fetch
    manager.client._get = AsyncMock(return_value={
        "lastUpdateId": 100,
        "E": 1000,
        "T": 1000,
        "bids": [],
        "asks": []
    })
    
    sync_mgr = manager.sync_managers["BTCUSDT"]
    
    # Send some raw events to establish sync
    sync_mgr.on_raw_event({
        "s": "BTCUSDT", "E": 1001, "T": 1001,
        "U": 96, "u": 105, "pu": 95, "b": [["100", "1"]], "a": []
    })
    
    await sync_mgr._sync_routine()
    
    assert sync_mgr.local_book.synchronized
    
    # Now we just wait for checkpoint loop to notice the staleness
    # checkpoint interval is 0.1, stale_timeout is 0.2
    await asyncio.sleep(0.3)
    
    # It should have triggered resync
    assert not sync_mgr.local_book.synchronized
    assert sync_mgr.stale_incidents > 0
    assert any(v.violation_type == "STALE_STREAM" for v in sync_mgr.violations_history)
    
    await manager.stop()
