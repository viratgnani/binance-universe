"""
tests/test_statistics_models.py
"""

from research.models import (
    DescriptiveStats,
    OutcomeStatus,
    OutcomeType,
    Quantiles,
    ReturnStats,
    SampleQuality,
    StatisticsResult,
)

def test_sample_quality_n_property():
    sq = SampleQuality(
        event_count=100,
        valid_outcome_count=95,
        missing_outcome_count=2,
        insufficient_future_data_count=1,
        invalid_outcome_count=2,
    )
    assert sq.N == 95

def test_statistics_result_logical_key():
    sr = StatisticsResult(
        research_id="test_rid",
        symbol="BTCUSDT",
        horizon="1",
        grouping_type="symbol_horizon",
        outcome_name="fwd_1m",
        outcome_type=OutcomeType.RETURN_LIKE,
        sample=SampleQuality(event_count=1, valid_outcome_count=1, missing_outcome_count=0, insufficient_future_data_count=0, invalid_outcome_count=0),
        descriptive=DescriptiveStats(),
        returns=ReturnStats(),
        quantiles=Quantiles(),
    )
    key = sr.logical_key()
    assert key == ("test_rid", "symbol_horizon", "BTCUSDT", "1", "fwd_1m")

def test_statistics_result_logical_key_overall():
    sr = StatisticsResult(
        research_id="test_rid",
        grouping_type="overall",
        outcome_name="fwd_1m",
        outcome_type=OutcomeType.RETURN_LIKE,
        sample=SampleQuality(event_count=1, valid_outcome_count=1, missing_outcome_count=0, insufficient_future_data_count=0, invalid_outcome_count=0),
        descriptive=DescriptiveStats(),
        returns=ReturnStats(),
        quantiles=Quantiles(),
    )
    key = sr.logical_key()
    assert key == ("test_rid", "overall", "ALL", "ALL", "fwd_1m")
