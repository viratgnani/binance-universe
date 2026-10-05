"""
tests/test_discovery_runner.py
"""

from datetime import datetime, timezone
from unittest.mock import patch, MagicMock
import pytest

from research.models import ResearchSpec, EventDefinition, ThresholdCondition, Operator, EventMode, EventPolicy, OutcomeDefinition
from research_discovery.models import DiscoverySpec, ExperimentStatus
from research_discovery.discovery_runner import DiscoveryRunner

def make_spec(id_: str) -> DiscoverySpec:
    rs = ResearchSpec(
        research_id=id_,
        symbols=["TEST"],
        start_time=datetime(2025, 1, 1, tzinfo=timezone.utc),
        end_time=datetime(2025, 1, 2, tzinfo=timezone.utc),
        event_definition=EventDefinition(
            condition=ThresholdCondition(feature_name="f", operator=Operator.GT, threshold=0.0),
            event_mode=EventMode.CONDITION,
            event_policy=EventPolicy.EVERY_OBSERVATION
        ),
        outcome_definitions=[
            OutcomeDefinition(name="ret_1m", horizon_minutes=1, price_feature="close")
        ]
    )
    return DiscoverySpec(
        experiment_id=id_,
        description="test",
        universe_name="test_univ",
        universe_definition="test_def",
        dataset_period="2025",
        is_exploratory=True,
        hypotheses_count=1,
        research_spec=rs
    )


@patch("research_discovery.discovery_runner.ExperimentRegistry")
@patch("research_discovery.discovery_runner.ResearchRunner")
def test_discovery_runner(mock_rr_cls, mock_reg_cls):
    mock_rr = MagicMock()
    mock_reg = MagicMock()
    mock_rr_cls.return_value = mock_rr
    mock_reg_cls.return_value = mock_reg
    
    mock_rr.run.return_value = (["result1"], ["stat1"])
    
    runner = DiscoveryRunner()
    spec = make_spec("exp_test")
    
    res, stat = runner.run(spec)
    
    assert res == ["result1"]
    assert stat == ["stat1"]
    
    # Verify registration
    mock_reg.register.assert_called_once_with(spec)
    
    # Verify execution delegated to frozen runner
    mock_rr.run.assert_called_once_with(
        spec=spec.research_spec,
        compute_statistics=True,
        group_by=None
    )
    
    # Verify status updates
    assert mock_reg.update_status.call_count == 2
    mock_reg.update_status.assert_any_call("exp_test", ExperimentStatus.RUNNING)
    mock_reg.update_status.assert_any_call("exp_test", ExperimentStatus.COMPLETE)
