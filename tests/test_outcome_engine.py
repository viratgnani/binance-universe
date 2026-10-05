"""
tests/test_outcome_engine.py

Tests for OutcomeEngine — forward outcome calculation.

Hand-calculated fixture:
  Prices:
    10:00 = 100.0
    10:01 = 101.0
    10:02 = 98.0
    10:03 = 102.0
    10:04 = 99.0

  Event at 10:01 (price=101)
  1m outcome  = 98  / 101 - 1  ≈ -0.02970
  3m outcome  = 102 / 101 - 1  ≈  0.00990
  5m outcome  = insufficient_future_data (data ends at 10:04, target = 10:06)
"""

import pytest
from datetime import datetime, timedelta, timezone

from research.event_engine import EventEngine
from research.models import (
    CrossingDirection,
    Event,
    EventDefinition,
    EventMode,
    Operator,
    OutcomeDefinition,
    OutcomeStatus,
    ThresholdCondition,
)
from research.outcome_engine import OutcomeEngine

RID = "test_run"
SYM = "BTCUSDT"

def _utc(h: int, m: int = 0) -> datetime:
    return datetime(2026, 8, 31, h, m, tzinfo=timezone.utc)


PRICE_SERIES = [
    (_utc(10, 0), 100.0),
    (_utc(10, 1), 101.0),
    (_utc(10, 2), 98.0),
    (_utc(10, 3), 102.0),
    (_utc(10, 4), 99.0),
]


def _event(ts, val=101.0) -> Event:
    return Event(
        research_id=RID, symbol=SYM,
        timestamp=ts, event_definition_hash="abc",
        feature_name="return_1m", feature_value=val,
        direction=None,
    )


def _od(name: str, minutes: int) -> OutcomeDefinition:
    return OutcomeDefinition(name=name, horizon_minutes=minutes, price_feature="mid_price")


engine = OutcomeEngine()


# ---------------------------------------------------------------------------
# SECTION 1: Hand-calculated exact returns
# ---------------------------------------------------------------------------

class TestForwardReturnMath:
    def test_1m_return(self):
        """Event at 10:01 (price=101), 1m target 10:02 (price=98)"""
        outcomes = engine.calculate_outcomes(
            [_event(_utc(10, 1), val=101.0)],
            [_od("fwd_1m", 1)],
            PRICE_SERIES,
        )
        assert len(outcomes) == 1
        o = outcomes[0]
        assert o.status == OutcomeStatus.VALID
        assert o.outcome_value == pytest.approx(98.0 / 101.0 - 1.0, abs=1e-9)
        assert o.outcome_timestamp == _utc(10, 2)

    def test_3m_return(self):
        """Event at 10:01 (price=101), 3m target 10:04 (price=99)"""
        outcomes = engine.calculate_outcomes(
            [_event(_utc(10, 1))],
            [_od("fwd_3m", 3)],
            PRICE_SERIES,
        )
        o = outcomes[0]
        assert o.status == OutcomeStatus.VALID
        assert o.outcome_value == pytest.approx(99.0 / 101.0 - 1.0, abs=1e-9)

    def test_5m_insufficient(self):
        """Event at 10:01, 5m target 10:06 — beyond last obs at 10:04"""
        outcomes = engine.calculate_outcomes(
            [_event(_utc(10, 1))],
            [_od("fwd_5m", 5)],
            PRICE_SERIES,
        )
        o = outcomes[0]
        assert o.status == OutcomeStatus.INSUFFICIENT_FUTURE_DATA
        assert o.outcome_value is None

    def test_exact_horizon_match_only(self):
        """No obs exactly at T+2, but T+3 exists — must be missing_price not nearest"""
        # Remove 10:03 from the series (no exact 2m match for event at 10:01)
        partial = [p for p in PRICE_SERIES if p[0] != _utc(10, 3)]
        outcomes = engine.calculate_outcomes(
            [_event(_utc(10, 1))],
            [_od("fwd_2m", 2)],  # target: 10:03, which we removed
            partial,
        )
        # 10:03 is removed → not at end of data, but missing → missing_price
        o = outcomes[0]
        assert o.status == OutcomeStatus.MISSING_PRICE
        assert o.outcome_value is None

    def test_missing_price_at_event_time(self):
        """Price at event timestamp is None → missing_price"""
        price_series = [(_utc(10, 1), None), (_utc(10, 2), 101.0)]
        outcomes = engine.calculate_outcomes(
            [_event(_utc(10, 1))],
            [_od("fwd_1m", 1)],
            price_series,
        )
        assert outcomes[0].status == OutcomeStatus.MISSING_PRICE

    def test_zero_price_at_event_time_rejected(self):
        """Zero price at T → missing_price"""
        price_series = [(_utc(10, 1), 0.0), (_utc(10, 2), 101.0)]
        outcomes = engine.calculate_outcomes(
            [_event(_utc(10, 1))],
            [_od("fwd_1m", 1)],
            price_series,
        )
        assert outcomes[0].status == OutcomeStatus.MISSING_PRICE

    def test_negative_price_at_event_time_rejected(self):
        price_series = [(_utc(10, 1), -1.0), (_utc(10, 2), 101.0)]
        outcomes = engine.calculate_outcomes(
            [_event(_utc(10, 1))],
            [_od("fwd_1m", 1)],
            price_series,
        )
        assert outcomes[0].status == OutcomeStatus.MISSING_PRICE


