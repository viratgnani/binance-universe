import pytest
from datetime import datetime, timezone
from research_features.registry import FEATURE_REGISTRY
from research_features.models import FeatureRow
from market_data.models import Candle, AggTrade
from market_data.ob_models import OrderBookCheckpoint
from research_features.calculators import (
    calculate_price_features,
    calculate_volatility_features,
    calculate_volume_features,
    calculate_trade_features,
    calculate_order_book_features
)


def test_registry_completeness():
    # 1. Collect all features from calculators
    T = datetime(2026, 8, 31, 12, 0, tzinfo=timezone.utc)
    
    # We pass empty data to get the dict shapes
    p_feat = calculate_price_features([], T)
    v_feat = calculate_volatility_features([], T)
    vol_feat = calculate_volume_features([], T)
    t_feat = calculate_trade_features([], T)
    ob_feat = calculate_order_book_features(OrderBookCheckpoint(
        symbol="BTCUSDT", last_update_id=1, exchange_event_time=T, local_checkpoint_time=T,
        synchronized=True, bids=[("100", "1")], asks=[("101", "1")]
    ))
    
    implemented_features = set()
    for d in [p_feat, v_feat, vol_feat, t_feat, ob_feat]:
        implemented_features.update(d.keys())
        
    # 2. Collect all features from registry
    registered_features = set(FEATURE_REGISTRY.keys())
    
    # 3. Collect all features from Pydantic schema
    # Ignore base fields
    base_fields = {"symbol", "timestamp", "feature_version"}
    schema_features = set(FeatureRow.model_fields.keys()) - base_fields
    
    # Assert IMPLEMENTATION -> REGISTRY
    missing_in_registry = implemented_features - registered_features
    assert not missing_in_registry, f"Features missing from registry: {missing_in_registry}"
    
    # Assert REGISTRY -> IMPLEMENTATION
    missing_in_impl = registered_features - implemented_features
    assert not missing_in_impl, f"Features in registry but no implementation: {missing_in_impl}"
    
    # Assert SCHEMA matching
    assert schema_features == implemented_features, "Schema does not exactly match implemented features"
    
    # Verify Metadata Completeness
    for name, meta in FEATURE_REGISTRY.items():
        assert meta.name == name
        assert meta.version == "v1"
        assert meta.description
        assert meta.source_dataset
        assert meta.lookback
        assert meta.timestamp_semantics
        assert meta.missing_data_policy
        
    # Confirm the specific requested ones are there
    expected_depth = [
        "bid_depth_10", "ask_depth_10", "depth_imbalance_10",
        "bid_depth_20", "ask_depth_20", "depth_imbalance_20"
    ]
    for e in expected_depth:
        assert e in registered_features
