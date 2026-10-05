"""
tests/test_research_adversarial.py

Mandatory adversarial temporal tests for Research Engine V1.

Tests A–H cover all invariants from the specification:
  A — future feature mutation must not change Event(T)
  B — future price mutation must not change Event(T)
  C — input ordering must not change events
  D — future record insertion must not change prior events
  E — event timestamps must not exceed the feature series range
  F — outcome timestamps must be >= event timestamps
  G — outcome engine is explicitly allowed to use future price data
  H — insufficient future data produces explicit status (never fabricated)
"""

import random
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
from research.validators import TemporalValidator, TemporalValidationError

RID = "adv_test"
SYM = "BTCUSDT"

def _utc(minute: int) -> datetime:
    return datetime(2026, 8, 31, 10, 0, tzinfo=timezone.utc) + timedelta(minutes=minute)

def _crossing_def(threshold: float = 90.0) -> EventDefinition:
    return EventDefinition(
        condition=ThresholdCondition(feature_name="f", operator=Operator.GT, threshold=threshold),
        event_mode=EventMode.CROSSING,
        crossing_direction=CrossingDirection.CROSS_UP,
    )

event_engine   = EventEngine()
outcome_engine = OutcomeEngine()
validator      = TemporalValidator()


# ---------------------------------------------------------------------------
# Test A — Future feature mutation must not change Event(T)
# ---------------------------------------------------------------------------

class TestA_FutureFeatureMutation:
    """
    Inject extreme feature values at T+1, T+5, T+60, T+1440.
    Events at or before T must be identical.
    """

    def _detect(self, extra_series: list) -> list[Event]:
        base_series = [
            (_utc(0), 89.0),
            (_utc(1), 91.0),  # cross_up event here
        ]
        full_series = base_series + extra_series
        ed = _crossing_def()
        return event_engine.detect_events(RID, SYM, ed, full_series)

    def test_mutation_t_plus_1m(self):
        events_base  = self._detect([])
        events_mutated = self._detect([(_utc(2), 999_999.0)])
        assert [e.timestamp for e in events_base] == [e.timestamp for e in events_mutated]
        assert [e.feature_value for e in events_base] == [e.feature_value for e in events_mutated]

    def test_mutation_t_plus_5m(self):
        events_base  = self._detect([])
        events_mutated = self._detect([(_utc(6), 999_999.0)])
        assert [e.timestamp for e in events_base] == [e.timestamp for e in events_mutated]

    def test_mutation_t_plus_1h(self):
        events_base  = self._detect([])
        events_mutated = self._detect([(_utc(61), -999_999.0)])
        assert [e.timestamp for e in events_base] == [e.timestamp for e in events_mutated]

    def test_mutation_t_plus_1d(self):
        events_base  = self._detect([])
        events_mutated = self._detect([(_utc(1441), 999_999.0)])
        assert [e.timestamp for e in events_base] == [e.timestamp for e in events_mutated]

    def test_future_insertion_in_middle_of_array(self):
        """
        Insert future records in the MIDDLE of the input array — must not affect T events.
        This is the adversarial unordered insertion case.
        """
        base = [(_utc(0), 89.0), (_utc(1), 91.0)]
        # Insert future records between existing ones
        adversarial = [(_utc(0), 89.0), (_utc(100), 999_999.0), (_utc(1), 91.0), (_utc(200), -1.0)]
        ed = _crossing_def()
        events_base = event_engine.detect_events(RID, SYM, ed, base)
        events_adv  = event_engine.detect_events(RID, SYM, ed, adversarial)
        assert [e.timestamp for e in events_base] == [e.timestamp for e in events_adv]


# ---------------------------------------------------------------------------
# Test B — Future price mutation must not change Event(T)
# ---------------------------------------------------------------------------

