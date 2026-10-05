"""
tests/test_discovery_event_definitions.py
"""

from research.models import Operator, EventMode, CrossingDirection
from research_discovery.event_definitions import (
    price_move_up,
    volume_shock,
    breakout,
    extreme_candle_up
)

def test_price_move_up():
    ev = price_move_up(0.05, feature="return_10m")
    assert ev.condition.feature_name == "return_10m"
    assert ev.condition.operator == Operator.GT
    assert ev.condition.threshold == 0.05
    assert ev.event_mode == EventMode.CONDITION

def test_volume_shock():
    ev = volume_shock(3.5)
    assert ev.condition.feature_name == "relative_volume_vs_1h"
    assert ev.condition.operator == Operator.GT
    assert ev.condition.threshold == 3.5
    assert ev.event_mode == EventMode.CROSSING
    assert ev.crossing_direction == CrossingDirection.CROSS_UP

def test_breakout():
    ev = breakout()
    assert ev.condition.feature_name == "distance_from_high_24h"
    assert ev.condition.operator == Operator.GT
    assert ev.condition.threshold == 0.0
    assert ev.event_mode == EventMode.CROSSING

def test_extreme_candle_up():
    ev = extreme_candle_up(0.02)
    assert ev.condition.feature_name == "return_1m"
    assert ev.condition.operator == Operator.GT
    assert ev.condition.threshold == 0.02
    assert ev.event_mode == EventMode.CONDITION
