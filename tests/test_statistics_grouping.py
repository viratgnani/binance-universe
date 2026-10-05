"""
tests/test_statistics_grouping.py
"""

from datetime import datetime, timezone

from research.models import (
    EventOutcome,
    OutcomeDefinition,
    OutcomeStatus,
)
from research.statistics_engine import StatisticsEngine

def _make_outcome(sym: str, hor: int, val: float) -> EventOutcome:
    return EventOutcome(
        research_id="rid",
        symbol=sym,
        event_timestamp=datetime(2026, 1, 1, tzinfo=timezone.utc),
        event_definition_hash="x",
        outcome_name=f"fwd_{hor}m",
        horizon_minutes=hor,
        outcome_value=val,
        status=OutcomeStatus.VALID,
    )

def test_grouping_dimensions():
    outcomes = [
        _make_outcome("BTC", 1, 0.01),
        _make_outcome("BTC", 1, 0.02),
        _make_outcome("BTC", 5, 0.10),
        _make_outcome("ETH", 1, -0.01),
    ]
    ods = [
        OutcomeDefinition(name="fwd_1m", horizon_minutes=1),
        OutcomeDefinition(name="fwd_5m", horizon_minutes=5),
    ]
    
    eng = StatisticsEngine()
    results = eng.compute(outcomes, ods, ["overall", "symbol", "horizon", "symbol_horizon"])
    
    # overall: fwd_1m (3 obs), fwd_5m (1 obs) = 2 results
    # symbol: BTC fwd_1m, BTC fwd_5m, ETH fwd_1m = 3 results
    # horizon: fwd_1m, fwd_5m = 2 results
    # symbol_horizon: BTC fwd_1m, BTC fwd_5m, ETH fwd_1m = 3 results
    # Total = 10 results
    
    assert len(results) == 10
    
    overall_1m = [r for r in results if r.grouping_type == "overall" and r.outcome_name == "fwd_1m"][0]
    assert overall_1m.sample.N == 3
    assert overall_1m.symbol is None
    assert overall_1m.horizon is None
    
    sym_btc_1m = [r for r in results if r.grouping_type == "symbol" and r.symbol == "BTC" and r.outcome_name == "fwd_1m"][0]
    assert sym_btc_1m.sample.N == 2
    assert sym_btc_1m.horizon is None
    
    symhor_btc_5m = [r for r in results if r.grouping_type == "symbol_horizon" and r.symbol == "BTC" and r.horizon == "5"][0]
    assert symhor_btc_5m.sample.N == 1
    assert symhor_btc_5m.outcome_name == "fwd_5m"
