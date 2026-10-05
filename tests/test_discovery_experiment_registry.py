"""
tests/test_discovery_experiment_registry.py
"""

import shutil
from pathlib import Path
from datetime import datetime, timezone
import pytest

from market_data.config import MarketDataConfig
from research.models import ResearchSpec, EventDefinition, ThresholdCondition, Operator, EventMode, EventPolicy, OutcomeDefinition
from research_discovery.models import DiscoverySpec, ExperimentStatus
from research_discovery.experiment_registry import ExperimentRegistry

@pytest.fixture
def registry(tmp_path):
    cfg = MarketDataConfig()
    cfg.OHLCV_DIR = str(tmp_path / "data" / "ohlcv")
    reg = ExperimentRegistry(cfg)
    yield reg
    if reg.registry_dir.exists():
        shutil.rmtree(reg.registry_dir)

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

def test_registry_register_and_list(registry):
    spec = make_spec("exp1")
    registry.register(spec)
    
    entries = registry.list_entries()
    assert len(entries) == 1
    assert entries[0].experiment_id == "exp1"
    assert entries[0].status == ExperimentStatus.REGISTERED
    assert entries[0].spec_summary["is_exploratory"] is True
    
    # Duplicate should fail
    with pytest.raises(ValueError):
        registry.register(spec)

def test_registry_update_status(registry):
    spec = make_spec("exp2")
    registry.register(spec)
    
    registry.update_status("exp2", ExperimentStatus.RUNNING)
    entry = registry.get_entry("exp2")
    assert entry.status == ExperimentStatus.RUNNING
