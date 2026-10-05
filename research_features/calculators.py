"""
research_features/calculators.py

Calculators for research features based on strictly aligned historical data.
"""

from __future__ import annotations

import math
from datetime import datetime, timedelta

from market_data.models import Candle, AggTrade
from market_data.ob_models import OrderBookCheckpoint


def _get_candle_at_offset(candles: list[Candle], current_time: datetime, offset_minutes: int) -> Candle | None:
    """
    Get the most recent closed candle that is at least `offset_minutes` old relative to current_time.
    For a 1m offset, we look for a candle whose open_time + 1m <= current_time, which means
    it was fully closed and available at or before current_time.
    """
    target_close_time_max = current_time - timedelta(minutes=offset_minutes)
    
    # We iterate backwards through sorted candles
    for c in reversed(candles):
        # Assuming 1m candles for now based on feature definitions.
        # Candle close time is open_time + 1 minute (or 60 seconds).
        candle_close_time = c.open_time + timedelta(minutes=1)
        if candle_close_time <= target_close_time_max:
            return c
    return None


def calculate_price_features(candles: list[Candle], current_time: datetime) -> dict[str, float | None]:
    """
    Calculates:
    - return_1m
    - return_5m
    - return_15m
    - return_1h
    
    All returns are close-to-close based on 1m candles.
    """
    # Enforce chronological ordering
    candles = sorted(candles, key=lambda c: c.open_time)
    
    features: dict[str, float | None] = {
        "return_1m": None,
        "return_5m": None,
        "return_15m": None,
        "return_1h": None,
    }
    
    current_candle = _get_candle_at_offset(candles, current_time, 0)
    if not current_candle:
        return features
        
    current_close = float(current_candle.close)
    
    for offset, feature_name in [(1, "return_1m"), (5, "return_5m"), (15, "return_15m"), (60, "return_1h")]:
        prev_candle = _get_candle_at_offset(candles, current_time, offset)
        if prev_candle and float(prev_candle.close) != 0:
            features[feature_name] = (current_close - float(prev_candle.close)) / float(prev_candle.close)

    return features


def calculate_volatility_features(candles: list[Candle], current_time: datetime) -> dict[str, float | None]:
    """
    Calculates:
    - volatility_5m
    - volatility_15m
    - volatility_1h
    - range_pct
    """
    # Enforce chronological ordering
    candles = sorted(candles, key=lambda c: c.open_time)
    
    features: dict[str, float | None] = {
        "volatility_5m": None,
        "volatility_15m": None,
        "volatility_1h": None,
        "range_pct": None,
    }
    
    current_candle = _get_candle_at_offset(candles, current_time, 0)
    if current_candle and float(current_candle.close) != 0:
        h = float(current_candle.high)
        l = float(current_candle.low)
        c = float(current_candle.close)
        features["range_pct"] = (h - l) / c
        
    # Calculate realized volatility over windows
    for window, feature_name in [(5, "volatility_5m"), (15, "volatility_15m"), (60, "volatility_1h")]:
        # We need `window` returns. This requires `window + 1` candles.
        # Find all candles closed within the last `window` minutes, plus 1 before that to form the first return.
        window_start_close_time = current_time - timedelta(minutes=window)
        
        # Extract valid consecutive 1m returns
        returns = []
        
        # Iterate backwards to collect the last N candles
        window_candles = []
        for c in reversed(candles):
            if c.open_time + timedelta(minutes=1) <= current_time:
                window_candles.append(c)
                if len(window_candles) == window + 1:
                    break
                    
        window_candles.reverse()  # chronological order
        
        # Check if we actually have enough history
        # (We strictly require window+1 consecutive candles? Let's just calculate from available consecutive pairs in the window).
        # Actually, for quantitative integrity, if we ask for 60m volatility, we shouldn't calculate it if we only have 2 candles.
        # We will strictly require that we have at least `window` candles in the lookback period, AND the earliest candle is ~window minutes ago.
        if len(window_candles) < window + 1:
            continue
            
        # Calculate returns
        valid_returns = True
        for i in range(1, len(window_candles)):
            c_prev = window_candles[i-1]
            c_curr = window_candles[i]
            
            # Check consecutive (1 minute apart)
            if c_curr.open_time - c_prev.open_time != timedelta(minutes=1):
                valid_returns = False
                break
                
            prev_close = float(c_prev.close)
            if prev_close == 0:
                valid_returns = False
                break
                
            ret = (float(c_curr.close) - prev_close) / prev_close
            returns.append(ret)
            
        if valid_returns and len(returns) == window:
            mean_ret = sum(returns) / len(returns)
            variance = sum((r - mean_ret) ** 2 for r in returns) / len(returns)
            features[feature_name] = math.sqrt(variance)

    return features


