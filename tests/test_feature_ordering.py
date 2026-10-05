import random
import pytest
from datetime import datetime, timezone, timedelta
from market_data.models import Candle, AggTrade
from research_features.calculators import (
    calculate_price_features,
    calculate_volatility_features,
    calculate_volume_features,
    calculate_trade_features
)


def _dt(offset_seconds: int) -> datetime:
    return datetime(2026, 8, 31, 12, 0, 0, tzinfo=timezone.utc) + timedelta(seconds=offset_seconds)

def _c(o: int) -> Candle:
    # offset corresponds to the open_time of a 1m candle
    open_t = _dt(o * 60)
    close_t = open_t + timedelta(minutes=1, milliseconds=-1)
    return Candle(
        symbol="BTCUSDT",
        interval="1m",
        open_time=open_t,
        close_time=close_t,
        open="100",
        high="105",
        low="95",
        close=str(100 + o),
        volume="10",
        quote_volume="1000",
        trade_count=100,
        taker_buy_base_vol="5",
        taker_buy_quote_vol="500"
    )

def _t(o: int, price: float = 100.0) -> AggTrade:
    return AggTrade(
        symbol="BTCUSDT",
        agg_trade_id=1000+o,
        price=str(price),
        quantity="1.0",
        quote_quantity=str(price * 1.0),
        first_trade_id=0,
        last_trade_id=0,
        timestamp=_dt(o),
        is_buyer_maker=False,
        buyer_is_maker=False
    )

@pytest.fixture
def base_candles():
    # 60 candles leading up to T=0 (from -60 to -1)
    return [_c(i) for i in range(-60, 0)]

@pytest.fixture
def base_trades():
    # 60 trades leading up to T=0 (from -60s to -1s)
    return [_t(i) for i in range(-60, 0)]

def test_input_ordering_determinism_candles(base_candles):
    T = _dt(0)
    
    # A. Ascending
    asc = list(base_candles)
    # B. Descending
    desc = list(reversed(asc))
    # C. Random shuffled
    shuffled = list(asc)
    random.seed(42)
    random.shuffle(shuffled)
    
    # Generate features
    f_asc_p = calculate_price_features(asc, T)
    f_desc_p = calculate_price_features(desc, T)
    f_shuff_p = calculate_price_features(shuffled, T)
    
    assert f_asc_p == f_desc_p
    assert f_asc_p == f_shuff_p
    
    f_asc_v = calculate_volatility_features(asc, T)
    f_desc_v = calculate_volatility_features(desc, T)
    f_shuff_v = calculate_volatility_features(shuffled, T)
    
    assert f_asc_v == f_desc_v
    assert f_asc_v == f_shuff_v

    f_asc_vol = calculate_volume_features(asc, T)
    f_desc_vol = calculate_volume_features(desc, T)
    f_shuff_vol = calculate_volume_features(shuffled, T)
    
    assert f_asc_vol == f_desc_vol
    assert f_asc_vol == f_shuff_vol
    
    # D. Multiple random permutations
    for i in range(5):
        perm = list(asc)
        random.shuffle(perm)
        assert calculate_price_features(perm, T) == f_asc_p
        assert calculate_volatility_features(perm, T) == f_asc_v
        assert calculate_volume_features(perm, T) == f_asc_vol

def test_input_ordering_determinism_trades(base_trades):
    T = _dt(0)
    
    # A. Ascending
    asc = list(base_trades)
    # B. Descending
    desc = list(reversed(asc))
    # C. Random shuffled
    shuffled = list(asc)
    random.seed(42)
    random.shuffle(shuffled)
    
    f_asc = calculate_trade_features(asc, T)
    f_desc = calculate_trade_features(desc, T)
    f_shuff = calculate_trade_features(shuffled, T)
    
    assert f_asc == f_desc
    assert f_asc == f_shuff
    
    # D. Multiple random permutations
    for i in range(5):
        perm = list(asc)
        random.shuffle(perm)
        assert calculate_trade_features(perm, T) == f_asc

def test_duplicates_handling(base_trades):
    # Duplicates in market data (same trade received twice upstream)
    # The current engine passes them raw. We want to ensure that given the SAME duplicated input,
    # order does not matter. We don't drop duplicates in calculators, so feature values will double (for volume).
    T = _dt(0)
    base = list(base_trades)
    base.append(base[-1]) # Duplicate the last trade
    
    asc = list(base)
    shuffled = list(base)
    random.seed(42)
    random.shuffle(shuffled)
    
    f_asc = calculate_trade_features(asc, T)
    f_shuff = calculate_trade_features(shuffled, T)
    
    assert f_asc == f_shuff
    # Documented behavior: Duplicate input causes duplicated accumulation because dedup is expected upstream
    # or the store idempotency handles it. The calculator simply processes what it is given deterministically.
    # base_trades = offset -60 to -1 seconds; cutoff = T - 1m = -60s (exclusive, t > cutoff).
    # Trade at -60s is excluded. Valid trades: -59s to -1s = 59 trades. With duplicate of last: 60.
    assert f_asc["trade_count"] == 60
