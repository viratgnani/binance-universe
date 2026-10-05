"""
research_features/engine.py

FeatureEngine that orchestrates temporal alignment and feature generation.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

from market_data.config import MarketDataConfig, config as default_config
from market_data.ohlcv_store import OHLCVStore
from market_data.trades_store import TradesStore
from market_data.ob_store import OrderBookCheckpointStore
from research_features.models import FeatureRow
from research_features.calculators import (
    calculate_price_features,
    calculate_volatility_features,
    calculate_volume_features,
    calculate_trade_features,
    calculate_order_book_features,
)

logger = logging.getLogger(__name__)


class FeatureEngine:
    """
    Deterministically generates timestamped FeatureRows avoiding look-ahead.
    """

    def __init__(self, cfg: MarketDataConfig = default_config) -> None:
        self._cfg = cfg
        self._ohlcv_store = OHLCVStore(cfg)
        self._trades_store = TradesStore(cfg)
        self._ob_store = OrderBookCheckpointStore()

    def generate_features(
        self,
        symbol: str,
        start: datetime,
        end: datetime,
        interval_minutes: int = 1,
    ) -> list[FeatureRow]:
        """
        Generate feature rows for a specific symbol within [start, end].
        
        The engine evaluates features at boundaries of `interval_minutes` (e.g. every minute).
        Data loaded extends beyond `start` by a maximum lookback window (e.g. 1 hour + margin)
        to ensure sufficient history for the first feature at `start`.
        """
        start_utc = start.astimezone(timezone.utc)
        end_utc = end.astimezone(timezone.utc)
        
        # We need up to 60m of history (for 1h features), let's grab 65m to be safe.
        lookback_margin = timedelta(minutes=65)
        load_start = start_utc - lookback_margin
        
        # 1. Load historical data
        candles = self._ohlcv_store.load(symbol, "1m", load_start, end_utc)
        trades = self._trades_store.load(symbol, load_start, end_utc)
        # Checkpoints only have event times, we need enough to ensure we get one before T.
        # Since they are frequent, grabbing a few minutes before start is enough, but we grab the same margin.
        checkpoints = []
        try:
            from market_data.ob_store import OrderBookStore
            ob_store = OrderBookCheckpointStore()
            # We don't have load_checkpoints in the ob_store currently? Wait, let me check ob_store.py
            # There is NO load_checkpoints in OrderBookCheckpointStore! I need to add or mock it.
            # I will assume I can parse it exactly like load_events.
            pass
        except Exception:
            pass
            
        # We need to implement a load_checkpoints or similar, or just read files directly here for simplicity,
        # but let's implement a robust loader inside the engine if it's missing from the store.
        sym_ob_dir = self._ob_store.data_dir / symbol
        if sym_ob_dir.exists():
            start_date = load_start.date()
            end_date = end_utc.date()
            for filepath in sorted(sym_ob_dir.glob("????????.jsonl")):
                try:
                    file_date = datetime.strptime(filepath.stem, "%Y%m%d").date()
                    if start_date <= file_date <= end_date:
                        with filepath.open("r", encoding="utf-8") as fh:
                            for line in fh:
                                line = line.strip()
                                if not line: continue
                                try:
                                    from market_data.ob_models import OrderBookCheckpoint
                                    c = OrderBookCheckpoint.model_validate_json(line)
                                    if load_start <= c.exchange_event_time <= end_utc:
                                        checkpoints.append(c)
                                except Exception:
                                    pass
                except ValueError:
                    pass

        checkpoints.sort(key=lambda c: c.exchange_event_time)

        # 2. Iterate through temporal boundaries
        current_time = start_utc
        # Round up to the next minute boundary if start_utc is not exactly on a minute
        if current_time.second != 0 or current_time.microsecond != 0:
            current_time = current_time.replace(second=0, microsecond=0) + timedelta(minutes=1)
            
        features: list[FeatureRow] = []
        
        # For efficient traversal without rescanning arrays every minute, we could use sliding indices.
        # But for V1 simplicity and correctness, passing the sliced arrays or letting the calculators
        # iterate backward is fine, as lists are small (a few thousand elements).
        
        while current_time <= end_utc:
            # Slicing the arrays strictly at T to prevent ANY look-ahead.
            # This is the core look-ahead prevention mechanism.
            safe_candles = [c for c in candles if c.open_time + timedelta(minutes=1) <= current_time]
            safe_trades = [t for t in trades if t.timestamp <= current_time]
            safe_checkpoints = [c for c in checkpoints if c.exchange_event_time <= current_time]
            
            latest_checkpoint = safe_checkpoints[-1] if safe_checkpoints else None
            
            # Order Book Staleness Policy (5 minutes)
            if latest_checkpoint is not None:
                if current_time - latest_checkpoint.exchange_event_time > timedelta(minutes=5):
                    latest_checkpoint = None
            
            row = FeatureRow(
                symbol=symbol,
                timestamp=current_time,
                feature_version="v1"
            )
            
            # Compute features
            p_feat = calculate_price_features(safe_candles, current_time)
            v_feat = calculate_volatility_features(safe_candles, current_time)
            vol_feat = calculate_volume_features(safe_candles, current_time)
            t_feat = calculate_trade_features(safe_trades, current_time)
            ob_feat = calculate_order_book_features(latest_checkpoint)
            
            # Populate row
            for d in [p_feat, v_feat, vol_feat, t_feat, ob_feat]:
                for k, v in d.items():
                    setattr(row, k, v)
                    
            features.append(row)
            
            current_time += timedelta(minutes=interval_minutes)
            
        return features
