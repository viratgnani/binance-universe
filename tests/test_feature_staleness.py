import pytest
from unittest import mock
from datetime import datetime, timezone, timedelta
from research_features.engine import FeatureEngine
from market_data.ob_models import OrderBookCheckpoint
from pathlib import Path


def _dt(minute: int, second: int = 0) -> datetime:
    return datetime(2026, 8, 31, 12, 0, second, tzinfo=timezone.utc) + timedelta(minutes=minute)

def _ob(ts: datetime) -> str:
    c = OrderBookCheckpoint(
        symbol="BTCUSDT",
        last_update_id=1,
        exchange_event_time=ts,
        local_checkpoint_time=ts,
        synchronized=True,
        bids=[("100", "1")],
        asks=[("101", "1")]
    )
    return c.model_dump_json() + "\n"

@mock.patch("research_features.engine.OHLCVStore")
@mock.patch("research_features.engine.TradesStore")
@mock.patch("pathlib.Path.exists")
@mock.patch("pathlib.Path.glob")
def test_orderbook_staleness_boundary(mock_glob, mock_exists, mock_trades, mock_ohlcv):
    engine = FeatureEngine()
    engine._ohlcv_store = mock_ohlcv.return_value
    engine._trades_store = mock_trades.return_value
    mock_ohlcv.return_value.load.return_value = []
    mock_trades.return_value.load.return_value = []
    
    mock_exists.return_value = True
    # We yield one fake file
    mock_file = mock.MagicMock(spec=Path)
    mock_file.stem = "20260831"
    mock_glob.return_value = [mock_file]
    
    T = _dt(10) # 12:10:00
    
    # We want to test different staleness values relative to T (12:10:00)
    scenarios = [
        # description, checkpoint_time, expected_spread
        ("fresh", T - timedelta(seconds=1), 1.0),
        ("1m old", T - timedelta(minutes=1), 1.0),
        ("4m59s old", T - timedelta(minutes=4, seconds=59), 1.0),
        ("exactly 5m old", T - timedelta(minutes=5), 1.0), # 5 minutes is inclusive in the code <= 5m?
        ("5m1s old (stale)", T - timedelta(minutes=5, seconds=1), None),
        ("10m old (stale)", T - timedelta(minutes=10), None),
        ("1h old (stale)", T - timedelta(hours=1), None),
        ("48h old (stale)", T - timedelta(hours=48), None), # Won't even be loaded because of load_start filter, but if it was, None
        ("future book", T + timedelta(seconds=1), None), # Slicing prevents this
    ]
    
    for desc, cp_time, expected_spread in scenarios:
        # Patch the file open to yield our mock checkpoint
        file_content = _ob(cp_time)
        mock_file.open = mock.mock_open(read_data=file_content)
        
        # In engine, load_start is T - 65m. If cp_time is older than 65m, it is dropped by the loader.
        # Let's adjust T or expected_spread if cp_time < T - 65m
        if cp_time < T - timedelta(minutes=65):
            expected_spread = None
            
        rows = engine.generate_features("BTCUSDT", T, T)
        assert len(rows) == 1
        r = rows[0]
        
        assert r.spread == expected_spread, f"Failed scenario: {desc}. Expected {expected_spread}, got {r.spread}"


@mock.patch("research_features.engine.OHLCVStore")
@mock.patch("research_features.engine.TradesStore")
@mock.patch("pathlib.Path.exists")
@mock.patch("pathlib.Path.glob")
def test_staleness_lookahead_interaction(mock_glob, mock_exists, mock_trades, mock_ohlcv):
    engine = FeatureEngine()
    engine._ohlcv_store = mock_ohlcv.return_value
    engine._trades_store = mock_trades.return_value
    mock_ohlcv.return_value.load.return_value = []
    mock_trades.return_value.load.return_value = []
    
    mock_exists.return_value = True
    mock_file = mock.MagicMock(spec=Path)
    mock_file.stem = "20260831"
    mock_glob.return_value = [mock_file]
    
    T = _dt(10) # 12:10:00
    
    # 1. Old book (stale) + future book (look-ahead)
    content1 = _ob(T - timedelta(minutes=10)) + _ob(T + timedelta(seconds=1))
    mock_file.open = mock.mock_open(read_data=content1)
    rows1 = engine.generate_features("BTCUSDT", T, T)
    assert rows1[0].spread is None # Old is stale, future is ignored
    
    # 2. Valid book (-4m) + future extreme book (+1s)
    # The extreme book has 5 spread, valid has 1 spread
    c_valid = OrderBookCheckpoint(
        symbol="BTCUSDT", last_update_id=1, exchange_event_time=T - timedelta(minutes=4), local_checkpoint_time=T,
        synchronized=True, bids=[("100", "1")], asks=[("101", "1")] # spread = 1
    )
    c_future = OrderBookCheckpoint(
        symbol="BTCUSDT", last_update_id=2, exchange_event_time=T + timedelta(seconds=1), local_checkpoint_time=T,
        synchronized=True, bids=[("100", "1")], asks=[("105", "1")] # spread = 5
    )
    content2 = c_valid.model_dump_json() + "\n" + c_future.model_dump_json() + "\n"
    mock_file.open = mock.mock_open(read_data=content2)
    
    rows2 = engine.generate_features("BTCUSDT", T, T)
    r = rows2[0]
    
    assert r.spread == 1.0, "Future book incorrectly influenced the feature!"
    assert r.best_ask == 101.0
    
    # Check all depth metrics are calculated from valid book
    assert r.bid_depth_5 == 1.0
    assert r.ask_depth_5 == 1.0
    assert r.bid_depth_10 == 1.0
    assert r.ask_depth_20 == 1.0
    assert r.depth_imbalance_10 == 0.0
