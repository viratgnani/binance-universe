"""
tests/test_ob_local.py
"""

from datetime import datetime, timezone
import pytest

from market_data.ob_local import LocalOrderBook
from market_data.ob_models import OrderBookSnapshot, OrderBookEvent, OBViolationType


def test_apply_snapshot_initializes_book():
    book = LocalOrderBook("BTCUSDT")
    snapshot = OrderBookSnapshot(
        symbol="BTCUSDT",
        last_update_id=100,
        message_output_time=datetime.now(tz=timezone.utc),
        transaction_time=datetime.now(tz=timezone.utc),
        bids=[(100.0, 1.5), (99.0, 2.0)],
        asks=[(101.0, 1.0), (102.0, 3.0)],
        local_receipt_time=datetime.now(tz=timezone.utc),
    )
    book.apply_snapshot(snapshot)
    
    assert book.last_update_id == 100
    assert not book.synchronized
    assert book.bids == {100.0: 1.5, 99.0: 2.0}
    assert book.asks == {101.0: 1.0, 102.0: 3.0}

def test_bridge_event_synchronizes_book():
    book = LocalOrderBook("BTCUSDT")
    book.apply_snapshot(OrderBookSnapshot(
        symbol="BTCUSDT", last_update_id=100, 
        message_output_time=datetime.now(tz=timezone.utc), transaction_time=datetime.now(tz=timezone.utc),
        bids=[], asks=[], local_receipt_time=datetime.now(tz=timezone.utc)
    ))
    
    event = OrderBookEvent(
        symbol="BTCUSDT", event_time=datetime.now(tz=timezone.utc), transaction_time=datetime.now(tz=timezone.utc),
        first_update_id=99, final_update_id=101, previous_final_update_id=98,
        bids=[(100.0, 2.5)], asks=[], local_receipt_time=datetime.now(tz=timezone.utc)
    )
    violations = book.apply_event(event)
    
    assert not violations
    assert book.synchronized
    assert book.last_update_id == 101
    assert book.bids == {100.0: 2.5}

def test_obsolete_event_ignored():
    book = LocalOrderBook("BTCUSDT")
    book.last_update_id = 100
    book.synchronized = False
    
    event = OrderBookEvent(
        symbol="BTCUSDT", event_time=datetime.now(tz=timezone.utc), transaction_time=datetime.now(tz=timezone.utc),
        first_update_id=98, final_update_id=99, previous_final_update_id=97,
        bids=[], asks=[], local_receipt_time=datetime.now(tz=timezone.utc)
    )
    violations = book.apply_event(event)
    
    assert not violations
    assert not book.synchronized
    assert book.last_update_id == 100

def test_apply_event_removes_level_when_qty_zero():
    book = LocalOrderBook("BTCUSDT")
    book.bids = {100.0: 1.5, 99.0: 2.0}
    book.last_update_id = 100
    book.synchronized = True
    
    event = OrderBookEvent(
        symbol="BTCUSDT", event_time=datetime.now(tz=timezone.utc), transaction_time=datetime.now(tz=timezone.utc),
        first_update_id=101, final_update_id=101, previous_final_update_id=100,
        bids=[(100.0, 0.0)], asks=[], local_receipt_time=datetime.now(tz=timezone.utc)
    )
    book.apply_event(event)
    
    assert 100.0 not in book.bids
    assert book.bids == {99.0: 2.0}

def test_apply_event_detects_sequence_gap():
    book = LocalOrderBook("BTCUSDT")
    book.last_update_id = 100
    book.synchronized = True
    
    event = OrderBookEvent(
        symbol="BTCUSDT", event_time=datetime.now(tz=timezone.utc), transaction_time=datetime.now(tz=timezone.utc),
        first_update_id=102, final_update_id=103, previous_final_update_id=101, # Gap! Expected pu=100
        bids=[], asks=[], local_receipt_time=datetime.now(tz=timezone.utc)
    )
    violations = book.apply_event(event)
    
    assert len(violations) == 1
    assert violations[0].violation_type == OBViolationType.SEQUENCE_GAP
    assert not book.synchronized

def test_detects_crossed_book():
    book = LocalOrderBook("BTCUSDT")
    book.synchronized = True
    book.bids = {100.0: 1.0}
    book.asks = {99.0: 1.0}
    
    anomaly = book.check_crossed_book()
    assert anomaly is not None
    assert anomaly.violation_type == OBViolationType.CROSSED_BOOK

def test_checkpoint_sorts_correctly():
    book = LocalOrderBook("BTCUSDT")
    book.synchronized = True
    book.bids = {99.0: 1.0, 100.0: 2.0}
    book.asks = {102.0: 3.0, 101.0: 4.0}
    
    chk = book.get_checkpoint()
    
    assert chk.bids == [(100.0, 2.0), (99.0, 1.0)]
    assert chk.asks == [(101.0, 4.0), (102.0, 3.0)]
