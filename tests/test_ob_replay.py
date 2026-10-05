"""
tests/test_ob_replay.py
"""

from datetime import datetime, timezone
import pytest
import hashlib

from market_data.ob_local import LocalOrderBook
from market_data.ob_models import OrderBookSnapshot, OrderBookEvent


def get_checksum(book: LocalOrderBook) -> str:
    """
    Simulates a checksum generation based on the sorted book state.
    """
    chk = book.get_checkpoint()
    data = []
    for p, q in chk.bids:
        data.append(f"{p}:{q}")
    for p, q in chk.asks:
        data.append(f"{p}:{q}")
    return hashlib.md5(",".join(data).encode()).hexdigest()

def test_replay_reconstructs_correct_state():
    """
    Replay test requested by user.
    Simulates receiving a snapshot, then replaying a sequence of events,
    and verifying the deterministic checksum of the final state.
    """
    book = LocalOrderBook("BTCUSDT")
    
    t0 = datetime.now(tz=timezone.utc)
    
    snapshot = OrderBookSnapshot(
        symbol="BTCUSDT",
        last_update_id=10,
        message_output_time=t0,
        transaction_time=t0,
        bids=[(100.0, 5.0), (99.0, 10.0)],
        asks=[(101.0, 5.0), (102.0, 10.0)],
        local_receipt_time=t0
    )
    book.apply_snapshot(snapshot)
    
    # Bridge event
    event1 = OrderBookEvent(
        symbol="BTCUSDT", event_time=t0, transaction_time=t0,
        first_update_id=9, final_update_id=12, previous_final_update_id=8,
        bids=[(100.0, 2.0), (99.0, 0.0)], # update 100, remove 99
        asks=[(103.0, 1.0)],              # add 103
        local_receipt_time=t0
    )
    
    event2 = OrderBookEvent(
        symbol="BTCUSDT", event_time=t0, transaction_time=t0,
        first_update_id=13, final_update_id=13, previous_final_update_id=12,
        bids=[(99.5, 3.0)],               # add 99.5
        asks=[(101.0, 0.0)],              # remove 101
        local_receipt_time=t0
    )
    
    violations1 = book.apply_event(event1)
    assert not violations1
    assert book.synchronized
    
    violations2 = book.apply_event(event2)
    assert not violations2
    assert book.synchronized
    
    assert book.last_update_id == 13
    
    expected_bids = [(100.0, 2.0), (99.5, 3.0)]
    expected_asks = [(102.0, 10.0), (103.0, 1.0)]
    
    chk = book.get_checkpoint()
    assert chk.bids == expected_bids
    assert chk.asks == expected_asks
    
    assert get_checksum(book)
