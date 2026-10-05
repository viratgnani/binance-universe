"""
tests/test_discovery_feature_engine.py
"""

from datetime import datetime, timedelta, timezone
from pathlib import Path
import pytest
from unittest.mock import patch, MagicMock

from market_data.models import Candle
from research_discovery.feature_engine import DiscoveryFeatureEngine
from research_discovery.models import DiscoveryFeatureRow

def make_candle(t: datetime, open_p: float, high: float, low: float, close: float, vol: float = 100.0) -> Candle:
    return Candle(
        symbol="TEST",
        interval="1m",
        open_time=t,
        close_time=t + timedelta(minutes=1) - timedelta(milliseconds=1),
        open=open_p,
        high=high,
        low=low,
        close=close,
        volume=vol,
        quote_volume=vol * close,
        trade_count=10,
        taker_buy_base_vol=vol/2,
        taker_buy_quote_vol=(vol/2)*close,
    )

@patch("research_discovery.feature_engine.OHLCVStore")
@patch("research_discovery.feature_engine.DiscoveryFeatureStore")
def test_feature_engine_process_symbol(mock_feature_store_cls, mock_ohlcv_store_cls):
    mock_ohlcv = MagicMock()
    mock_feature = MagicMock()
    mock_ohlcv_store_cls.return_value = mock_ohlcv
    mock_feature_store_cls.return_value = mock_feature
    
    t0 = datetime(2025, 1, 1, 0, 0, tzinfo=timezone.utc)
    candles = [make_candle(t0 + timedelta(minutes=i), 100, 100, 100, 100) for i in range(50)]
    
    mock_ohlcv.load.return_value = candles
    mock_feature.save.side_effect = lambda batch: (len(batch), 0)
    
    engine = DiscoveryFeatureEngine()
    w, s = engine.process_symbol("TEST", t0, t0 + timedelta(minutes=50), batch_size=20)
    
    assert w == 50
    assert s == 0
    
    # 50 candles, batch_size=20 -> 3 save calls
    assert mock_feature.save.call_count == 3
    
    # Check the args of the first save call
    first_call_args = mock_feature.save.call_args_list[0][0][0]
    assert len(first_call_args) == 20
    assert isinstance(first_call_args[0], DiscoveryFeatureRow)
    assert first_call_args[0].symbol == "TEST"
    assert first_call_args[0].timestamp == t0
    assert first_call_args[0].close == 100.0
