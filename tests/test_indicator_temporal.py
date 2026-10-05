"""
tests/test_indicator_temporal.py
"""

from datetime import datetime, timezone, timedelta
import math
from indicators.models import IndicatorDefinition
from indicators.rsi import RsiCalculator

def _t(minutes: int) -> datetime:
    return datetime(2026, 1, 1, tzinfo=timezone.utc) + timedelta(minutes=minutes)

def test_temporal_lookahead_adversarial():
    # Base calculation
    calc = RsiCalculator()
    defi = IndicatorDefinition(indicator_name="rsi", parameters={"period": 2})
    
    # Needs 3 points for first valid RSI (period=2)
    base_series = [
        (_t(1), 10.0),
        (_t(2), 12.0),
        (_t(3), 11.0),
    ]
    
    base_res = calc.calculate("BTC", base_series, defi)
    base_val = base_res.values[2].value
    assert base_val is not None
    
    # Inject future data
    future_injections = [
        (_t(3) + timedelta(seconds=1), 1000000.0),
        (_t(4), 1000000.0),
        (_t(10), -500.0),
        (_t(60), math.inf),
    ]
    for f_ts, f_val in future_injections:
        adv_series = base_series + [(f_ts, f_val)]
        adv_res = calc.calculate("BTC", adv_series, defi)
        
        # The value at T=3 must be identical
        # First, find the output value for T=3 in the adversarial result
        t3_val = None
        for v in adv_res.values:
            if v.timestamp == _t(3):
                t3_val = v.value
                break
        
        assert t3_val == base_val, f"Temporal violation with injection at {f_ts}"
