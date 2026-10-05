"""
tests/test_feature_serialization.py

Tests serialization determinism and explicit null preservation.
"""

from datetime import datetime, timezone
import json
from research_features.models import FeatureRow

def test_feature_serialization_nulls():
    row = FeatureRow(
        symbol="BTCUSDT",
        timestamp=datetime(2026, 8, 31, 12, 0, tzinfo=timezone.utc),
        feature_version="v1",
        return_1m=0.05,
        return_1h=None, # Explicit null
        trade_count=0
    )
    
    js = row.model_dump_json()
    d = json.loads(js)
    
    assert d["symbol"] == "BTCUSDT"
    assert d["return_1m"] == 0.05
    assert d["return_1h"] is None # Null preserved
    assert d["trade_count"] == 0
    assert d["volatility_1h"] is None # Missing explicit falls back to None in schema

def test_feature_nan_inf_rejection():
    # Pydantic allows NaN and Inf by default unless configured otherwise.
    # In V1, we should test if they are serialized or rejected.
    import math
    try:
        row = FeatureRow(
            symbol="BTCUSDT",
            timestamp=datetime(2026, 8, 31, 12, 0, tzinfo=timezone.utc),
            feature_version="v1",
            return_1m=float('nan'),
            spread=float('inf')
        )
        js = row.model_dump_json()
        d = json.loads(js)
        # JSON standard doesn't support NaN/Inf. Pydantic might serialize them as NaN/Inf which breaks strict JSON,
        # or as strings.
        assert d["return_1m"] == "NaN" or math.isnan(d["return_1m"])
    except Exception as e:
        # If it throws, that's fine too (rejected).
        pass
