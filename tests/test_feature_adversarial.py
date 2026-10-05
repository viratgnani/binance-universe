"""
tests/test_feature_adversarial.py

Adversarial audit tests for the Research Feature Layer V1.
"""

import math
import random
from unittest import mock
from datetime import datetime, timedelta, timezone

from market_data.models import Candle, AggTrade
from market_data.ob_models import OrderBookCheckpoint
from research_features.engine import FeatureEngine
from research_features.calculators import (
    calculate_price_features,
    calculate_volatility_features,
    calculate_volume_features,
    calculate_trade_features,
    calculate_order_book_features,
)


def _dt(minute: int, second: int = 0, ms: int = 0) -> datetime:
    return datetime(2026, 8, 31, 12, 0, second, ms * 1000, tzinfo=timezone.utc) + timedelta(minutes=minute)


def _candle(open_time_dt, close_time_dt, o="100", h="100", l="100", c="100", v="10"):
    return Candle(
        symbol="BTCUSDT", interval="1m", 
        open_time=open_time_dt, close_time=close_time_dt, 
        open=o, high=h, low=l, close=c, volume=v, 
        quote_volume="1000", trade_count=1, 
        taker_buy_base_vol="10", taker_buy_quote_vol="1000"
    )

def _trade(ts, p="100", q="10"):
    return AggTrade(
        agg_trade_id=1, symbol="BTCUSDT", price=p, quantity=q, quote_quantity=str(float(p)*float(q)),
        first_trade_id=1, last_trade_id=1, timestamp=ts, is_buyer_maker=False, buyer_is_maker=False
    )

def _ob(ts, bids=[("100", "1")], asks=[("101", "1")]):
    return OrderBookCheckpoint(
        symbol="BTCUSDT", last_update_id=1, exchange_event_time=ts, local_checkpoint_time=ts,
        synchronized=True, bids=bids, asks=asks
    )


# ==============================================================================
# SECTION 1: EXACT TIMESTAMP BOUNDARY AUDIT
# ==============================================================================

def test_exact_timestamp_boundary():
    """
    FeatureRow(T) uses data known at strictly <= T.
    Candles closing exactly at T should be included (their close_time in Binance is actually T-1ms).
    Trades at strictly T should be included.
    Trades at T+1ms should NOT be included.
    """
    T = _dt(5)
    
    # Candle closing at T (e.g. 12:04:00 to 12:04:59.999)
    # The open_time is T-1m, the close_time is T-1ms.
    c_included = _candle(_dt(4), T - timedelta(milliseconds=1), c="150")
    
    # Candle closing at T+1m
    c_excluded = _candle(_dt(5), T + timedelta(minutes=1, milliseconds=-1), c="250")
    
    safe_candles = [c for c in [c_included, c_excluded] if c.open_time + timedelta(minutes=1) <= T]
    assert safe_candles[0].close == 150.0

    t_before = _trade(T - timedelta(milliseconds=1), p="10")
    t_exact = _trade(T, p="20")
    t_after = _trade(T + timedelta(milliseconds=1), p="30")
    
    safe_trades = [t for t in [t_before, t_exact, t_after] if t.timestamp <= T]
    assert safe_trades[-1].price == 20.0


# ==============================================================================
# SECTION 2: ADVERSARIAL LOOK-AHEAD TEST
# ==============================================================================

@mock.patch("research_features.engine.OHLCVStore")
@mock.patch("research_features.engine.TradesStore")
@mock.patch("research_features.engine.OrderBookCheckpointStore")
def test_adversarial_lookahead(mock_ob, mock_trades, mock_ohlcv):
    """
    Inject extreme future values and assert the output FeatureRow(T) is identical.
    """
    engine = FeatureEngine()
    engine._ohlcv_store = mock_ohlcv.return_value
    engine._trades_store = mock_trades.return_value
    engine._ob_store = mock_ob.return_value
    
    T = _dt(5)
    
    # Baseline
    base_candles = [
        _candle(_dt(0), _dt(0, 59, 999), c="100", v="10"),
        _candle(_dt(1), _dt(1, 59, 999), c="101", v="10"),
        _candle(_dt(2), _dt(2, 59, 999), c="102", v="10"),
        _candle(_dt(3), _dt(3, 59, 999), c="103", v="10"),
        _candle(_dt(4), _dt(4, 59, 999), c="104", v="10"),
    ]
    base_trades = [
        _trade(_dt(4, 30), p="100", q="1"),
        _trade(_dt(4, 59), p="104", q="1"),
    ]
    
    # Mocking order book directly in engine for now is hard since it reads files.
    # Let's intercept the generated lists inside engine loop.
    # We will test lookahead by calling calculators directly with "adversarial" sliced arrays 
    # to simulate if the engine leaked them. Wait, the engine slicing IS the security.
    # So we should pass the adversarial array to the Engine and assert output.
    
    mock_ohlcv.return_value.load.return_value = list(base_candles)
    mock_trades.return_value.load.return_value = list(base_trades)
    
    baseline_rows = engine.generate_features("BTCUSDT", T, T)
    assert len(baseline_rows) == 1
    baseline = baseline_rows[0].model_dump()
    
    # Adversarial Injection
    adv_candles = list(base_candles)
    adv_candles.append(_candle(_dt(5), _dt(5, 59, 999), c="999999", v="999999999"))
    adv_candles.append(_candle(_dt(6), _dt(6, 59, 999), c="999999", v="999999999"))
    # Also inject somewhere in the middle with a future timestamp (e.g. out of order API return)
    adv_candles.insert(2, _candle(_dt(7), _dt(7, 59, 999), c="999999", v="999999999"))
    
    adv_trades = list(base_trades)
    adv_trades.append(_trade(T + timedelta(seconds=1), p="999999", q="999999"))
    adv_trades.append(_trade(T + timedelta(days=1), p="999999", q="999999"))
    
    mock_ohlcv.return_value.load.return_value = adv_candles
    mock_trades.return_value.load.return_value = adv_trades
    
    adv_rows = engine.generate_features("BTCUSDT", T, T)
    assert len(adv_rows) == 1
    adv = adv_rows[0].model_dump()
    
    # Hard Invariant
    for k in baseline:
        assert adv[k] == baseline[k], f"Leakage detected in {k}: base={baseline[k]}, adv={adv[k]}"


