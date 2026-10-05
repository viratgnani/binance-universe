"""
tests/test_discovery_feature_store.py
"""

import shutil
from datetime import datetime, timezone
import pytest

from market_data.config import MarketDataConfig
from research_discovery.feature_store import DiscoveryFeatureStore
from research_discovery.models import DiscoveryFeatureRow

@pytest.fixture
def store(tmp_path):
    cfg = MarketDataConfig()
    cfg.OHLCV_DIR = str(tmp_path / "data" / "ohlcv")
    s = DiscoveryFeatureStore(cfg)
    yield s
    if s.data_dir.exists():
        shutil.rmtree(s.data_dir)

def test_feature_store_save_load(store):
    t0 = datetime(2025, 1, 1, 0, 0, tzinfo=timezone.utc)
    t1 = datetime(2025, 1, 1, 0, 1, tzinfo=timezone.utc)
    
    row1 = DiscoveryFeatureRow(symbol="TEST", timestamp=t0, close=100.0)
    row2 = DiscoveryFeatureRow(symbol="TEST", timestamp=t1, close=101.0, return_1m=0.01)
    
    # Save
    w, s = store.save([row1, row2])
    assert w == 2
    assert s == 0
    
    # Idempotent Save
    w, s = store.save([row1, row2])
    assert w == 0
    assert s == 2
    
    # Load
    loaded = store.load("TEST", t0, t1)
    assert len(loaded) == 2
    assert loaded[0].timestamp == t0
    assert loaded[1].return_1m == 0.01
