"""
tests/test_research_models.py

Tests for Research Engine V1 Pydantic models.
"""

import json
import pytest
from datetime import datetime, timedelta, timezone

from research.models import (
    CrossingDirection,
    EventDefinition,
    EventMode,
    EventPolicy,
    Operator,
    OutcomeDefinition,
    OutcomeStatus,
    ResearchSpec,
    ThresholdCondition,
    Event,
    EventOutcome,
    ResearchResult,
)


def _utc(h: int, m: int = 0) -> datetime:
    return datetime(2026, 8, 31, h, m, tzinfo=timezone.utc)


# ---------------------------------------------------------------------------
# ThresholdCondition
# ---------------------------------------------------------------------------

class TestThresholdCondition:
    def test_gt(self):
        c = ThresholdCondition(feature_name="f", operator=Operator.GT, threshold=90.0)
        assert c.evaluate(91.0) is True
        assert c.evaluate(90.0) is False
        assert c.evaluate(89.0) is False

    def test_gte(self):
        c = ThresholdCondition(feature_name="f", operator=Operator.GTE, threshold=90.0)
        assert c.evaluate(90.0) is True
        assert c.evaluate(89.9) is False

    def test_lt(self):
        c = ThresholdCondition(feature_name="f", operator=Operator.LT, threshold=90.0)
        assert c.evaluate(89.0) is True
        assert c.evaluate(90.0) is False

    def test_lte(self):
        c = ThresholdCondition(feature_name="f", operator=Operator.LTE, threshold=90.0)
        assert c.evaluate(90.0) is True
        assert c.evaluate(90.1) is False

    def test_eq(self):
        c = ThresholdCondition(feature_name="f", operator=Operator.EQ, threshold=90.0)
        assert c.evaluate(90.0) is True
        assert c.evaluate(90.1) is False

    def test_neq(self):
        c = ThresholdCondition(feature_name="f", operator=Operator.NEQ, threshold=90.0)
        assert c.evaluate(91.0) is True
        assert c.evaluate(90.0) is False


# ---------------------------------------------------------------------------
# EventDefinition
# ---------------------------------------------------------------------------

class TestEventDefinition:
    def test_default_mode_is_crossing(self):
        ed = EventDefinition(
            condition=ThresholdCondition(feature_name="f", operator=Operator.GT, threshold=90.0)
        )
        assert ed.event_mode == EventMode.CROSSING

    def test_stable_hash_deterministic(self):
        ed1 = EventDefinition(
            condition=ThresholdCondition(feature_name="f", operator=Operator.GT, threshold=90.0)
        )
        ed2 = EventDefinition(
            condition=ThresholdCondition(feature_name="f", operator=Operator.GT, threshold=90.0)
        )
        assert ed1.stable_hash() == ed2.stable_hash()

    def test_stable_hash_differs_on_threshold(self):
        ed1 = EventDefinition(condition=ThresholdCondition(feature_name="f", operator=Operator.GT, threshold=90.0))
        ed2 = EventDefinition(condition=ThresholdCondition(feature_name="f", operator=Operator.GT, threshold=91.0))
        assert ed1.stable_hash() != ed2.stable_hash()

    def test_condition_mode_event_policy_allowed(self):
        ed = EventDefinition(
            condition=ThresholdCondition(feature_name="f", operator=Operator.GT, threshold=90.0),
            event_mode=EventMode.CONDITION,
            event_policy=EventPolicy.FIRST_ENTRY,
        )
        assert ed.event_policy == EventPolicy.FIRST_ENTRY

    def test_crossing_mode_rejects_non_default_policy(self):
        with pytest.raises(Exception):
            EventDefinition(
                condition=ThresholdCondition(feature_name="f", operator=Operator.GT, threshold=90.0),
                event_mode=EventMode.CROSSING,
                event_policy=EventPolicy.FIRST_ENTRY,
            )

    def test_serialization_round_trip(self):
        ed = EventDefinition(
            condition=ThresholdCondition(feature_name="return_1m", operator=Operator.GT, threshold=0.005),
            event_mode=EventMode.CROSSING,
            crossing_direction=CrossingDirection.CROSS_UP,
        )
        js = ed.model_dump_json()
        ed2 = EventDefinition.model_validate_json(js)
        assert ed == ed2