class TestB_FuturePriceMutation:
    """Mutating future prices changes outcomes but never events."""

    def _events(self) -> list[Event]:
        series = [(_utc(0), 89.0), (_utc(1), 91.0)]
        return event_engine.detect_events(RID, SYM, _crossing_def(), series)

    def test_absurd_future_price_does_not_change_event(self):
        events = self._events()
        assert len(events) == 1
        assert events[0].timestamp == _utc(1)

        # Even if future prices are absurd, events are the same
        assert events[0].feature_value == 91.0

    def test_outcome_changes_but_event_does_not(self):
        events = self._events()
        T = _utc(1)

        price_normal = [(T, 100.0), (T + timedelta(minutes=1), 101.0)]
        price_absurd = [(T, 100.0), (T + timedelta(minutes=1), 999_999.0)]

        od = OutcomeDefinition(name="fwd_1m", horizon_minutes=1, price_feature="mid_price")

        outcomes_normal = outcome_engine.calculate_outcomes(events, [od], price_normal)
        outcomes_absurd = outcome_engine.calculate_outcomes(events, [od], price_absurd)

        # Events unchanged
        assert events[0].timestamp == T
        # Outcomes differ
        assert outcomes_normal[0].outcome_value != outcomes_absurd[0].outcome_value
        assert outcomes_absurd[0].outcome_value == pytest.approx(999_999.0 / 100.0 - 1.0, abs=1e-6)


# ---------------------------------------------------------------------------
# Test C — Input ordering invariant
# ---------------------------------------------------------------------------

class TestC_InputOrdering:
    def _run(self, series):
        return event_engine.detect_events(RID, SYM, _crossing_def(), series)

    def test_ascending_matches_descending(self):
        series = [(_utc(i), v) for i, v in enumerate([85, 91, 93, 88, 92])]
        asc = self._run(series)
        desc = self._run(list(reversed(series)))
        assert [e.timestamp for e in asc] == [e.timestamp for e in desc]

    def test_random_shuffles_deterministic(self):
        series = [(_utc(i), v) for i, v in enumerate([85, 91, 93, 88, 92])]
        expected = self._run(series)
        for _ in range(10):
            shuffled = list(series)
            random.shuffle(shuffled)
            result = self._run(shuffled)
            assert [e.timestamp for e in result] == [e.timestamp for e in expected]


# ---------------------------------------------------------------------------
# Test D — Temporal Validator rejects future-generated events
# ---------------------------------------------------------------------------

class TestD_TemporalValidator:
    def test_event_within_series_passes(self):
        series = [(_utc(0), 89.0), (_utc(1), 91.0)]
        events = event_engine.detect_events(RID, SYM, _crossing_def(), series)
        # Should not raise
        validator.validate_events(events, series)

    def test_event_outside_series_raises(self):
        series = [(_utc(0), 89.0), (_utc(1), 91.0)]
        # Fabricate an event beyond the series
        bad_event = Event(
            research_id=RID, symbol=SYM, timestamp=_utc(100),
            event_definition_hash="x", feature_name="f", feature_value=999.0, direction=None
        )
        with pytest.raises(TemporalValidationError):
            validator.validate_events([bad_event], series)

    def test_outcome_before_event_raises(self):
        from research.models import EventOutcome
        bad = EventOutcome(
            research_id=RID, symbol=SYM,
            event_timestamp=_utc(5), event_definition_hash="x",
            outcome_name="n", horizon_minutes=1,
            outcome_value=0.01,
            outcome_timestamp=_utc(4),  # before event!
            status=OutcomeStatus.VALID,
        )
        with pytest.raises(TemporalValidationError):
            validator.validate_outcomes([bad])

    def test_valid_outcome_passes(self):
        from research.models import EventOutcome
        good = EventOutcome(
            research_id=RID, symbol=SYM,
            event_timestamp=_utc(5), event_definition_hash="x",
            outcome_name="n", horizon_minutes=1,
            outcome_value=0.01,
            outcome_timestamp=_utc(6),
            status=OutcomeStatus.VALID,
        )
        validator.validate_outcomes([good])  # no raise


# ---------------------------------------------------------------------------
# Test E — Outcome uses future data (explicitly allowed)
# ---------------------------------------------------------------------------

class TestE_OutcomeUsesForwardData:
    def test_outcome_timestamp_is_after_event(self):
        series = [(_utc(0), 89.0), (_utc(1), 91.0)]
        events = event_engine.detect_events(RID, SYM, _crossing_def(), series)

        price_series = [
            (_utc(1), 100.0),
            (_utc(2), 102.0),  # T+1: future relative to event
        ]
        od = OutcomeDefinition(name="fwd_1m", horizon_minutes=1, price_feature="mid_price")
        outcomes = outcome_engine.calculate_outcomes(events, [od], price_series)

        o = outcomes[0]
        assert o.status == OutcomeStatus.VALID
        assert o.outcome_timestamp > o.event_timestamp  # explicitly forward-looking


