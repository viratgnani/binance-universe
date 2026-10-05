"""
tests/test_feature_math.py

Numerical fixture tests for the Research Feature Layer V1 calculators.
"""

import math
from datetime import datetime, timedelta, timezone

from market_data.models import Candle, AggTrade
from market_data.ob_models import OrderBookCheckpoint
from research_features.calculators import (
    calculate_price_features,
    calculate_volatility_features,
    calculate_volume_features,
    calculate_trade_features,
    calculate_order_book_features,
)


def _dt(minute: int) -> datetime:
    return datetime(2026, 8, 31, 12, 0, tzinfo=timezone.utc) + timedelta(minutes=minute)


def test_price_features():
    # 5 minutes of data
    candles = [
        Candle(symbol="BTCUSDT", interval="1m", open_time=_dt(-1), close_time=_dt(-1) + timedelta(minutes=1, milliseconds=-1), open="100", high="100", low="100", close="100", volume="10", quote_volume="1000", trade_count=1, taker_buy_base_vol="10", taker_buy_quote_vol="1000"),
        Candle(symbol="BTCUSDT", interval="1m", open_time=_dt(0), close_time=_dt(0) + timedelta(minutes=1, milliseconds=-1), open="100", high="100", low="100", close="100", volume="10", quote_volume="1000", trade_count=1, taker_buy_base_vol="10", taker_buy_quote_vol="1000"),
        Candle(symbol="BTCUSDT", interval="1m", open_time=_dt(1), close_time=_dt(1) + timedelta(minutes=1, milliseconds=-1), open="100", high="100", low="100", close="102", volume="10", quote_volume="1000", trade_count=1, taker_buy_base_vol="10", taker_buy_quote_vol="1000"),
        Candle(symbol="BTCUSDT", interval="1m", open_time=_dt(2), close_time=_dt(2) + timedelta(minutes=1, milliseconds=-1), open="102", high="102", low="102", close="105", volume="10", quote_volume="1000", trade_count=1, taker_buy_base_vol="10", taker_buy_quote_vol="1000"),
        Candle(symbol="BTCUSDT", interval="1m", open_time=_dt(3), close_time=_dt(3) + timedelta(minutes=1, milliseconds=-1), open="105", high="105", low="105", close="95", volume="10", quote_volume="1000", trade_count=1, taker_buy_base_vol="10", taker_buy_quote_vol="1000"),
        Candle(symbol="BTCUSDT", interval="1m", open_time=_dt(4), close_time=_dt(4) + timedelta(minutes=1, milliseconds=-1), open="95", high="110", low="90", close="114", volume="10", quote_volume="1000", trade_count=1, taker_buy_base_vol="10", taker_buy_quote_vol="1000"),
    ]
    
    # Feature timestamp is exactly the close of the last candle
    current_time = _dt(5)
    
    feats = calculate_price_features(candles, current_time)
    
    # return_1m: (114 - 95) / 95 = 19 / 95 = 0.2
    assert math.isclose(feats["return_1m"], 0.2)
    # return_5m: (114 - 100) / 100 = 0.14
    assert math.isclose(feats["return_5m"], 0.14)
    # return_15m: None (not enough history)
    assert feats["return_15m"] is None
    

def test_volatility_features():
    candles = []
    # Generate 6 candles to get 5 returns for a 5m volatility window
    prices = [100.0, 101.0, 99.0, 102.0, 98.0, 105.0]
    for i, p in enumerate(prices):
        candles.append(Candle(
            symbol="BTCUSDT", interval="1m", open_time=_dt(i), close_time=_dt(i) + timedelta(minutes=1, milliseconds=-1),
            open=str(p), high=str(p+1), low=str(p-1), close=str(p), volume="10", quote_volume="1000", trade_count=1, taker_buy_base_vol="10", taker_buy_quote_vol="1000"
        ))
        
    current_time = _dt(6)
    
    feats = calculate_volatility_features(candles, current_time)
    
    # range_pct of last candle (index 5): high 106, low 104, close 105 -> 2/105
    assert math.isclose(feats["range_pct"], 2.0 / 105.0)
    
    # returns: 
    # 1: (101-100)/100 = 0.01
    # 2: (99-101)/101 = -0.01980198
    # 3: (102-99)/99 = 0.03030303
    # 4: (98-102)/102 = -0.03921568
    # 5: (105-98)/98 = 0.07142857
    rets = [0.01, -0.01980198, 0.03030303, -0.03921568, 0.07142857]
    mean_ret = sum(rets) / 5
    var = sum((r - mean_ret)**2 for r in rets) / 5
    expected_vol = math.sqrt(var)
    
    assert math.isclose(feats["volatility_5m"], expected_vol, rel_tol=1e-5)
    assert feats["volatility_15m"] is None


