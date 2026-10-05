"""
tests/test_ob_stress.py
"""

from datetime import datetime, timezone
import pytest

from market_data.ob_local import LocalOrderBook
from market_data.ob_models import OrderBookSnapshot, OrderBookEvent, OBViolationType


def test_duplicate_event_fails_pu_rule():
    book = LocalOrderBook("BTCUSDT")
    book.apply_snapshot(OrderBookSnapshot(
        symbol="BTCUSDT", last_update_id=100, 
        message_output_time=datetime.now(tz=timezone.utc), transaction_time=datetime.now(tz=timezone.utc),
        bids=[], asks=[], local_receipt_time=datetime.now(tz=timezone.utc)
    ))
    
    event1 = OrderBookEvent(
        symbol="BTCUSDT", event_time=datetime.now(tz=timezone.utc), transaction_time=datetime.now(tz=timezone.utc),
        first_update_id=99, final_update_id=101, previous_final_update_id=98,
        bids=[(100.0, 1.0)], asks=[], local_receipt_time=datetime.now(tz=timezone.utc)
    )
    book.apply_event(event1)
    assert book.synchronized
    
    # Duplicate event (same final_update_id and previous_final_update_id)
    violations = book.apply_event(event1)
    
    # It must fail because expected pu=101, but event1 has pu=98
    assert len(violations) == 1
    assert violations[0].violation_type == OBViolationType.SEQUENCE_GAP
    assert not book.synchronized

def test_out_of_order_event_fails_pu_rule():
    book = LocalOrderBook("BTCUSDT")
    book.apply_snapshot(OrderBookSnapshot(
        symbol="BTCUSDT", last_update_id=100, 
        message_output_time=datetime.now(tz=timezone.utc), transaction_time=datetime.now(tz=timezone.utc),
        bids=[], asks=[], local_receipt_time=datetime.now(tz=timezone.utc)
    ))
    
    bridge = OrderBookEvent(
        symbol="BTCUSDT", event_time=datetime.now(tz=timezone.utc), transaction_time=datetime.now(tz=timezone.utc),
        first_update_id=99, final_update_id=101, previous_final_update_id=98,
        bids=[], asks=[], local_receipt_time=datetime.now(tz=timezone.utc)
    )
    book.apply_event(bridge)
    assert book.synchronized
    
    event2 = OrderBookEvent(
        symbol="BTCUSDT", event_time=datetime.now(tz=timezone.utc), transaction_time=datetime.now(tz=timezone.utc),
        first_update_id=102, final_update_id=105, previous_final_update_id=101,
        bids=[], asks=[], local_receipt_time=datetime.now(tz=timezone.utc)
    )
    
    event3 = OrderBookEvent(
        symbol="BTCUSDT", event_time=datetime.now(tz=timezone.utc), transaction_time=datetime.now(tz=timezone.utc),
        first_update_id=106, final_update_id=110, previous_final_update_id=105,
        bids=[], asks=[], local_receipt_time=datetime.now(tz=timezone.utc)
    )
    
    # Apply event3 before event2 (out of order)
    violations = book.apply_event(event3)
    
    # Should fail pu rule (expected 101, got 105)
    assert len(violations) == 1
    assert violations[0].violation_type == OBViolationType.SEQUENCE_GAP
    assert not book.synchronized


def test_bridge_stress_event_starts_after_snapshot():
    # If the first processed event has U > lastUpdateId, it means there is a gap.
    book = LocalOrderBook("BTCUSDT")
    book.apply_snapshot(OrderBookSnapshot(
        symbol="BTCUSDT", last_update_id=100, 
        message_output_time=datetime.now(tz=timezone.utc), transaction_time=datetime.now(tz=timezone.utc),
        bids=[], asks=[], local_receipt_time=datetime.now(tz=timezone.utc)
    ))
    
    event = OrderBookEvent(
        symbol="BTCUSDT", event_time=datetime.now(tz=timezone.utc), transaction_time=datetime.now(tz=timezone.utc),
        first_update_id=102, final_update_id=105, previous_final_update_id=101,
        bids=[], asks=[], local_receipt_time=datetime.now(tz=timezone.utc)
    )
    
    violations = book.apply_event(event)
    
    assert len(violations) == 1
    assert violations[0].violation_type == OBViolationType.SEQUENCE_GAP
    assert not book.synchronized


def test_zero_quantity_removes_nonexistent_level():
    book = LocalOrderBook("BTCUSDT")
    book.apply_snapshot(OrderBookSnapshot(
        symbol="BTCUSDT", last_update_id=100, 
        message_output_time=datetime.now(tz=timezone.utc), transaction_time=datetime.now(tz=timezone.utc),
        bids=[(100.0, 1.0)], asks=[], local_receipt_time=datetime.now(tz=timezone.utc)
    ))
    
    bridge = OrderBookEvent(
        symbol="BTCUSDT", event_time=datetime.now(tz=timezone.utc), transaction_time=datetime.now(tz=timezone.utc),
        first_update_id=99, final_update_id=101, previous_final_update_id=98,
        bids=[(99.0, 0.0)], # 99.0 doesn't exist
        asks=[], local_receipt_time=datetime.now(tz=timezone.utc)
    )
    violations = book.apply_event(bridge)
    
    assert not violations
    assert 99.0 not in book.bids
    assert book.bids == {100.0: 1.0}
