"""
research_discovery/feature_engine.py

Pipeline for computing discovery features from OHLCV data.
Operates on a per-symbol basis, streaming data chronologically in a single pass.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone

from market_data.config import MarketDataConfig, config as default_config
from market_data.models import Dataset
from market_data.ohlcv_store import OHLCVStore
from research_discovery.feature_library import DiscoveryFeatureCalculator
from research_discovery.feature_store import DiscoveryFeatureStore
from research_discovery.models import DiscoveryFeatureRow

logger = logging.getLogger(__name__)


class DiscoveryFeatureEngine:
    """
    Computes discovery features by streaming OHLCV data sequentially.
    """

    def __init__(self, cfg: MarketDataConfig = default_config) -> None:
        self.ohlcv_store = OHLCVStore(cfg)
        self.feature_store = DiscoveryFeatureStore(cfg)

    def process_symbol(self, symbol: str, start: datetime, end: datetime, batch_size: int = 10000) -> tuple[int, int]:
        """
        Process features for a single symbol within the given time range.
        Saves features in batches to limit memory usage.
        
        Returns:
            (total_written, total_skipped)
        """
        logger.info("DiscoveryFeatureEngine: Processing %s from %s to %s", symbol, start, end)
        
        # Load candles chronologically
        candles = self.ohlcv_store.load(
            symbol=symbol,
            interval="1m",
            start=start,
            end=end
        )
        
        if not candles:
            logger.warning("DiscoveryFeatureEngine: No candles found for %s in requested range.", symbol)
            return 0, 0
            
        # Ensure chronological ordering (frozen OHLCV store guarantees this, but double check)
        candles.sort(key=lambda c: c.open_time)
        
        calculator = DiscoveryFeatureCalculator()
        
        total_written = 0
        total_skipped = 0
        
        batch: list[DiscoveryFeatureRow] = []
        
        for c in candles:
            row = calculator.process_candle(c)
            batch.append(row)
            
            if len(batch) >= batch_size:
                w, s = self.feature_store.save(batch)
                total_written += w
                total_skipped += s
                batch = []
                
        # Save any remaining rows in the final batch
        if batch:
            w, s = self.feature_store.save(batch)
            total_written += w
            total_skipped += s
            
        logger.info(
            "DiscoveryFeatureEngine: Finished %s. Written: %d, Skipped: %d", 
            symbol, total_written, total_skipped
        )
        return total_written, total_skipped
