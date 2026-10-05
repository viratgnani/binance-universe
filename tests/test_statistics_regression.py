"""
tests/test_statistics_regression.py
"""

from unittest import mock
from datetime import datetime, timezone
from research.models import (
    CrossingDirection,
    EventDefinition,
    EventMode,
    Operator,
    OutcomeDefinition,
    ResearchSpec,
    ThresholdCondition,
)
from research.research_runner import ResearchRunner

def test_runner_works_without_statistics():
    spec = ResearchSpec(
        research_id="test_reg_1",
        symbols=["BTCUSDT"],
        start_time=datetime(2026, 1, 1, tzinfo=timezone.utc),
        end_time=datetime(2026, 1, 2, tzinfo=timezone.utc),
        event_definition=EventDefinition(
            condition=ThresholdCondition(feature_name="f", operator=Operator.GT, threshold=0.0),
            event_mode=EventMode.CROSSING,
            crossing_direction=CrossingDirection.ANY,
        ),
        outcome_definitions=[OutcomeDefinition(name="fwd", horizon_minutes=1)],
    )
    
    runner = ResearchRunner()
    
    with mock.patch.object(runner, "_run_symbol") as mock_run:
        from research.models import ResearchResult
        mock_run.return_value = ResearchResult(
            research_id="test_reg_1",
            symbol="BTCUSDT",
            feature_version="v1",
            engine_version="v1",
            events=[],
            outcomes=[],
            metadata={},
        )
        
        # Test default backward compatibility
        res, stats = runner.run(spec)
        assert len(res) == 1
        assert len(stats) == 0
        mock_run.assert_called_once()
