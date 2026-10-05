"""
experiment_rsi.py

Research Experiment V1: RSI(14) Crosses Above 90 — Alt-Perpetual Event Study

Research Question:
After RSI(14) crosses above 90, what happens to eligible Binance altcoin perpetual futures over the next 1, 3, 5, and 10 minutes?
"""

import logging
import sys
from datetime import datetime, timezone

from research.models import (
    ResearchSpec,
    EventDefinition,
    ThresholdCondition,
    Operator,
    EventMode,
    CrossingDirection,
    OutcomeDefinition,
    OutcomeType
)
from research.research_runner import ResearchRunner
from market_data.readiness import load_eligible_alt_symbols

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(name)s  %(message)s",
    datefmt="%Y-%m-%dT%H:%M:%SZ",
)
logger = logging.getLogger("experiment_rsi")

def main():
    start_time = datetime(2024, 9, 1, tzinfo=timezone.utc)
    end_time = datetime(2025, 9, 1, tzinfo=timezone.utc)
    
    # Load all eligible symbols. Exclude BTC, ETH, SOL.
    symbols = load_eligible_alt_symbols()
    excluded = {"BTCUSDT", "ETHUSDT", "SOLUSDT"}
    symbols = [s for s in symbols if s not in excluded]
    
    logger.info("Loaded %d eligible alt symbols for RSI experiment.", len(symbols))
    
    # Define Event: RSI(14) crosses above 90
    ed = EventDefinition(
        condition=ThresholdCondition(
            feature_name="rsi",  # This assumes data_adapter knows how to pull "rsi"
            operator=Operator.GT,
            threshold=90.0,
        ),
        event_mode=EventMode.CROSSING,
        crossing_direction=CrossingDirection.CROSS_UP,
    )
    
    # Define Outcomes: forward returns over 1, 3, 5, 10 minutes
    ods = [
        OutcomeDefinition(name="return_1m", horizon_minutes=1, price_feature="mid_price", outcome_type=OutcomeType.RETURN_LIKE),
        OutcomeDefinition(name="return_3m", horizon_minutes=3, price_feature="mid_price", outcome_type=OutcomeType.RETURN_LIKE),
        OutcomeDefinition(name="return_5m", horizon_minutes=5, price_feature="mid_price", outcome_type=OutcomeType.RETURN_LIKE),
        OutcomeDefinition(name="return_10m", horizon_minutes=10, price_feature="mid_price", outcome_type=OutcomeType.RETURN_LIKE),
    ]
    
    spec = ResearchSpec(
        research_id="rsi_cross_90_alts",
        symbols=symbols,
        start_time=start_time,
        end_time=end_time,
        feature_version="v1",
        engine_version="research_v1",
        event_definition=ed,
        outcome_definitions=ods
    )
    
    logger.info("Starting ResearchRunner...")
    runner = ResearchRunner()
    
    # Run the generic event study and compute statistics
    # group_by could be ["overall"], or ["horizon"]
    results, stats = runner.run(spec, compute_statistics=True, group_by=["horizon", "overall"])
    
    logger.info("Experiment complete. Stats computed: %d", len(stats))
    for stat in stats:
        logger.info("Stat: %s | %s -> N=%d | Mean=%s", stat.grouping_type, stat.outcome_name, stat.sample.valid_outcome_count, stat.descriptive.mean)

if __name__ == "__main__":
    main()
