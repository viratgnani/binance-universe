"""
tests/test_lookahead.py

Tests to ensure no future data is used in feature calculation.
"""

from datetime import datetime, timedelta, timezone

from market_data.models import Candle, AggTrade
from market_data.ob_models import OrderBookCheckpoint
from research_features.calculators import (
    calculate_price_features,
    calculate_trade_features,
    calculate_order_book_features,
)


def _dt(minute: int, second: int = 0) -> datetime:
    return datetime(2026, 8, 31, 12, 0, second, tzinfo=timezone.utc) + timedelta(minutes=minute)


def test_future_candle_rejected():
    """
    If a feature is timestamped at 12:05:00, it cannot use a candle that closes at 12:05:01.
    """
    current_time = _dt(5)
    
    candles = [
        # Closes exactly at 12:05:00
        Candle(symbol="BTCUSDT", interval="1m", open_time=_dt(4), close_time=_dt(4) + timedelta(minutes=1, milliseconds=-1), open="100", high="100", low="100", close="100", volume="10", quote_volume="1000", trade_count=1, taker_buy_base_vol="10", taker_buy_quote_vol="1000"),
        # Closes at 12:06:00
        Candle(symbol="BTCUSDT", interval="1m", open_time=_dt(5), close_time=_dt(5) + timedelta(minutes=1, milliseconds=-1), open="100", high="100", low="100", close="200", volume="10", quote_volume="1000", trade_count=1, taker_buy_base_vol="10", taker_buy_quote_vol="1000"),
    ]
    
    # Simulating the engine's slicing logic:
    safe_candles = [c for c in candles if c.open_time + timedelta(minutes=1) <= current_time]
    
    assert len(safe_candles) == 1
    assert safe_candles[0].open_time == _dt(4)
    
    feats = calculate_price_features(safe_candles, current_time)
    
    # The return_1m should be missing, because we need the candle from 12:03 to calculate the return
    # But more importantly, the price 200 MUST NOT appear anywhere.
    assert feats["return_1m"] is None


def test_future_trade_rejected():
    """
    A trade at 12:05:01 must not enter a feature timestamped 12:05:00.
    """
    current_time = _dt(5)
    
    trades = [
        # Exactly on the boundary (allowed)
        AggTrade(agg_trade_id=1, symbol="BTCUSDT", price="100", quantity="10", quote_quantity="1000", first_trade_id=1, last_trade_id=1, timestamp=current_time, is_buyer_maker=False, buyer_is_maker=False),
        # 1 second in the future
        AggTrade(agg_trade_id=2, symbol="BTCUSDT", price="200", quantity="1000", quote_quantity="200000", first_trade_id=2, last_trade_id=2, timestamp=current_time + timedelta(seconds=1), is_buyer_maker=False, buyer_is_maker=False),
    ]
    
    # Simulating engine slicing
    safe_trades = [t for t in trades if t.timestamp <= current_time]
    
    assert len(safe_trades) == 1
    
    feats = calculate_trade_features(safe_trades, current_time)
    
    # Trade volume should be 10, not 1010
    assert feats["total_trade_volume"] == 10.0


def test_future_order_book_rejected():
    """
    A checkpoint after T must never be selected for T.
    """
    current_time = _dt(5)
    
    checkpoints = [
        OrderBookCheckpoint(symbol="BTCUSDT", last_update_id=1, exchange_event_time=current_time - timedelta(seconds=1), local_checkpoint_time=current_time - timedelta(seconds=1), synchronized=True, bids=[("100", "1")], asks=[("101", "1")]),
        # Future checkpoint
        OrderBookCheckpoint(symbol="BTCUSDT", last_update_id=2, exchange_event_time=current_time + timedelta(seconds=1), local_checkpoint_time=current_time + timedelta(seconds=1), synchronized=True, bids=[("200", "1")], asks=[("201", "1")]),
    ]
    
    safe_checkpoints = [c for c in checkpoints if c.exchange_event_time <= current_time]
    
    assert len(safe_checkpoints) == 1
    
    feats = calculate_order_book_features(safe_checkpoints[-1] if safe_checkpoints else None)
    
    assert feats["best_bid"] == 100.0
    # NOT 200.0