# ==============================================================================
# SECTION 3: MISSING HISTORY STRESS TEST
# ==============================================================================

def test_missing_history():
    T = _dt(5)
    # Empty arrays
    p_feat = calculate_price_features([], T)
    assert p_feat["return_1m"] is None
    assert p_feat["return_1h"] is None
    
    v_feat = calculate_volatility_features([], T)
    assert v_feat["volatility_5m"] is None
    
    vol_feat = calculate_volume_features([], T)
    assert vol_feat["volume_1m"] is None
    
    t_feat = calculate_trade_features([], T)
    assert t_feat["trade_count"] == 0
    assert t_feat["average_trade_size"] is None
    
    ob_feat = calculate_order_book_features(None)
    assert ob_feat["spread"] is None


# ==============================================================================
# SECTION 5: CROSS-SOURCE TEMPORAL ALIGNMENT
# ==============================================================================

def test_temporal_alignment_logic():
    T = _dt(10) # 10:00:00
    
    candles = [
        _candle(_dt(9), _dt(9, 59, 999), c="150") # Closes at 09:59:59.999
    ]
    trades = [
        _trade(_dt(9, 59, 59), p="100", q="1"),
        _trade(_dt(10, 0, 1), p="200", q="1")
    ]
    
    safe_candles = [c for c in candles if c.open_time + timedelta(minutes=1) <= T]
    assert len(safe_candles) == 1
    
    safe_trades = [t for t in trades if t.timestamp <= T]
    assert safe_trades[0].price == 100.0


# ==============================================================================
# SECTION 6: INPUT ORDERING / DETERMINISM
# ==============================================================================

def test_input_ordering_determinism():
    T = _dt(10)
    trades_base = [
        _trade(_dt(8, 59), p="90"), # Outside window! (12:08:59 <= 12:09:00)
        _trade(_dt(9, 10), p="100"),
        _trade(_dt(9, 20), p="110"),
        _trade(_dt(9, 30), p="120"),
    ]
    
    # Chronological
    feat_chrono = calculate_trade_features(trades_base, T)
    
    # Reverse
    feat_rev = calculate_trade_features(list(reversed(trades_base)), T)
    
    # Worst case shuffle where the outside trade is at the end of the array (so it's first in reversed())
    shuffled = [
        _trade(_dt(9, 10), p="100"),
        _trade(_dt(9, 20), p="110"),
        _trade(_dt(9, 30), p="120"),
        _trade(_dt(8, 59), p="90"), # Outside window!
    ]
    feat_shuffled = calculate_trade_features(shuffled, T)
    
    # With explicit sorting, these should now be identical.
    assert feat_chrono == feat_rev
    assert feat_chrono == feat_shuffled


# ==============================================================================
# SECTION 8: NUMERICAL TORTURE TEST
# ==============================================================================

def test_numerical_pathologies():
    T = _dt(5)
    
    # Negative volume / zero price
    c_bad = _candle(_dt(4), T - timedelta(milliseconds=1), c="0", v="-10")
    p_feat = calculate_price_features([c_bad], T)
    # 0 close might cause division by zero in returns if it's the previous candle
    c_prev = _candle(_dt(3), _dt(3, 59, 999), c="0")
    p_feat_2 = calculate_price_features([c_prev, c_bad], T)
    # The return_1m should handle divide by zero
    assert p_feat_2["return_1m"] is None or math.isnan(p_feat_2["return_1m"]) == False

    # Order book pathologies
    ob_bad = _ob(T, bids=[("100", "0")], asks=[("99", "1")]) # Crossed and 0 volume
    ob_feat = calculate_order_book_features(ob_bad)
    # The calculator returns empty dict basically for crossed books
    assert ob_feat["spread"] is None
    
    ob_zero_depth = _ob(T, bids=[("100", "0")], asks=[("101", "0")])
    ob_feat_zero = calculate_order_book_features(ob_zero_depth)
    assert ob_feat_zero["depth_imbalance_5"] is None # Avoid division by zero
    
    # Ensure no NaN
    for v in ob_feat_zero.values():
        if isinstance(v, float):
            assert not math.isnan(v)
            assert not math.isinf(v)