def calculate_volume_features(candles: list[Candle], current_time: datetime) -> dict[str, float | None]:
    """
    Calculates:
    - volume_1m
    - volume_5m
    - volume_15m
    - volume_1h
    - relative_volume
    """
    features: dict[str, float | None] = {
        "volume_1m": None,
        "volume_5m": None,
        "volume_15m": None,
        "volume_1h": None,
        "relative_volume": None,
    }
    
    # Enforce chronological ordering
    candles = sorted(candles, key=lambda c: c.open_time)
    
    # We sum volumes for candles that closed strictly within (current_time - offset, current_time]
    for window, feature_name in [(1, "volume_1m"), (5, "volume_5m"), (15, "volume_15m"), (60, "volume_1h")]:
        cutoff = current_time - timedelta(minutes=window)
        window_vol = 0.0
        candle_count = 0
        
        for c in reversed(candles):
            c_close = c.open_time + timedelta(minutes=1)
            if c_close <= cutoff:
                break
            if c_close <= current_time:
                window_vol += float(c.volume)
                candle_count += 1
                
        # If we expect 60 candles but only have 50, it's missing data. We strictly require all candles?
        # For volume, missing candles might mean 0 volume, but Binance provides candles even for 0 volume generally.
        # If the gap is huge, the data is invalid. We will enforce that we have exactly `window` candles.
        if candle_count == window:
            features[feature_name] = window_vol
            
    # relative_volume = current 1m volume / (average 1m volume over last 1h)
    vol_1m = features["volume_1m"]
    vol_1h = features["volume_1h"]
    
    if vol_1m is not None and vol_1h is not None and vol_1h > 0:
        mean_1h_vol = vol_1h / 60.0
        if mean_1h_vol > 0:
            features["relative_volume"] = vol_1m / mean_1h_vol

    return features


def calculate_trade_features(trades: list[AggTrade], current_time: datetime) -> dict[str, float | None]:
    """
    Calculates:
    - trade_count
    - total_trade_volume
    - total_trade_quote_volume
    - average_trade_size
    - median_trade_size
    
    Trades must satisfy: timestamp > current_time - 1m AND timestamp <= current_time
    """
    features: dict[str, float | None] = {
        "trade_count": None,
        "total_trade_volume": None,
        "total_trade_quote_volume": None,
        "average_trade_size": None,
        "median_trade_size": None,
    }
    
    cutoff = current_time - timedelta(minutes=1)
    
    # Enforce chronological ordering
    trades = sorted(trades, key=lambda t: t.timestamp)
    
    window_trades = []
    # Trades are sorted by timestamp ascending
    # We iterate backwards to efficiently grab the last 1m of trades.
    for t in reversed(trades):
        if t.timestamp > current_time:
            # Look-ahead violation if this happens, but the engine should prevent passing future trades.
            continue
        if t.timestamp <= cutoff:
            break
        window_trades.append(t)
        
    if not window_trades:
        # If no trades happened in the minute, return 0 for additive features, missing for averages
        features["trade_count"] = 0
        features["total_trade_volume"] = 0.0
        features["total_trade_quote_volume"] = 0.0
        return features
        
    features["trade_count"] = len(window_trades)
    
    vols = [float(t.quantity) for t in window_trades]
    qvols = [float(t.quantity) * float(t.price) for t in window_trades]
    
    total_vol = sum(vols)
    features["total_trade_volume"] = total_vol
    features["total_trade_quote_volume"] = sum(qvols)
    
    features["average_trade_size"] = total_vol / len(vols)
    
    vols.sort()
    n = len(vols)
    if n % 2 == 1:
        features["median_trade_size"] = vols[n // 2]
    else:
        features["median_trade_size"] = (vols[n // 2 - 1] + vols[n // 2]) / 2.0
        
    return features


def calculate_order_book_features(checkpoint: OrderBookCheckpoint | None) -> dict[str, float | None]:
    """
    Calculates:
    - spread
    - spread_bps
    - best_bid
    - best_ask
    - mid_price
    - bid_depth_5/10/20
    - ask_depth_5/10/20
    - depth_imbalance_5/10/20
    """
    features: dict[str, float | None] = {
        "spread": None,
        "spread_bps": None,
        "best_bid": None,
        "best_ask": None,
        "mid_price": None,
        "bid_depth_5": None,
        "ask_depth_5": None,
        "bid_depth_10": None,
        "ask_depth_10": None,
        "bid_depth_20": None,
        "ask_depth_20": None,
        "depth_imbalance_5": None,
        "depth_imbalance_10": None,
        "depth_imbalance_20": None,
    }
    
    if not checkpoint:
        return features
        
    if not checkpoint.bids or not checkpoint.asks:
        return features
        
    best_bid = float(checkpoint.bids[0][0])
    best_ask = float(checkpoint.asks[0][0])
    
    if best_bid >= best_ask:
        # Crossed book, invalid state
        return features
        
    features["best_bid"] = best_bid
    features["best_ask"] = best_ask
    
    spread = best_ask - best_bid
    mid_price = (best_bid + best_ask) / 2.0
    
    features["spread"] = spread
    features["mid_price"] = mid_price
    if mid_price > 0:
        features["spread_bps"] = (spread / mid_price) * 10000.0
        
    bids = checkpoint.bids
    asks = checkpoint.asks
    
    for levels, b_feat, a_feat, i_feat in [
        (5, "bid_depth_5", "ask_depth_5", "depth_imbalance_5"),
        (10, "bid_depth_10", "ask_depth_10", "depth_imbalance_10"),
        (20, "bid_depth_20", "ask_depth_20", "depth_imbalance_20"),
    ]:
        bid_depth = sum(float(qty) for price, qty in bids[:levels])
        ask_depth = sum(float(qty) for price, qty in asks[:levels])
        
        # Only populate if we have enough levels? Or just use whatever we have.
        # We will populate what we have, but if it's 0 it's probably missing.
        features[b_feat] = bid_depth
        features[a_feat] = ask_depth
        
        total_depth = bid_depth + ask_depth
        if total_depth > 0:
            features[i_feat] = (bid_depth - ask_depth) / total_depth
            
    return features
