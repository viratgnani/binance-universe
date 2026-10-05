"""
tests/test_indicator_adversarial.py
"""

import random
import pytest
from datetime import datetime, timezone, timedelta
from indicators.models import IndicatorDefinition
from indicators.rsi import RsiCalculator
from indicators.validators import TemporalValidationError

def _t(minutes: int) -> datetime:
    return datetime(2026, 1, 1, tzinfo=timezone.utc) + timedelta(minutes=minutes)

def test_input_ordering_determinism():
    calc = RsiCalculator()
    defi = IndicatorDefinition(indicator_name="rsi", parameters={"period": 3})
    
    # 5 observations -> first valid RSI at index 3
    base_series = [
        (_t(1), 10.0),
        (_t(2), 11.0),
        (_t(3), 10.5),
        (_t(4), 12.0),
        (_t(5), 11.8),
    ]
    
    base_res = calc.calculate("BTC", base_series, defi)
    
    for _ in range(5):
        shuffled = list(base_series)
        random.shuffle(shuffled)
        shuff_res = calc.calculate("BTC", shuffled, defi)
        
        # Result arrays must match exactly
        for i in range(len(base_res.values)):
            assert base_res.values[i].timestamp == shuff_res.values[i].timestamp
            assert base_res.values[i].value == shuff_res.values[i].value

def test_duplicate_timestamps_raise_error():
    calc = RsiCalculator()
    defi = IndicatorDefinition(indicator_name="rsi", parameters={"period": 3})
    
    series = [
        (_t(1), 10.0),
        (_t(1), 11.0), # Duplicate
    ]
    
    with pytest.raises(TemporalValidationError):
        calc.calculate("BTC", series, defi)

def test_middle_insertion_sorting():
    calc = RsiCalculator()
    defi = IndicatorDefinition(indicator_name="rsi", parameters={"period": 2})
    
    # We provide the series out of order: T=1, T=3, T=2
    series = [
        (_t(1), 10.0),
        (_t(3), 12.0),
        (_t(2), 11.0),
    ]
    
    res = calc.calculate("BTC", series, defi)
    
    # Engine must sort to T=1, T=2, T=3.
    # Changes: +1, +1. avg_gain = 1.0, avg_loss = 0.0 -> RSI = 100.
    assert res.values[0].timestamp == _t(1)
    assert res.values[1].timestamp == _t(2)
    assert res.values[2].timestamp == _t(3)
    assert res.values[2].value == 100.0
