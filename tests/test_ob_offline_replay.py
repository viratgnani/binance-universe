"""
tests/test_ob_offline_replay.py
"""

from datetime import datetime, timezone
import pytest

from market_data.ob_local import LocalOrderBook
from market_data.ob_models import OrderBookSnapshot, OrderBookEvent


def test_offline_replay_vs_live_checkpoint():
    """
    Verifies that (Stored Checkpoint 1 + Stored Raw Events) == Stored Checkpoint 2.
    """
    t0 = datetime.now(tz=timezone.utc)
    
    # 1. Live execution simulation
    live_book = LocalOrderBook("BTCUSDT")
    
    # Initial snapshot
    snapshot = OrderBookSnapshot(
        symbol="BTCUSDT",
        last_update_id=100,
        message_output_time=t0,
        transaction_time=t0,
        bids=[(100.0, 5.0), (99.0, 10.0)],
        asks=[(101.0, 5.0), (102.0, 10.0)],
        local_receipt_time=t0
    )
    live_book.apply_snapshot(snapshot)
    
    # Bridge event to sync
    bridge = OrderBookEvent(
        symbol="BTCUSDT", event_time=t0, transaction_time=t0,
        first_update_id=99, final_update_id=101, previous_final_update_id=98,
        bids=[(100.0, 6.0)], asks=[], local_receipt_time=t0
    )
    live_book.apply_event(bridge)
    assert live_book.synchronized
    
    # Checkpoint 1
    chk1 = live_book.get_checkpoint()
    
    # Subsequent events (the raw stream)
    event1 = OrderBookEvent(
        symbol="BTCUSDT", event_time=t0, transaction_time=t0,
        first_update_id=102, final_update_id=105, previous_final_update_id=101,
        bids=[(99.0, 0.0)], asks=[(101.5, 2.0)], local_receipt_time=t0
    )
    live_book.apply_event(event1)
    
    event2 = OrderBookEvent(
        symbol="BTCUSDT", event_time=t0, transaction_time=t0,
        first_update_id=106, final_update_id=107, previous_final_update_id=105,
        bids=[(99.5, 8.0)], asks=[(102.0, 0.0)], local_receipt_time=t0
    )
    live_book.apply_event(event2)
    
    # Checkpoint 2 (Live)
    chk2_live = live_book.get_checkpoint()
    
    # 2. Offline replay simulation
    offline_book = LocalOrderBook("BTCUSDT")
    
    # Init offline book using Checkpoint 1 instead of a REST snapshot
    # We can fake a REST snapshot from the checkpoint
    fake_snapshot = OrderBookSnapshot(
        symbol=chk1.symbol,
        last_update_id=chk1.last_update_id,
        message_output_time=chk1.exchange_event_time,
        transaction_time=chk1.exchange_event_time,
        bids=chk1.bids,
        asks=chk1.asks,
        local_receipt_time=chk1.local_checkpoint_time
    )
    offline_book.apply_snapshot(fake_snapshot)
    offline_book.synchronized = True  # We trust the checkpoint
    
    # Replay events
    offline_book.apply_event(event1)
    offline_book.apply_event(event2)
    
    # Checkpoint 2 (Offline)
    chk2_offline = offline_book.get_checkpoint()
    
    # Compare
    assert chk2_offline.bids == chk2_live.bids
    assert chk2_offline.asks == chk2_live.asks
    assert chk2_offline.last_update_id == chk2_live.last_update_id
