"""
research/data_adapter.py

ResearchDataAdapter — provides stored historical data to the research engine.

Responsibilities
----------------
- Read FeatureRow data from the frozen Feature Layer V1 store.
- Expose clean typed series to the event and outcome engines.
- Never call Binance directly.
- Preserve timestamps exactly as stored.

Data access methods
-------------------
  get_feature_series(symbol, feature_name, start, end)
      -> list[tuple[datetime, float | None]]

  get_price_series(symbol, price_feature, start, end)
      -> list[tuple[datetime, float | None]]

  get_available_symbols(start, end)
      -> list[str]
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from pathlib import Path

from market_data.config import MarketDataConfig, config as default_config
from research_features.models import FeatureRow
from research_features.store import FeatureStore
from indicators.store import IndicatorStore

logger = logging.getLogger(__name__)

# Type alias for a timestamped scalar series
TimestampedSeries = list[tuple[datetime, float | None]]


class ResearchDataAdapter:
    """
    Read-only adapter over the frozen Feature Layer V1 store.

    All timestamps are returned in UTC and sorted ascending.
    Missing feature values are preserved as None — never filled or interpolated.
    """

    def __init__(self, cfg: MarketDataConfig = default_config) -> None:
        self._store = FeatureStore(cfg)
        self._indicator_store = IndicatorStore(cfg)
        self._features_dir = Path(cfg.OHLCV_DIR).parent / "features"

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def get_feature_series(
        self,
        symbol: str,
        feature_name: str,
        start: datetime,
        end: datetime,
    ) -> TimestampedSeries:
        """
        Return a list of (timestamp, value) pairs for *feature_name* on *symbol*
        with timestamp in [start, end], sorted ascending.

        Missing feature values (None in the stored FeatureRow) are returned as None.
        No interpolation or filling is performed.
        """
        rows = self._load_rows(symbol, start, end)
        result: TimestampedSeries = []
        for row in rows:
            val = getattr(row, feature_name, None)
            # Coerce int to float for uniformity (e.g. trade_count)
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
        Return a list of (timestamp, price) pairs, identical API to get_feature_series.

        Price features are numeric FeatureRow fields (e.g. "mid_price", "best_bid").
        None values are preserved as None.
        """
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
        Return a list of (timestamp, value) pairs from the IndicatorStore.
        Filters explicitly by indicator_name, version, and exact parameter_hash.
        Missing values (e.g. during warm-up) are returned as None.
        """
        start_utc = start.astimezone(timezone.utc)
        end_utc   = end.astimezone(timezone.utc)
        
        # Load raw IndicatorValues from JSONL
        indicator_values = self._indicator_store.load(symbol, start_utc, end_utc)
        
        result: TimestampedSeries = []
        for v in indicator_values:
            # Filter strictly to the desired calculation identity
            if v.indicator_name != indicator_name:
                continue
            if v.indicator_version != indicator_version:
                continue
            if v.parameter_hash != parameter_hash:
                continue
                
            # Must fall strictly in the requested window
            if start_utc <= v.timestamp <= end_utc:
                result.append((v.timestamp, v.value))
                
        # Defensive sort (IndicatorStore already sorts, but enforcing the API contract)
        result.sort(key=lambda x: x[0])
        return result

    def get_available_symbols(
        self,
        start: datetime,
        end: datetime,
    ) -> list[str]:
        """
        Return the list of symbols that have at least one stored FeatureRow
        with timestamp in [start, end].
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

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _load_rows(
        self,
        symbol: str,
        start: datetime,
        end: datetime,
    ) -> list[FeatureRow]:
        """Load FeatureRows from the store, UTC-normalised and sorted ascending."""
        start_utc = start.astimezone(timezone.utc)
        end_utc   = end.astimezone(timezone.utc)
        rows = self._store.load(symbol, start_utc, end_utc)
        # store.load already sorts ascending — defensive re-sort here is cheap
        rows.sort(key=lambda r: r.timestamp)
        return rows
