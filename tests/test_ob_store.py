"""
tests/test_ob_store.py
"""

from datetime import datetime, timezone
import pytest
from pathlib import Path

from market_data.ob_store import OrderBookStore, OrderBookCheckpointStore
from market_data.ob_models import OrderBookEvent, OrderBookCheckpoint


def test_save_and_load_events(tmp_path):
    store = OrderBookStore(data_dir=tmp_path)
    
    event = OrderBookEvent(
        symbol="BTCUSDT",
        event_time=datetime(2026, 9, 1, 10, 0, tzinfo=timezone.utc),
        transaction_time=datetime(2026, 9, 1, 10, 0, tzinfo=timezone.utc),
        first_update_id=1, final_update_id=2, previous_final_update_id=0,
        bids=[(100.0, 1.0)], asks=[], local_receipt_time=datetime.now(tz=timezone.utc)
    )
    
    written = store.save_events([event])
    assert written == 1
    
    loaded = store.load_events(
        "BTCUSDT", 
        datetime(2026, 9, 1, 9, 0, tzinfo=timezone.utc),
        datetime(2026, 9, 1, 11, 0, tzinfo=timezone.utc)
    )
    assert len(loaded) == 1
    assert loaded[0].final_update_id == 2


def test_save_checkpoints(tmp_path):
    store = OrderBookCheckpointStore(data_dir=tmp_path)
    
    checkpoint = OrderBookCheckpoint(
        symbol="BTCUSDT", last_update_id=10, 
        exchange_event_time=datetime(2026, 9, 1, 10, 0, tzinfo=timezone.utc),
        bids=[(100.0, 1.0)], asks=[(101.0, 1.0)], synchronized=True,
        local_checkpoint_time=datetime.now(tz=timezone.utc)
    )
    
    written = store.save_checkpoints([checkpoint])
    assert written == 1
    
    assert (tmp_path / "BTCUSDT" / "20260901.jsonl").exists()
