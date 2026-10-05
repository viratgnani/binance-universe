"""
tests/test_feature_reproducibility.py

Tests to ensure feature generation is deterministic and reproducible.
"""

from unittest import mock
from datetime import datetime, timezone, timedelta

from market_data.models import Candle
from research_features.engine import FeatureEngine


def _dt(minute: int) -> datetime:
    return datetime(2026, 8, 31, 12, 0, tzinfo=timezone.utc) + timedelta(minutes=minute)


@mock.patch("research_features.engine.OHLCVStore")
@mock.patch("research_features.engine.TradesStore")
@mock.patch("research_features.engine.OrderBookCheckpointStore")
def test_reproducibility(mock_ob_store, mock_trades_store, mock_ohlcv_store):
    # Mock some data
    mock_ohlcv = mock_ohlcv_store.return_value
    mock_trades = mock_trades_store.return_value
    mock_ob = mock_ob_store.return_value
    
    # We just need it not to crash and return something consistent
    mock_ohlcv.load.return_value = [
        Candle(symbol="BTCUSDT", interval="1m", open_time=_dt(0), close_time=_dt(0) + timedelta(minutes=1, milliseconds=-1), open="100", high="100", low="100", close="100", volume="10", quote_volume="1000", trade_count=1, taker_buy_base_vol="10", taker_buy_quote_vol="1000"),
        Candle(symbol="BTCUSDT", interval="1m", open_time=_dt(1), close_time=_dt(1) + timedelta(minutes=1, milliseconds=-1), open="100", high="110", low="90", close="105", volume="20", quote_volume="2000", trade_count=2, taker_buy_base_vol="20", taker_buy_quote_vol="2000"),
    ]
    mock_trades.load.return_value = []
    
    # Run A
    engine_a = FeatureEngine()
    engine_a._ohlcv_store = mock_ohlcv
    engine_a._trades_store = mock_trades
    engine_a._ob_store = mock_ob
    
    rows_a = engine_a.generate_features("BTCUSDT", _dt(2), _dt(5))
    
    # Run B
    engine_b = FeatureEngine()
    engine_b._ohlcv_store = mock_ohlcv
    engine_b._trades_store = mock_trades
    engine_b._ob_store = mock_ob
    
    rows_b = engine_b.generate_features("BTCUSDT", _dt(2), _dt(5))
    
    assert len(rows_a) == len(rows_b)
    assert len(rows_a) > 0
    
    # Check strict equality of the JSON dumps
    for a, b in zip(rows_a, rows_b):
        assert a.model_dump_json() == b.model_dump_json()
