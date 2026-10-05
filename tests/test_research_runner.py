"""
tests/test_research_runner.py

Integration tests for ResearchRunner.
"""

import pytest
from datetime import datetime, timezone, timedelta
from unittest import mock

from research.models import (
    CrossingDirection,
    EventDefinition,
    EventMode,
    OutcomeDefinition,
    Operator,
    OutcomeStatus,
    ResearchSpec,
    ThresholdCondition,
)
from research.research_runner import ResearchRunner
from research.data_adapter import ResearchDataAdapter
from research.result_store import ResearchResultStore


def _utc(h: int, m: int = 0) -> datetime:
    return datetime(2026, 8, 31, h, m, tzinfo=timezone.utc)


def _make_spec(
    symbols=("BTCUSDT",),
    feature="return_1m",
    threshold=0.005,
    mode=EventMode.CROSSING,
    horizons=(1, 3),
    price_feature="mid_price",
) -> ResearchSpec:
    return ResearchSpec(
        research_id="test_runner_001",
        symbols=list(symbols),
        start_time=_utc(10),
        end_time=_utc(11),
        event_definition=EventDefinition(
            condition=ThresholdCondition(
                feature_name=feature, operator=Operator.GT, threshold=threshold
            ),
            event_mode=mode,
        ),
        outcome_definitions=[
            OutcomeDefinition(name=f"fwd_{h}m", horizon_minutes=h, price_feature=price_feature)
            for h in horizons
        ],
    )


@pytest.fixture
def mock_runner():
    """ResearchRunner with mocked adapter and store."""
    adapter = mock.MagicMock(spec=ResearchDataAdapter)
    store   = mock.MagicMock(spec=ResearchResultStore)
    store.save.return_value = (0, 0)
    runner = ResearchRunner(adapter=adapter, store=store)
    return runner, adapter, store


class TestResearchRunner:
    def test_pipeline_produces_result(self, mock_runner):
        runner, adapter, store = mock_runner
        spec = _make_spec()

        # Feature series with one crossing: prev=0.001, current=0.01
        T = _utc(10, 30)
        feature_series = [
            (_utc(10, 29), 0.001),  # below
            (T, 0.01),              # cross_up
        ]
        # Price series extended for outcomes
        price_series = [
            (T,                                  100.0),
            (T + timedelta(minutes=1),           101.0),
            (T + timedelta(minutes=3),           102.0),
            (T + timedelta(minutes=5),           103.0),
        ]

        adapter.get_feature_series.return_value = feature_series
        adapter.get_price_series.return_value   = price_series

        results, stats = runner.run(spec)

        assert len(results) == 1
        r = results[0]
        assert r.symbol == "BTCUSDT"
        assert r.research_id == "test_runner_001"
        assert len(r.events) == 1
        assert r.events[0].timestamp == T
        # 2 horizons × 1 event = 2 outcomes
        assert len(r.outcomes) == 2

    def test_no_events_yields_empty_outcomes(self, mock_runner):
        runner, adapter, _ = mock_runner
        spec = _make_spec()
        adapter.get_feature_series.return_value = [(_utc(10, i), 0.001) for i in range(5)]
        adapter.get_price_series.return_value   = [(_utc(10, i), 100.0) for i in range(5)]

        results, stats = runner.run(spec)
        assert results[0].events == []
        assert results[0].outcomes == []

    def test_multi_symbol_runs(self, mock_runner):
        runner, adapter, _ = mock_runner
        spec = _make_spec(symbols=("BTCUSDT", "ETHUSDT"))
        adapter.get_feature_series.return_value = []
        adapter.get_price_series.return_value   = []
        results, stats = runner.run(spec)
        assert len(results) == 2

    def test_outcomes_persisted(self, mock_runner):
        runner, adapter, store = mock_runner
        spec = _make_spec()
        T = _utc(10, 30)
        adapter.get_feature_series.return_value = [(_utc(10, 29), 0.001), (T, 0.01)]
        adapter.get_price_series.return_value   = [
            (T, 100.0),
            (T + timedelta(minutes=1), 101.0),
            (T + timedelta(minutes=3), 102.0),
        ]
        store.save.return_value = (2, 0)

        results, stats = runner.run(spec)
        assert store.save.called
        assert results[0].metadata["written"] == 2

    def test_deterministic_repeat_run(self, mock_runner):
        """Same inputs → same events and outcomes"""
        runner, adapter, _ = mock_runner
        spec = _make_spec()
        T = _utc(10, 30)
        feature_series = [(_utc(10, 29), 0.001), (T, 0.01)]
        price_series   = [
            (T, 100.0), (T + timedelta(minutes=1), 101.0), (T + timedelta(minutes=3), 103.0)
        ]
        adapter.get_feature_series.return_value = feature_series
        adapter.get_price_series.return_value   = price_series

        r1, stats1 = runner.run(spec)
        r2, stats2 = runner.run(spec)

        assert [e.timestamp for e in r1[0].events] == [e.timestamp for e in r2[0].events]
        assert [o.outcome_value for o in r1[0].outcomes] == [o.outcome_value for o in r2[0].outcomes]
