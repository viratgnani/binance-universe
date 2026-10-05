"""
tests/test_indicator_store.py
"""

import tempfile
from pathlib import Path
from datetime import datetime, timezone
from market_data.config import MarketDataConfig
from indicators.models import IndicatorValue
from indicators.store import IndicatorStore

def test_indicator_store_idempotency():
    with tempfile.TemporaryDirectory() as td:
        cfg = MarketDataConfig()
        cfg.OHLCV_DIR = Path(td) / "ohlcv"
        store = IndicatorStore(cfg)
        
        v1 = IndicatorValue(
            symbol="BTC",
            timestamp=datetime(2026, 1, 1, tzinfo=timezone.utc),
            indicator_name="rsi",
            indicator_version="v1",
            parameter_hash="h1",
            input_feature="mid_price",
            value=50.0,
        )
        v2 = IndicatorValue(
            symbol="BTC",
            timestamp=datetime(2026, 1, 1, tzinfo=timezone.utc),
            indicator_name="rsi",
            indicator_version="v1",
            parameter_hash="h2",  # different params, same time
            input_feature="mid_price",
            value=60.0,
        )
        
        # Initial save
        written, skipped = store.save([v1, v2])
        assert written == 2
        assert skipped == 0
        
        # Duplicate save
        written, skipped = store.save([v1, v2])
        assert written == 0
        assert skipped == 2
        
        # Load
        loaded = store.load("BTC", datetime(2026, 1, 1, tzinfo=timezone.utc), datetime(2026, 1, 2, tzinfo=timezone.utc))
        assert len(loaded) == 2
        assert {v.parameter_hash for v in loaded} == {"h1", "h2"}