# ---------------------------------------------------------------------------
# SECTION 2: Multiple events and horizons
# ---------------------------------------------------------------------------

class TestMultipleEventsAndHorizons:
    def test_multiple_events_all_get_outcomes(self):
        events = [_event(_utc(10, 0), 100.0), _event(_utc(10, 1), 101.0)]
        ods = [_od("fwd_1m", 1), _od("fwd_2m", 2)]
        outcomes = engine.calculate_outcomes(events, ods, PRICE_SERIES)
        assert len(outcomes) == 4  # 2 events × 2 horizons

    def test_overlapping_events_preserved(self):
        """Events can overlap — no hidden deduplication"""
        e1 = _event(_utc(10, 0), 100.0)
        e2 = _event(_utc(10, 1), 101.0)
        outcomes = engine.calculate_outcomes([e1, e2], [_od("fwd_1m", 1)], PRICE_SERIES)
        assert len(outcomes) == 2

    def test_empty_events_returns_empty(self):
        outcomes = engine.calculate_outcomes([], [_od("fwd_1m", 1)], PRICE_SERIES)
        assert outcomes == []

    def test_empty_price_series(self):
        outcomes = engine.calculate_outcomes([_event(_utc(10, 1))], [_od("fwd_1m", 1)], [])
        assert outcomes[0].status == OutcomeStatus.MISSING_PRICE


# ---------------------------------------------------------------------------
# SECTION 3: Determinism
# ---------------------------------------------------------------------------

class TestOutcomeDeterminism:
    def test_shuffled_price_series_same_result(self):
        import random
        events = [_event(_utc(10, 1))]
        ods    = [_od("fwd_1m", 1), _od("fwd_3m", 3)]

        expected = engine.calculate_outcomes(events, ods, PRICE_SERIES)

        for _ in range(5):
            shuffled = list(PRICE_SERIES)
            random.shuffle(shuffled)
            result = engine.calculate_outcomes(events, ods, shuffled)
            assert [o.status for o in result] == [o.status for o in expected]
            assert [o.outcome_value for o in result] == [o.outcome_value for o in expected]

    def test_outcome_metadata_correct(self):
        outcomes = engine.calculate_outcomes(
            [_event(_utc(10, 1))], [_od("fwd_1m", 1)], PRICE_SERIES
        )
        o = outcomes[0]
        assert o.research_id == RID
        assert o.symbol == SYM
        assert o.event_timestamp == _utc(10, 1)
        assert o.outcome_name == "fwd_1m"
        assert o.horizon_minutes == 1
        assert o.event_definition_hash == "abc"
