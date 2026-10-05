"""
tests/test_statistics_engine.py
"""

import pytest
from datetime import datetime, timezone

from research.models import (
    EventOutcome,
    OutcomeDefinition,
    OutcomeStatus,
    OutcomeType,
)
from research.statistics_engine import StatisticsEngine, _calculate_quantile

def test_quantile_linear_interpolation():
    data = [10.0, 20.0, 30.0, 40.0]
    # N = 4. idx = 3 * p
    assert _calculate_quantile(data, 0.0) == 10.0
    assert _calculate_quantile(data, 1.0) == 40.0
    # p = 0.5 -> idx = 1.5 -> lower=1, upper=2, frac=0.5 -> 20*0.5 + 30*0.5 = 25.0
    assert _calculate_quantile(data, 0.5) == 25.0
    # p = 0.25 -> idx = 0.75 -> lower=0, upper=1, frac=0.75 -> 10*0.25 + 20*0.75 = 17.5
    assert _calculate_quantile(data, 0.25) == 17.5
    
    assert _calculate_quantile([], 0.5) is None
    assert _calculate_quantile([5.0], 0.5) == 5.0

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

def test_hand_calculated_fixture():
    # Fixture: -0.02, -0.01, 0.00, 0.01, 0.03
    outcomes = [
        _make_outcome(-0.02),
        _make_outcome(0.01),
        _make_outcome(0.00),
        _make_outcome(-0.01),
        _make_outcome(0.03),
    ]
    od = OutcomeDefinition(name="ret_1m", horizon_minutes=1, outcome_type=OutcomeType.RETURN_LIKE)
    
    eng = StatisticsEngine()
    res = eng.compute(outcomes, [od], ["overall"])[0]
    
    assert res.sample.N == 5
    assert res.descriptive.mean == pytest.approx(0.002, abs=1e-9)
    assert res.descriptive.median == pytest.approx(0.00, abs=1e-9)
    assert res.descriptive.min == pytest.approx(-0.02, abs=1e-9)
    assert res.descriptive.max == pytest.approx(0.03, abs=1e-9)
    
    # Win rate: > 0 (2 positive, 5 total -> 0.4)
    assert res.returns.win_rate == 0.4
    assert res.returns.positive_count == 2
    assert res.returns.negative_count == 2
    assert res.returns.zero_count == 1
    
    assert res.returns.largest_loss == -0.02
    assert res.returns.largest_gain == 0.03

def test_sample_size_0():
    eng = StatisticsEngine()
    od = OutcomeDefinition(name="ret_1m", horizon_minutes=1)
    res = eng.compute([], [od], ["overall"])
    assert len(res) == 0  # no populations at all

def test_sample_size_all_invalid():
    outcomes = [
        _make_outcome(None, OutcomeStatus.MISSING_PRICE),
        _make_outcome(None, OutcomeStatus.INSUFFICIENT_FUTURE_DATA),
    ]
    od = OutcomeDefinition(name="ret_1m", horizon_minutes=1)
    eng = StatisticsEngine()
    res = eng.compute(outcomes, [od], ["overall"])[0]
    
    assert res.sample.N == 0
    assert res.sample.event_count == 2
    assert res.descriptive.mean is None
    assert res.descriptive.median is None
    assert res.descriptive.std is None
    assert res.returns.win_rate is None

def test_sample_size_1():
    outcomes = [_make_outcome(0.05)]
    od = OutcomeDefinition(name="ret_1m", horizon_minutes=1)
    eng = StatisticsEngine()
    res = eng.compute(outcomes, [od], ["overall"])[0]
    
    assert res.sample.N == 1
    assert res.descriptive.mean == 0.05
    assert res.descriptive.std is None
    assert res.quantiles.p50 == 0.05
    assert res.returns.win_rate == 1.0

def test_sample_size_2():
    outcomes = [_make_outcome(0.01), _make_outcome(0.03)]
    od = OutcomeDefinition(name="ret_1m", horizon_minutes=1)
    eng = StatisticsEngine()
    res = eng.compute(outcomes, [od], ["overall"])[0]
    
    assert res.sample.N == 2
    assert res.descriptive.mean == 0.02
    # std of [0.01, 0.03] is sqrt( ((0.01-0.02)^2 + (0.03-0.02)^2) / 1 ) = sqrt( 0.0001 + 0.0001 ) = sqrt(0.0002) = 0.0141421...
    assert res.descriptive.std == pytest.approx(0.0141421356)