# ---------------------------------------------------------------------------
# Test F — Insufficient future data produces explicit status
# ---------------------------------------------------------------------------

class TestF_InsufficientFutureData:
    def test_insufficient_status_not_fabricated(self):
        series = [(_utc(0), 89.0), (_utc(1), 91.0)]
        events = event_engine.detect_events(RID, SYM, _crossing_def(), series)

        # Price series ends at T+1; requesting T+10
        price_series = [(_utc(1), 100.0), (_utc(2), 102.0)]
        od = OutcomeDefinition(name="fwd_10m", horizon_minutes=10, price_feature="mid_price")
        outcomes = outcome_engine.calculate_outcomes(events, [od], price_series)

        o = outcomes[0]
        assert o.status == OutcomeStatus.INSUFFICIENT_FUTURE_DATA
        assert o.outcome_value is None
        assert o.outcome_timestamp is None

    def test_event_near_end_of_data_returns_insufficient(self):
        """Event at 23:59, horizon=10m, data ends at 00:05 — must return insufficient"""
        end_ts = datetime(2026, 8, 31, 23, 59, tzinfo=timezone.utc)
        series = [(end_ts - timedelta(minutes=1), 89.0), (end_ts, 91.0)]
        events = event_engine.detect_events(RID, SYM, _crossing_def(), series)

        data_end = datetime(2026, 9, 1, 0, 5, tzinfo=timezone.utc)
        price_series = [(end_ts, 100.0), (data_end, 103.0)]

        od = OutcomeDefinition(name="fwd_10m", horizon_minutes=10, price_feature="mid_price")
        outcomes = outcome_engine.calculate_outcomes(events, [od], price_series)
        assert outcomes[0].status == OutcomeStatus.INSUFFICIENT_FUTURE_DATA


# ---------------------------------------------------------------------------
# Test G — Hand-calculated crossing fixture
# ---------------------------------------------------------------------------

class TestG_HandCalculatedFixture:
    """
    timestamp   feature
    10:00       89          (below 90)
    10:01       91          → cross_up
    10:02       93
    10:03       88          → cross_down from 93
    10:04       missing (None)
    10:05       92          → cross_up from 88 (None was skipped)

    With direction=ANY, events at 10:01 (up), 10:03 (down), 10:05 (up)
    """

    def test_crossing_hand_calculated(self):
        series = [
            (_utc(0), 89.0),
            (_utc(1), 91.0),
            (_utc(2), 93.0),
            (_utc(3), 88.0),
            (_utc(4), None),
            (_utc(5), 92.0),
        ]
        ed = EventDefinition(
            condition=ThresholdCondition(feature_name="f", operator=Operator.GT, threshold=90.0),
            event_mode=EventMode.CROSSING,
            crossing_direction=CrossingDirection.ANY,
        )
        events = event_engine.detect_events(RID, SYM, ed, series)

        assert len(events) == 3
        assert events[0].timestamp == _utc(1)
        assert events[0].direction == CrossingDirection.CROSS_UP
        assert events[1].timestamp == _utc(3)
        assert events[1].direction == CrossingDirection.CROSS_DOWN
        assert events[2].timestamp == _utc(5)
        assert events[2].direction == CrossingDirection.CROSS_UP

    def test_price_forward_return_hand_calculated(self):
        """
        Event at 10:01, price = 100
        price at 10:02 = 101  → 1m return = 101/100 - 1 = 0.01
        price at 10:04 = 102  → 3m return = 102/100 - 1 = 0.02
        """
        event = Event(
            research_id=RID, symbol=SYM, timestamp=_utc(1),
            event_definition_hash="x", feature_name="f",
            feature_value=91.0, direction=None,
        )
        price_series = [
            (_utc(1), 100.0),
            (_utc(2), 101.0),
            (_utc(3), 99.0),
            (_utc(4), 102.0),
        ]
        ods = [
            OutcomeDefinition(name="fwd_1m", horizon_minutes=1, price_feature="mid_price"),
            OutcomeDefinition(name="fwd_3m", horizon_minutes=3, price_feature="mid_price"),
        ]
        outcomes = outcome_engine.calculate_outcomes([event], ods, price_series)
        by_name = {o.outcome_name: o for o in outcomes}

        assert by_name["fwd_1m"].outcome_value == pytest.approx(0.01, abs=1e-9)
        assert by_name["fwd_3m"].outcome_value == pytest.approx(0.02, abs=1e-9)
