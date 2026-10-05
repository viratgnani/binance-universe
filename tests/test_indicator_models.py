"""
tests/test_indicator_models.py
"""

from datetime import datetime, timezone
from indicators.models import IndicatorDefinition, IndicatorValue

def test_indicator_definition_hash_deterministic():
    d1 = IndicatorDefinition(
        indicator_name="rsi",
        parameters={"period": 14},
    )
    d2 = IndicatorDefinition(
        indicator_name="rsi",
        parameters={"period": 14},
    )
    d3 = IndicatorDefinition(
        indicator_name="rsi",
        parameters={"period": 7},
    )
    
    assert d1.parameter_hash() == d2.parameter_hash()
    assert d1.parameter_hash() != d3.parameter_hash()

def test_indicator_value_logical_key():
    v = IndicatorValue(
        symbol="BTC",
        timestamp=datetime(2026, 1, 1, tzinfo=timezone.utc),
        indicator_name="rsi",
        indicator_version="v1",
        parameter_hash="hash123",
        input_feature="mid_price",
        value=50.0,
    )
    key = v.logical_key()
    assert key == ("BTC", datetime(2026, 1, 1, tzinfo=timezone.utc), "rsi", "v1", "hash123")
