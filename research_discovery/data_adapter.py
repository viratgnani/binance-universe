"""
research_discovery/data_adapter.py

DiscoveryDataAdapter — provides discovery feature data to the frozen ResearchEngine.

Wraps DiscoveryFeatureStore. Maps frozen engine requests for `mid_price`
to the discovery `close` feature.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from pathlib import Path

from market_data.config import MarketDataConfig, config as default_config
from research_discovery.feature_store import DiscoveryFeatureStore
from research_discovery.models import DiscoveryFeatureRow

logger = logging.getLogger(__name__)

TimestampedSeries = list[tuple[datetime, float | None]]


class DiscoveryDataAdapter:
    """
    Adapter over the DiscoveryFeatureStore.
    Implements the same interface as ResearchDataAdapter to be injected into
    the frozen ResearchRunner.
    """

    def __init__(self, cfg: MarketDataConfig = default_config) -> None:
        self._store = DiscoveryFeatureStore(cfg)
        self._features_dir = self._store.data_dir

    def get_feature_series(
        self,
        symbol: str,
        feature_name: str,
        start: datetime,
        end: datetime,
    ) -> TimestampedSeries:
        """
        Return a list of (timestamp, value) pairs for *feature_name*.
        """
        rows = self._load_rows(symbol, start, end)
        result: TimestampedSeries = []
        for row in rows:
            val = getattr(row, feature_name, None)
            if isinstance(val, int):
                val = float(val)
            result.append((row.timestamp, val))
        return result

    def get_price_series(
        self,
        symbol: str,
        price_feature: str,
        start: datetime,
        end: datetime,
    ) -> TimestampedSeries:
        """
        Return a list of (timestamp, price) pairs.
        Explicit mapping: if the frozen engine asks for 'mid_price' (its default),
        we intercept and return 'close' from the discovery store.
        """
        # Map legacy frozen 'mid_price' to discovery 'close' terminology
        if price_feature == "mid_price":
            price_feature = "close"
            
        return self.get_feature_series(symbol, price_feature, start, end)

    def get_indicator_series(
        self,
        symbol: str,
        indicator_name: str,
        indicator_version: str,
        parameter_hash: str,
        start: datetime,
        end: datetime,
    ) -> TimestampedSeries:
        """
        Discovery Layer currently does not use the frozen Indicator Layer (RSI).
        We return empty here, or we could wrap the real IndicatorStore if needed.
        """
        logger.warning("get_indicator_series called on DiscoveryDataAdapter - returning empty.")
        return []

    def get_available_symbols(
        self,
        start: datetime,
        end: datetime,
    ) -> list[str]:
        """
        Return symbols that have discovery features.
        """
        if not self._features_dir.exists():
            return []

        symbols: list[str] = []
        for sym_dir in sorted(self._features_dir.iterdir()):
            if not sym_dir.is_dir():
                continue
            symbol = sym_dir.name
            rows = self._load_rows(symbol, start, end)
            if rows:
                symbols.append(symbol)
        return symbols

    def _load_rows(
        self,
        symbol: str,
        start: datetime,
        end: datetime,
    ) -> list[DiscoveryFeatureRow]:
        """Load DiscoveryFeatureRows from the store."""
        start_utc = start.astimezone(timezone.utc)
        end_utc   = end.astimezone(timezone.utc)
        rows = self._store.load(symbol, start_utc, end_utc)
        return rows