# ---------------------------------------------------------------------------
# OutcomeDefinition
# ---------------------------------------------------------------------------

class TestOutcomeDefinition:
    def test_horizon_property(self):
        od = OutcomeDefinition(name="fwd_1m", horizon_minutes=1, price_feature="mid_price")
        assert od.horizon == timedelta(minutes=1)

    def test_horizon_must_be_positive(self):
        with pytest.raises(Exception):
            OutcomeDefinition(name="bad", horizon_minutes=0, price_feature="mid_price")

    def test_serialization(self):
        od = OutcomeDefinition(name="fwd_10m", horizon_minutes=10, price_feature="mid_price")
        js = od.model_dump_json()
        od2 = OutcomeDefinition.model_validate_json(js)
        assert od == od2


# ---------------------------------------------------------------------------
# ResearchSpec
# ---------------------------------------------------------------------------

class TestResearchSpec:
    def _make_spec(self, **kw) -> ResearchSpec:
        defaults = dict(
            research_id="test_001",
            symbols=["BTCUSDT"],
            start_time=_utc(10),
            end_time=_utc(11),
            event_definition=EventDefinition(
                condition=ThresholdCondition(feature_name="return_1m", operator=Operator.GT, threshold=0.005)
            ),
            outcome_definitions=[
                OutcomeDefinition(name="fwd_1m", horizon_minutes=1, price_feature="mid_price")
            ],
        )
        defaults.update(kw)
        return ResearchSpec(**defaults)

    def test_valid_spec(self):
        spec = self._make_spec()
        assert spec.engine_version == "research_v1"

    def test_end_before_start_rejected(self):
        with pytest.raises(Exception):
            self._make_spec(start_time=_utc(11), end_time=_utc(10))

    def test_stable_hash_deterministic(self):
        spec1 = self._make_spec()
        spec2 = self._make_spec()
        assert spec1.stable_hash() == spec2.stable_hash()

    def test_serialization_round_trip(self):
        spec = self._make_spec()
        js = spec.model_dump_json()
        spec2 = ResearchSpec.model_validate_json(js)
        assert spec == spec2


# ---------------------------------------------------------------------------
# Event
# ---------------------------------------------------------------------------

class TestEvent:
    def test_logical_key(self):
        e = Event(
            research_id="r1",
            symbol="BTCUSDT",
            timestamp=_utc(10),
            event_definition_hash="abc123",
            feature_name="return_1m",
            feature_value=0.01,
            direction=None,
        )
        key = e.logical_key()
        assert key == ("r1", "BTCUSDT", _utc(10), "abc123")

    def test_serialization(self):
        e = Event(
            research_id="r1", symbol="BTCUSDT", timestamp=_utc(10),
            event_definition_hash="abc", feature_name="f", feature_value=1.0,
            direction=CrossingDirection.CROSS_UP,
        )
        e2 = Event.model_validate_json(e.model_dump_json())
        assert e == e2


# ---------------------------------------------------------------------------
# EventOutcome
# ---------------------------------------------------------------------------

class TestEventOutcome:
    def test_valid_outcome(self):
        o = EventOutcome(
            research_id="r1", symbol="BTCUSDT",
            event_timestamp=_utc(10), event_definition_hash="abc",
            outcome_name="fwd_1m", horizon_minutes=1,
            outcome_value=0.01, outcome_timestamp=_utc(10, 1),
            status=OutcomeStatus.VALID,
        )
        assert o.outcome_value == pytest.approx(0.01)

    def test_logical_key(self):
        o = EventOutcome(
            research_id="r1", symbol="BTCUSDT",
            event_timestamp=_utc(10), event_definition_hash="abc",
            outcome_name="fwd_1m", horizon_minutes=1,
            status=OutcomeStatus.MISSING_PRICE,
        )
        assert o.logical_key() == ("r1", "BTCUSDT", _utc(10), "abc", "fwd_1m")

    def test_serialization(self):
        o = EventOutcome(
            research_id="r1", symbol="B", event_timestamp=_utc(10),
            event_definition_hash="x", outcome_name="n", horizon_minutes=5,
            status=OutcomeStatus.INSUFFICIENT_FUTURE_DATA,
        )
        o2 = EventOutcome.model_validate_json(o.model_dump_json())
        assert o == o2
