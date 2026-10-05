"""
tests/test_rsi.py
"""

import math
import pytest
from datetime import datetime, timezone, timedelta
from indicators.models import IndicatorDefinition
from indicators.rsi import RsiCalculator

def _t(minutes: int) -> datetime:
    return datetime(2026, 1, 1, tzinfo=timezone.utc) + timedelta(minutes=minutes)

def test_rsi_initialization_window():
    # Period 3 requires 4 valid prices (3 changes) to emit first RSI
    calc = RsiCalculator()
    defi = IndicatorDefinition(indicator_name="rsi", parameters={"period": 3})
    
    series = [
        (_t(1), 100.0),
        (_t(2), 101.0), # change 1: +1
        (_t(3), 102.0), # change 2: +1
        (_t(4), 103.0), # change 3: +1 -> first RSI here
    ]
    
    res = calc.calculate("BTC", series, defi)
    
    assert res.values[0].value is None
    assert res.values[1].value is None
    assert res.values[2].value is None
    assert res.values[3].value == 100.0  # all gains

def test_rsi_flat_series():
    calc = RsiCalculator()
    defi = IndicatorDefinition(indicator_name="rsi", parameters={"period": 3})
    series = [(_t(i), 100.0) for i in range(1, 10)]
    res = calc.calculate("BTC", series, defi)
    
    # After warm-up, should be exactly 50
    assert res.values[3].value == 50.0
    assert res.values[8].value == 50.0

def test_rsi_all_losses():
    calc = RsiCalculator()
    defi = IndicatorDefinition(indicator_name="rsi", parameters={"period": 3})
    series = [(_t(i), 100.0 - i) for i in range(1, 10)]
    res = calc.calculate("BTC", series, defi)
    
    # After warm-up, should be exactly 0
    assert res.values[3].value == 0.0

def test_rsi_invalid_prices_skipped():
    calc = RsiCalculator()
    defi = IndicatorDefinition(indicator_name="rsi", parameters={"period": 2})
    # Valid window requires 3 valid prices.
    series = [
        (_t(1), 10.0),
        (_t(2), None),
        (_t(3), math.nan),
        (_t(4), 12.0), # change 1: +2
        (_t(5), -5.0), # invalid
        (_t(6), 11.0), # change 2: -1 -> first RSI here
    ]
    res = calc.calculate("BTC", series, defi)
    
    for i in range(5):
        assert res.values[i].value is None
        
    # period=2. Initial changes: +2, -1.
    # avg_gain = 2/2 = 1.0. avg_loss = 1/2 = 0.5.
    # RS = 1.0 / 0.5 = 2.0. RSI = 100 - 100/3 = 66.666...
    assert res.values[5].value == pytest.approx(66.666666666666)

def _reference_rsi(prices: list[float], period: int) -> float | None:
    """Independent reference implementation of Wilder's RSI."""
    if len(prices) <= period:
        return None
    
    gains = []
    losses = []
    for i in range(1, len(prices)):
        change = prices[i] - prices[i-1]
        gains.append(max(change, 0.0))
        losses.append(max(-change, 0.0))
        
    avg_gain = sum(gains[:period]) / period
    avg_loss = sum(losses[:period]) / period
    
    for i in range(period, len(gains)):
        avg_gain = (avg_gain * (period - 1) + gains[i]) / period
        avg_loss = (avg_loss * (period - 1) + losses[i]) / period
        
    if avg_loss == 0 and avg_gain == 0: return 50.0
    if avg_loss == 0: return 100.0
    if avg_gain == 0: return 0.0
    return 100.0 - 100.0 / (1.0 + avg_gain/avg_loss)

def test_rsi_cross_check():
    calc = RsiCalculator()
    defi = IndicatorDefinition(indicator_name="rsi", parameters={"period": 5})
    
    prices = [10, 12, 11, 13, 15, 14, 18, 17, 20, 22, 21, 19]
    series = [(_t(i), p) for i, p in enumerate(prices)]
    
    res = calc.calculate("BTC", series, defi)
    
    for i in range(5, len(prices)):
        expected = _reference_rsi(prices[:i+1], 5)
        assert res.values[i].value == pytest.approx(expected)
