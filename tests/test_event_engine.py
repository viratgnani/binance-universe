"""
tests/test_event_engine.py

Comprehensive tests for EventEngine.
Covers all operators, condition modes, crossing modes, edge cases,
and determinism requirements.
"""

import random
import pytest
from datetime import datetime, timezone, timedelta

from research.event_engine import EventEngine
from research.models import (
    CrossingDirection,
    EventDefinition,
    EventMode,
    EventPolicy,
    Operator,
    ThresholdCondition,
)

RID = "test_run"
SYM = "BTCUSDT"

def _utc(minute: int) -> datetime:
    return datetime(2026, 8, 31, 10, 0, tzinfo=timezone.utc) + timedelta(minutes=minute)


def _make_def(
    op: Operator = Operator.GT,
    threshold: float = 90.0,
    mode: EventMode = EventMode.CONDITION,
    policy: EventPolicy = EventPolicy.EVERY_OBSERVATION,
    direction: CrossingDirection = CrossingDirection.ANY,
    feature: str = "return_1m",
) -> EventDefinition:
    return EventDefinition(
        condition=ThresholdCondition(feature_name=feature, operator=op, threshold=threshold),
        event_mode=mode,
        event_policy=policy,
        crossing_direction=direction,
    )


def _series(*pairs) -> list:
    return [(ts, val) for ts, val in pairs]


engine = EventEngine()


# ---------------------------------------------------------------------------
# SECTION 1: All six operators — condition mode
# ---------------------------------------------------------------------------

class TestOperators:
    """Hand-calculated fixture: threshold=90"""

    def _run(self, op, values):
        series = [(_utc(i), v) for i, v in enumerate(values)]
        ed = _make_def(op=op, threshold=90.0, mode=EventMode.CONDITION)
        return engine.detect_events(RID, SYM, ed, series)

    def test_gt(self):
        events = self._run(Operator.GT, [89, 90, 91])
        assert len(events) == 1
        assert events[0].feature_value == 91.0

    def test_gte(self):
        events = self._run(Operator.GTE, [89, 90, 91])
        assert len(events) == 2  # 90 and 91

    def test_lt(self):
        events = self._run(Operator.LT, [89, 90, 91])
        assert len(events) == 1
        assert events[0].feature_value == 89.0

    def test_lte(self):
        events = self._run(Operator.LTE, [89, 90, 91])
        assert len(events) == 2  # 89 and 90

    def test_eq(self):
        events = self._run(Operator.EQ, [89, 90, 91])
        assert len(events) == 1
        assert events[0].feature_value == 90.0

    def test_neq(self):
        events = self._run(Operator.NEQ, [89, 90, 91])
        assert len(events) == 2


# ---------------------------------------------------------------------------
# SECTION 2: Condition mode — every_observation vs first_entry
# ---------------------------------------------------------------------------

class TestConditionMode:
    def test_every_observation_emits_all(self):
        """consecutive satisfying bars each generate an event"""
        series = [(_utc(i), v) for i, v in enumerate([85, 91, 92, 93, 88])]
        ed = _make_def(mode=EventMode.CONDITION, policy=EventPolicy.EVERY_OBSERVATION)
        events = engine.detect_events(RID, SYM, ed, series)
        assert len(events) == 3  # 91, 92, 93

    def test_first_entry_only_on_transition(self):
        """only the first bar after a non-satisfying bar generates an event"""
        series = [(_utc(i), v) for i, v in enumerate([85, 91, 92, 93, 88, 95])]
        ed = _make_def(mode=EventMode.CONDITION, policy=EventPolicy.FIRST_ENTRY)
        events = engine.detect_events(RID, SYM, ed, series)
        # 85->91 = entry, 88->95 = re-entry, 91->92->93 are sustained (no new entry)
        assert len(events) == 2
        assert events[0].feature_value == 91.0
        assert events[1].feature_value == 95.0

    def test_first_entry_no_prior_non_satisfying(self):
        """starts with satisfying value — counts as first entry"""
        series = [(_utc(i), v) for i, v in enumerate([91, 92, 85])]
        ed = _make_def(mode=EventMode.CONDITION, policy=EventPolicy.FIRST_ENTRY)
        events = engine.detect_events(RID, SYM, ed, series)
        # 91 is first satisfying with no prior — should emit
        assert len(events) == 1

    def test_none_treated_as_non_satisfying_for_first_entry(self):
        """None resets first_entry state"""
        series = [(_utc(0), 91.0), (_utc(1), None), (_utc(2), 95.0)]
        ed = _make_def(mode=EventMode.CONDITION, policy=EventPolicy.FIRST_ENTRY)
        events = engine.detect_events(RID, SYM, ed, series)
        # 91 = first entry, None resets, 95 = new first entry
        assert len(events) == 2


# ---------------------------------------------------------------------------
# SECTION 3: Crossing mode
# ---------------------------------------------------------------------------

