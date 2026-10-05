"""
tests/test_statistics_adversarial.py
"""

import math
import random
import pytest
from datetime import datetime, timezone

from research.models import (
    EventOutcome,
    OutcomeDefinition,
    OutcomeStatus,
    OutcomeType,
)
from research.statistics_engine import StatisticsEngine

def _make_outcome(val: float | None, status: OutcomeStatus = OutcomeStatus.VALID) -> EventOutcome:
    return EventOutcome(
        research_id="rid",
        symbol="BTC",
        event_timestamp=datetime(2026, 1, 1, tzinfo=timezone.utc),
        event_definition_hash="x",
        outcome_name="ret_1m",
        horizon_minutes=1,
        outcome_value=val,
        status=status,
    )

def test_input_ordering_determinism():
    base_vals = [0.01, -0.05, 0.03, 0.00, 0.10, -0.02]
    outcomes = [_make_outcome(v) for v in base_vals]
    
    eng = StatisticsEngine()
    od = OutcomeDefinition(name="ret_1m", horizon_minutes=1)
    
    res_base = eng.compute(outcomes, [od], ["overall"])[0]
    
    for _ in range(5):
        shuffled = list(outcomes)
        random.shuffle(shuffled)
        res_shuff = eng.compute(shuffled, [od], ["overall"])[0]
        
        assert res_base.descriptive.mean == res_shuff.descriptive.mean
        assert res_base.descriptive.median == res_shuff.descriptive.median
        assert res_base.descriptive.std == res_shuff.descriptive.std
        assert res_base.quantiles.p90 == res_shuff.quantiles.p90

def test_duplicate_observations():
    # If the same observation is duplicated, it counts twice.
    o = _make_outcome(0.01)
    outcomes = [o, o]
    
    eng = StatisticsEngine()
    od = OutcomeDefinition(name="ret_1m", horizon_minutes=1)
    res = eng.compute(outcomes, [od], ["overall"])[0]
    
    assert res.sample.N == 2
    assert res.descriptive.mean == 0.01
    assert res.descriptive.std == 0.0

def test_missing_outcomes_not_in_n():
    outcomes = [
        _make_outcome(0.01),
        _make_outcome(None, OutcomeStatus.MISSING_PRICE),
        _make_outcome(0.03),
    ]
    eng = StatisticsEngine()
    od = OutcomeDefinition(name="ret_1m", horizon_minutes=1)
    res = eng.compute(outcomes, [od], ["overall"])[0]
    
    assert res.sample.event_count == 3
    assert res.sample.N == 2
    assert res.descriptive.mean == 0.02
    assert res.sample.missing_outcome_count == 1

def test_invalid_numerical_values():
    outcomes = [
        _make_outcome(0.01),
        _make_outcome(float('nan')),
        _make_outcome(float('inf')),
        _make_outcome(float('-inf')),
    ]
    eng = StatisticsEngine()
    od = OutcomeDefinition(name="ret_1m", horizon_minutes=1)
    res = eng.compute(outcomes, [od], ["overall"])[0]
    
    assert res.sample.event_count == 4
    assert res.sample.N == 1
    assert res.sample.invalid_outcome_count == 3
    assert res.descriptive.mean == 0.01

def test_very_large_and_small_numbers():
    outcomes = [
        _make_outcome(1e12),
        _make_outcome(-1e12),
        _make_outcome(1e-12),
        _make_outcome(-1e-12),
    ]
    eng = StatisticsEngine()
    od = OutcomeDefinition(name="ret_1m", horizon_minutes=1)
    res = eng.compute(outcomes, [od], ["overall"])[0]
    
    assert res.sample.N == 4
    # Mean of 1e12 and -1e12 is 0. 1e-12 and -1e-12 is 0.
    assert res.descriptive.mean == pytest.approx(0.0, abs=1e-9)
    assert res.returns.largest_gain == 1e12
    assert res.returns.largest_loss == -1e12