def test_volume_features():
    candles = []
    for i in range(60):
        # 1 volume for first 59 candles, 20 volume for the last candle
        vol = "20" if i == 59 else "1"
        candles.append(Candle(
            symbol="BTCUSDT", interval="1m", open_time=_dt(i), close_time=_dt(i) + timedelta(minutes=1, milliseconds=-1),
            open="100", high="100", low="100", close="100", volume=vol, quote_volume="100", trade_count=1, taker_buy_base_vol="10", taker_buy_quote_vol="100"
        ))
        
    current_time = _dt(60)
    
    feats = calculate_volume_features(candles, current_time)
    
    assert feats["volume_1m"] == 20.0
    assert feats["volume_5m"] == 20.0 + 4.0  # 1 last candle + 4 previous
    assert feats["volume_1h"] == 20.0 + 59.0
    
    mean_1h = 79.0 / 60.0
    assert math.isclose(feats["relative_volume"], 20.0 / mean_1h)


def test_trade_features():
    trades = [
        # Outside window (too old)
        AggTrade(agg_trade_id=1, symbol="BTCUSDT", price="100", quantity="1", quote_quantity="100", first_trade_id=1, last_trade_id=1, timestamp=_dt(0), is_buyer_maker=False, buyer_is_maker=False),
        # Exactly on the lower boundary (excluded by <= cutoff)
        AggTrade(agg_trade_id=2, symbol="BTCUSDT", price="100", quantity="2", quote_quantity="200", first_trade_id=2, last_trade_id=2, timestamp=_dt(1), is_buyer_maker=False, buyer_is_maker=False),
        # Inside window
        AggTrade(agg_trade_id=3, symbol="BTCUSDT", price="100", quantity="1", quote_quantity="100", first_trade_id=3, last_trade_id=3, timestamp=_dt(1) + timedelta(seconds=10), is_buyer_maker=False, buyer_is_maker=False),
        AggTrade(agg_trade_id=4, symbol="BTCUSDT", price="110", quantity="3", quote_quantity="330", first_trade_id=4, last_trade_id=4, timestamp=_dt(1) + timedelta(seconds=20), is_buyer_maker=False, buyer_is_maker=False),
        AggTrade(agg_trade_id=5, symbol="BTCUSDT", price="120", quantity="6", quote_quantity="720", first_trade_id=5, last_trade_id=5, timestamp=_dt(2), is_buyer_maker=False, buyer_is_maker=False),
    ]
    
    current_time = _dt(2)  # Window: (12:01:00, 12:02:00]
    
    feats = calculate_trade_features(trades, current_time)
    
    assert feats["trade_count"] == 3
    assert feats["total_trade_volume"] == 10.0
    assert feats["total_trade_quote_volume"] == (100*1 + 110*3 + 120*6)  # 100 + 330 + 720 = 1150
    assert feats["average_trade_size"] == 10.0 / 3
    # Quantities: 1, 3, 6 -> Median is 3
    assert feats["median_trade_size"] == 3.0


def test_order_book_features():
    bids = [("99.0", "1.0"), ("98.0", "2.0"), ("97.0", "3.0"), ("96.0", "4.0"), ("95.0", "5.0")]
    asks = [("101.0", "1.0"), ("102.0", "2.0"), ("103.0", "3.0"), ("104.0", "4.0"), ("105.0", "5.0")]
    
    checkpoint = OrderBookCheckpoint(
        symbol="BTCUSDT",
        last_update_id=1,
        exchange_event_time=_dt(1),
        local_checkpoint_time=_dt(1),
        synchronized=True,
        bids=bids,
        asks=asks
    )
    
    feats = calculate_order_book_features(checkpoint)
    
    assert feats["best_bid"] == 99.0
    assert feats["best_ask"] == 101.0
    assert feats["spread"] == 2.0
    assert feats["mid_price"] == 100.0
    assert feats["spread_bps"] == (2.0 / 100.0) * 10000
    
    assert feats["bid_depth_5"] == 15.0
    assert feats["ask_depth_5"] == 15.0
    assert feats["depth_imbalance_5"] == 0.0
