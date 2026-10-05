"""
research_discovery/feature_library.py

O(N) rolling implementations of market behavior features.
Computes features using only data available at or before T (strict causal correctness).
"""

from __future__ import annotations

import math
import statistics
from collections import deque
from datetime import datetime, timedelta
from typing import Optional

from market_data.models import Candle
from research_discovery.models import DiscoveryFeatureRow

# Time constants
ONE_MIN = timedelta(minutes=1)
ONE_HOUR = timedelta(hours=1)
ONE_DAY = timedelta(days=1)


class DiscoveryFeatureCalculator:
    """
    Computes DiscoveryFeatureRow from a chronological stream of Candles for a SINGLE symbol.
    Maintains internal state to achieve O(1) amortized complexity per candle.
    """

    def __init__(self) -> None:
        # History dictionary for exact timestamp lookups up to 24h
        self._candles: dict[datetime, Candle] = {}
        self._candle_times: deque[datetime] = deque()
        
        # Track 1-minute returns for volatility calculations
        self._returns_1m: dict[datetime, float] = {}
        
        # Track historical volatilities and volumes for contextual percentiles
        self._volatilities_1h_history: deque[float] = deque() # trailing 60 items
        self._volumes_1h_history: deque[float] = deque() # trailing 60 items

    def _prune(self, current_time: datetime) -> None:
        """Prune data older than 24h to keep memory footprint bounded."""
        cutoff_24h = current_time - ONE_DAY
        
        while self._candle_times and self._candle_times[0] < cutoff_24h:
            old_time = self._candle_times.popleft()
            self._candles.pop(old_time, None)
            self._returns_1m.pop(old_time, None)

    def _get_candle(self, t: datetime) -> Optional[Candle]:
        """Exact timestamp lookup."""
        return self._candles.get(t)

    def _get_return(self, t_current: datetime, minutes: int) -> Optional[float]:
        """Calculates close(T) / close(T - N) - 1. Strict timestamp lookup."""
        current = self._get_candle(t_current)
        past = self._get_candle(t_current - timedelta(minutes=minutes))
        if current and past and past.close > 0:
            return (current.close / past.close) - 1.0
        return None

    def _get_range(self, t_current: datetime, minutes: int) -> Optional[float]:
        """Calculates (rolling_high - rolling_low) / close(T)."""
        current = self._get_candle(t_current)
        if not current or current.close <= 0:
            return None
            
        highs = []
        lows = []
        # We need to collect exactly the past N minutes of candles.
        for i in range(minutes):
            c = self._get_candle(t_current - timedelta(minutes=i))
            if c is not None:
                highs.append(c.high)
                lows.append(c.low)
                
        # If we are missing any candle in the window, we still compute the range 
        # of the observed candles as long as we have at least one. But strictness 
        # might dictate returning None if the window is incomplete. 
        # Let's require the window to be mostly complete, or just use what we have.
        if not highs:
            return None
            
        return (max(highs) - min(lows)) / current.close

    def _get_volatility(self, t_current: datetime, minutes: int) -> Optional[float]:
        """Realized volatility: std deviation of 1m returns over the trailing N minutes."""
        rets = []
        for i in range(minutes):
            t = t_current - timedelta(minutes=i)
            r = self._returns_1m.get(t)
            if r is not None:
                rets.append(r)
        
        # We need at least 2 data points for standard deviation
        if len(rets) >= max(2, minutes // 2): # require at least 50% coverage
            return statistics.stdev(rets)
        return None

    def _get_volume(self, t_current: datetime, minutes: int) -> Optional[float]:
        """Sum of volume over the trailing N minutes."""
        vols = []
        for i in range(minutes):
            c = self._get_candle(t_current - timedelta(minutes=i))
            if c is not None:
                vols.append(c.volume)
                
        if vols:
            return sum(vols)
        return None

    def _calculate_percentile(self, value: float, history: deque[float]) -> Optional[float]:
        """Percentile rank of `value` within `history` (0.0 to 1.0)."""
        if not history:
            return None
        count_below = sum(1 for v in history if v < value)
        count_equal = sum(1 for v in history if v == value)
        # standard percentile rank formula handling ties
        return (count_below + 0.5 * count_equal) / len(history)

    def process_candle(self, c: Candle) -> DiscoveryFeatureRow:
        """
        Process a single new candle and return the computed DiscoveryFeatureRow.
        Candles must be fed chronologically.
        """
        t = c.open_time
        
        # Update state
        self._candles[t] = c
        self._candle_times.append(t)
        self._prune(t)
        
        row = DiscoveryFeatureRow(symbol=c.symbol, timestamp=t, close=c.close)
        
        # 1. Price/Return Features
        row.return_1m = self._get_return(t, 1)
        row.return_3m = self._get_return(t, 3)
        row.return_5m = self._get_return(t, 5)
        row.return_10m = self._get_return(t, 10)
        row.return_15m = self._get_return(t, 15)
        row.return_30m = self._get_return(t, 30)
        row.return_1h = self._get_return(t, 60)
        
        if row.return_1m is not None:
            self._returns_1m[t] = row.return_1m
            row.absolute_return_1m = abs(row.return_1m)
        if row.return_5m is not None:
            row.absolute_return_5m = abs(row.return_5m)
        if row.return_15m is not None:
            row.absolute_return_15m = abs(row.return_15m)

        # 2. Range Features
        row.range_1m = self._get_range(t, 1)
        row.range_5m = self._get_range(t, 5)
        row.range_15m = self._get_range(t, 15)
        row.range_30m = self._get_range(t, 30)
        row.range_1h = self._get_range(t, 60)

        # Distance from 24h high/low (max/min over past 1440 mins, EXCLUDING current candle)
        # Only compute if we have a reasonable amount of data (e.g. > 23 hours)
        if len(self._candles) > 1380: # 23 hours * 60
            # Filter out the current candle's timestamp (t)
            recent_24h_highs = [candle.high for ts, candle in self._candles.items() if ts != t]
            recent_24h_lows = [candle.low for ts, candle in self._candles.items() if ts != t]
            
            if recent_24h_highs and recent_24h_lows:
                max_24h = max(recent_24h_highs)
                min_24h = min(recent_24h_lows)
                
                if max_24h > 0:
                    row.distance_from_high_24h = (c.close / max_24h) - 1.0
                if min_24h > 0:
                    row.distance_from_low_24h = (c.close / min_24h) - 1.0

        # 3. Volatility Features
        row.volatility_5m = self._get_volatility(t, 5)
        row.volatility_15m = self._get_volatility(t, 15)
        row.volatility_30m = self._get_volatility(t, 30)
        row.volatility_1h = self._get_volatility(t, 60)
        
        if row.volatility_1h is not None:
            # Contextual percentile rank over trailing 60 values
            row.volatility_pct_rank_1h = self._calculate_percentile(row.volatility_1h, self._volatilities_1h_history)
            
            # Maintain 60-bar trailing window of 1h volatilities
            self._volatilities_1h_history.append(row.volatility_1h)
            if len(self._volatilities_1h_history) > 60:
                self._volatilities_1h_history.popleft()

        # 4. Volume Features
        row.volume_1m = c.volume
        row.volume_5m = self._get_volume(t, 5)
        row.volume_15m = self._get_volume(t, 15)
        row.volume_30m = self._get_volume(t, 30)
        row.volume_1h = self._get_volume(t, 60)

        # Maintain 60-bar trailing window of 1m volumes
        self._volumes_1h_history.append(c.volume)
        if len(self._volumes_1h_history) > 60:
            self._volumes_1h_history.popleft()

        row.volume_pct_rank_1h = self._calculate_percentile(c.volume, self._volumes_1h_history)
        
        if len(self._volumes_1h_history) > 0:
            median_vol_1h = statistics.median(self._volumes_1h_history)
            if median_vol_1h > 0:
                row.relative_volume_vs_1h = c.volume / median_vol_1h

        # 5. Candle Structure Features
        hl_range = c.high - c.low
        if hl_range > 0:
            row.body_pct = (c.close - c.open) / hl_range
            row.upper_wick_pct = (c.high - max(c.open, c.close)) / hl_range
            row.lower_wick_pct = (min(c.open, c.close) - c.low) / hl_range
            row.close_location = (c.close - c.low) / hl_range
        else:
            row.body_pct = 0.0
            row.upper_wick_pct = 0.0
            row.lower_wick_pct = 0.0
            row.close_location = 0.5 # mid point if flat
            
        row.is_bullish = 1.0 if c.close > c.open else 0.0
        row.is_bearish = 1.0 if c.close < c.open else 0.0

        return row
