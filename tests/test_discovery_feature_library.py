"""
tests/test_discovery_feature_library.py
"""

from datetime import datetime, timedelta, timezone
import pytest

from market_data.models import Candle
from research_discovery.feature_library import DiscoveryFeatureCalculator


def make_candle(t: datetime, open_p: float, high: float, low: float, close: float, vol: float = 100.0) -> Candle:
    return Candle(
        symbol="TEST",
        interval="1m",
        open_time=t,
        close_time=t + timedelta(minutes=1) - timedelta(milliseconds=1),
        open=open_p,
        high=high,
        low=low,
        close=close,
        volume=vol,
        quote_volume=vol * close,
        trade_count=10,
        taker_buy_base_vol=vol/2,
        taker_buy_quote_vol=(vol/2)*close,
    )

def test_discovery_returns():
    calc = DiscoveryFeatureCalculator()
    t0 = datetime(2025, 1, 1, 0, 0, tzinfo=timezone.utc)
    
    # Push T0
    c0 = make_candle(t0, 100, 101, 99, 100)
    row0 = calc.process_candle(c0)
    assert row0.return_1m is None  # no history
    
    # Push T1
    t1 = t0 + timedelta(minutes=1)
    c1 = make_candle(t1, 100, 105, 99, 105)
    row1 = calc.process_candle(c1)
    assert row1.return_1m == pytest.approx(0.05)
    assert row1.absolute_return_1m == pytest.approx(0.05)
    
    # Gap in data, skip T2, T3, T4
    # Push T5
    t5 = t0 + timedelta(minutes=5)
    c5 = make_candle(t5, 105, 110, 100, 110)
    row5 = calc.process_candle(c5)
    
    assert row5.return_1m is None # missing T4
    assert row5.return_5m == pytest.approx(0.10) # compared to T0 (110/100 - 1)

def test_discovery_percentiles():
    calc = DiscoveryFeatureCalculator()
    t0 = datetime(2025, 1, 1, 0, 0, tzinfo=timezone.utc)
    
    # Push 100 identical candles to build volume history
    for i in range(100):
        t = t0 + timedelta(minutes=i)
        c = make_candle(t, 100, 100, 100, 100, vol=100.0)
        calc.process_candle(c)
        
    # Now trailing 60 history has 60 items of 100.0 volume
    # Push a shock
    t_shock = t0 + timedelta(minutes=100)
    c_shock = make_candle(t_shock, 100, 100, 100, 100, vol=500.0)
    row_shock = calc.process_candle(c_shock)
    
    assert row_shock.relative_volume_vs_1h == pytest.approx(5.0)
    # The shock is 500.0. The history has 59 items of 100.0 and 1 item of 500.0 (total 60).
    # count_below = 59, count_equal = 1. Percentile = (59 + 0.5) / 60 = 59.5 / 60 = 0.9916666666666667
    assert row_shock.volume_pct_rank_1h == pytest.approx(59.5 / 60.0)

def test_breakout_distance():
    calc = DiscoveryFeatureCalculator()
    t0 = datetime(2025, 1, 1, 0, 0, tzinfo=timezone.utc)
    
    # Push 1400 candles (almost 24h)
    for i in range(1400):
        t = t0 + timedelta(minutes=i)
        # High is 100 everywhere
        c = make_candle(t, 90, 100, 90, 95)
        calc.process_candle(c)
        
    # Push one more to cross 1380 threshold, with a breakout close
    t_break = t0 + timedelta(minutes=1400)
    c_break = make_candle(t_break, 90, 110, 90, 105) # close = 105, previous max high = 100
    row_break = calc.process_candle(c_break)
    
    assert row_break.distance_from_high_24h is not None
    # distance = close(T) / max(high(t < T)) - 1
    # distance = 105 / 100 - 1 = 0.05
    assert row_break.distance_from_high_24h == pytest.approx(0.05)