class TestCrossingMode:
    """
    Hand-calculated fixture:
    t=0: 89  (below threshold=90)
    t=1: 91  → cross_up event
    t=2: 93
    t=3: 88  → cross_down event
    t=4: 92  → cross_up event
    """

    def _series(self):
        return [(_utc(i), v) for i, v in enumerate([89, 91, 93, 88, 92])]

    def test_cross_up(self):
        ed = _make_def(mode=EventMode.CROSSING, direction=CrossingDirection.CROSS_UP)
        events = engine.detect_events(RID, SYM, ed, self._series())
        assert len(events) == 2
        assert events[0].timestamp == _utc(1)
        assert events[1].timestamp == _utc(4)
        for e in events:
            assert e.direction == CrossingDirection.CROSS_UP

    def test_cross_down(self):
        ed = _make_def(mode=EventMode.CROSSING, direction=CrossingDirection.CROSS_DOWN)
        events = engine.detect_events(RID, SYM, ed, self._series())
        assert len(events) == 1
        assert events[0].timestamp == _utc(3)
        assert events[0].direction == CrossingDirection.CROSS_DOWN

    def test_any_direction(self):
        ed = _make_def(mode=EventMode.CROSSING, direction=CrossingDirection.ANY)
        events = engine.detect_events(RID, SYM, ed, self._series())
        assert len(events) == 3
        directions = [e.direction for e in events]
        assert CrossingDirection.CROSS_UP in directions
        assert CrossingDirection.CROSS_DOWN in directions

    def test_exact_threshold_boundary(self):
        """
        prev=90 (= threshold), current=91 → cross_up (prev <= threshold is true)
        prev=90 (= threshold), current=89 → cross_down (prev >= threshold is true)
        """
        s_up   = [(_utc(0), 90.0), (_utc(1), 91.0)]
        s_down = [(_utc(0), 90.0), (_utc(1), 89.0)]

        ed_up   = _make_def(mode=EventMode.CROSSING, direction=CrossingDirection.CROSS_UP)
        ed_down = _make_def(mode=EventMode.CROSSING, direction=CrossingDirection.CROSS_DOWN)

        assert len(engine.detect_events(RID, SYM, ed_up,   s_up))   == 1
        assert len(engine.detect_events(RID, SYM, ed_down, s_down)) == 1

    def test_none_skipped_crossing(self):
        """None values don't update prev_val — crossing still detected across gap"""
        series = [
            (_utc(0), 89.0),
            (_utc(1), None),   # skipped
            (_utc(2), 91.0),   # cross_up vs 89 from t=0
        ]
        ed = _make_def(mode=EventMode.CROSSING, direction=CrossingDirection.CROSS_UP)
        events = engine.detect_events(RID, SYM, ed, series)
        assert len(events) == 1
        assert events[0].timestamp == _utc(2)

    def test_no_crossing_on_flat_series(self):
        series = [(_utc(i), 91.0) for i in range(5)]
        ed = _make_def(mode=EventMode.CROSSING)
        events = engine.detect_events(RID, SYM, ed, series)
        assert len(events) == 0

    def test_no_crossing_all_none(self):
        series = [(_utc(i), None) for i in range(5)]
        ed = _make_def(mode=EventMode.CROSSING)
        events = engine.detect_events(RID, SYM, ed, series)
        assert len(events) == 0

    def test_single_observation_no_crossing(self):
        ed = _make_def(mode=EventMode.CROSSING)
        events = engine.detect_events(RID, SYM, ed, [(_utc(0), 91.0)])
        assert len(events) == 0


# ---------------------------------------------------------------------------
# SECTION 4: Determinism — ordering
# ---------------------------------------------------------------------------

class TestDeterminism:
    def test_shuffled_produces_same_events(self):
        series = [(_utc(i), v) for i, v in enumerate([85, 91, 93, 88, 92])]
        ed = _make_def(mode=EventMode.CROSSING, direction=CrossingDirection.ANY)

        expected = engine.detect_events(RID, SYM, ed, series)

        for _ in range(5):
            shuffled = list(series)
            random.shuffle(shuffled)
            result = engine.detect_events(RID, SYM, ed, shuffled)
            assert [e.timestamp for e in result] == [e.timestamp for e in expected]
            assert [e.feature_value for e in result] == [e.feature_value for e in expected]

    def test_reversed_produces_same_events(self):
        series = [(_utc(i), v) for i, v in enumerate([85, 91, 93, 88, 92])]
        ed = _make_def(mode=EventMode.CROSSING)
        expected = engine.detect_events(RID, SYM, ed, series)
        reversed_result = engine.detect_events(RID, SYM, ed, list(reversed(series)))
        assert [e.timestamp for e in reversed_result] == [e.timestamp for e in expected]


# ---------------------------------------------------------------------------
# SECTION 5: Edge cases
# ---------------------------------------------------------------------------

class TestEdgeCases:
    def test_empty_series(self):
        ed = _make_def()
        assert engine.detect_events(RID, SYM, ed, []) == []

    def test_all_none_condition(self):
        series = [(_utc(i), None) for i in range(5)]
        ed = _make_def(mode=EventMode.CONDITION)
        assert engine.detect_events(RID, SYM, ed, series) == []

    def test_event_carries_correct_metadata(self):
        series = [(_utc(0), 89.0), (_utc(1), 91.0)]
        ed = _make_def(mode=EventMode.CROSSING, direction=CrossingDirection.CROSS_UP, feature="return_1m")
        events = engine.detect_events(RID, SYM, ed, series)
        assert len(events) == 1
        e = events[0]
        assert e.research_id == RID
        assert e.symbol == SYM
        assert e.timestamp == _utc(1)
        assert e.feature_name == "return_1m"
        assert e.feature_value == 91.0
        assert e.direction == CrossingDirection.CROSS_UP
        assert e.event_definition_hash == ed.stable_hash()
