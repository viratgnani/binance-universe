"""
research_features/registry.py

Feature metadata registry for the Research Feature Layer V1.
"""

from __future__ import annotations

from research_features.models import FeatureMetadata

FEATURE_REGISTRY: dict[str, FeatureMetadata] = {
    # ------------------------------------------------------------------ #
    # Price / Return Features
    # ------------------------------------------------------------------ #
    "return_1m": FeatureMetadata(
        name="return_1m",
        version="v1",
        description="1-minute close-to-close return",
        source_dataset="OHLCV (1m)",
        lookback="1m",
        timestamp_semantics="closed candle",
        missing_data_policy="null",
    ),
    "return_5m": FeatureMetadata(
        name="return_5m",
        version="v1",
        description="5-minute close-to-close return",
        source_dataset="OHLCV (1m)",
        lookback="5m",
        timestamp_semantics="closed candle",
        missing_data_policy="null",
    ),
    "return_15m": FeatureMetadata(
        name="return_15m",
        version="v1",
        description="15-minute close-to-close return",
        source_dataset="OHLCV (1m)",
        lookback="15m",
        timestamp_semantics="closed candle",
        missing_data_policy="null",
    ),
    "return_1h": FeatureMetadata(
        name="return_1h",
        version="v1",
        description="1-hour close-to-close return",
        source_dataset="OHLCV (1m)",
        lookback="1h",
        timestamp_semantics="closed candle",
        missing_data_policy="null",
    ),

    # ------------------------------------------------------------------ #
    # Volatility / Range Features
    # ------------------------------------------------------------------ #
    "volatility_5m": FeatureMetadata(
        name="volatility_5m",
        version="v1",
        description="Realized volatility over the last 5 minutes (standard deviation of 1m returns)",
        source_dataset="OHLCV (1m)",
        lookback="5m",
        timestamp_semantics="closed candle",
        missing_data_policy="null",
    ),
    "volatility_15m": FeatureMetadata(
        name="volatility_15m",
        version="v1",
        description="Realized volatility over the last 15 minutes (standard deviation of 1m returns)",
        source_dataset="OHLCV (1m)",
        lookback="15m",
        timestamp_semantics="closed candle",
        missing_data_policy="null",
    ),
    "volatility_1h": FeatureMetadata(
        name="volatility_1h",
        version="v1",
        description="Realized volatility over the last 1 hour (standard deviation of 1m returns)",
        source_dataset="OHLCV (1m)",
        lookback="1h",
        timestamp_semantics="closed candle",
        missing_data_policy="null",
    ),
    "range_pct": FeatureMetadata(
        name="range_pct",
        version="v1",
        description="(high - low) / close over the current 1m candle",
        source_dataset="OHLCV (1m)",
        lookback="1m",
        timestamp_semantics="closed candle",
        missing_data_policy="null",
    ),

    # ------------------------------------------------------------------ #
    # Volume Features
    # ------------------------------------------------------------------ #
    "volume_1m": FeatureMetadata(
        name="volume_1m",
        version="v1",
        description="Volume over the last 1 minute",
        source_dataset="OHLCV (1m)",
        lookback="1m",
        timestamp_semantics="closed candle",
        missing_data_policy="null",
    ),
    "volume_5m": FeatureMetadata(
        name="volume_5m",
        version="v1",
        description="Volume over the last 5 minutes",
        source_dataset="OHLCV (1m)",
        lookback="5m",
        timestamp_semantics="closed candle",
        missing_data_policy="null",
    ),
    "volume_15m": FeatureMetadata(
        name="volume_15m",
        version="v1",
        description="Volume over the last 15 minutes",
        source_dataset="OHLCV (1m)",
        lookback="15m",
        timestamp_semantics="closed candle",
        missing_data_policy="null",
    ),
    "volume_1h": FeatureMetadata(
        name="volume_1h",
        version="v1",
        description="Volume over the last 1 hour",
        source_dataset="OHLCV (1m)",
        lookback="1h",
        timestamp_semantics="closed candle",
        missing_data_policy="null",
    ),
    "relative_volume": FeatureMetadata(
        name="relative_volume",
        version="v1",
        description="Current 1m volume divided by the rolling mean of the last 1h volume",
        source_dataset="OHLCV (1m)",
        lookback="1h",
        timestamp_semantics="closed candle",
        missing_data_policy="null",
    ),

    # ------------------------------------------------------------------ #
    # Trade-Derived Features
    # ------------------------------------------------------------------ #
    "trade_count": FeatureMetadata(
        name="trade_count",
        version="v1",
        description="Number of trades in the last 1 minute",
        source_dataset="Trades",
        lookback="1m",
        timestamp_semantics="trade.timestamp <= T",
        missing_data_policy="null",
    ),
    "total_trade_volume": FeatureMetadata(
        name="total_trade_volume",
        version="v1",
        description="Total volume of trades in the last 1 minute",
        source_dataset="Trades",
        lookback="1m",
        timestamp_semantics="trade.timestamp <= T",
        missing_data_policy="null",
    ),
    "total_trade_quote_volume": FeatureMetadata(
        name="total_trade_quote_volume",
        version="v1",
        description="Total quote volume of trades in the last 1 minute",
        source_dataset="Trades",
        lookback="1m",
        timestamp_semantics="trade.timestamp <= T",
        missing_data_policy="null",
    ),
    "average_trade_size": FeatureMetadata(
        name="average_trade_size",
        version="v1",
        description="Average trade size (volume / count) in the last 1 minute",
        source_dataset="Trades",
        lookback="1m",
        timestamp_semantics="trade.timestamp <= T",
        missing_data_policy="null",
    ),
    "median_trade_size": FeatureMetadata(
        name="median_trade_size",
        version="v1",
        description="Median trade size in the last 1 minute",
        source_dataset="Trades",
        lookback="1m",
        timestamp_semantics="trade.timestamp <= T",
        missing_data_policy="null",
    ),

    # ------------------------------------------------------------------ #
    # Order-Book Features
    # ------------------------------------------------------------------ #
    "spread": FeatureMetadata(
        name="spread",
        version="v1",
        description="best_ask - best_bid",
        source_dataset="Order Book Checkpoints",
        lookback="0",
        timestamp_semantics="last known checkpoint <= T",
        missing_data_policy="null",
    ),
    "spread_bps": FeatureMetadata(
        name="spread_bps",
        version="v1",
        description="Spread in basis points (spread / mid_price * 10000)",
        source_dataset="Order Book Checkpoints",
        lookback="0",
        timestamp_semantics="last known checkpoint <= T",
        missing_data_policy="null",
    ),
    "best_bid": FeatureMetadata(
        name="best_bid",
        version="v1",
        description="Highest bid price",
        source_dataset="Order Book Checkpoints",
        lookback="0",
        timestamp_semantics="last known checkpoint <= T",
        missing_data_policy="null",
    ),
    "best_ask": FeatureMetadata(
        name="best_ask",
        version="v1",
        description="Lowest ask price",
        source_dataset="Order Book Checkpoints",
        lookback="0",
        timestamp_semantics="last known checkpoint <= T",
        missing_data_policy="null",
    ),
    "mid_price": FeatureMetadata(
        name="mid_price",
        version="v1",
        description="(best_bid + best_ask) / 2",
        source_dataset="Order Book Checkpoints",
        lookback="0",
        timestamp_semantics="last known checkpoint <= T",
        missing_data_policy="null",
    ),
    "bid_depth_5": FeatureMetadata(
        name="bid_depth_5",
        version="v1",
        description="Total quantity at the top 5 bid levels",
        source_dataset="Order Book Checkpoints",
        lookback="0",
        timestamp_semantics="last known checkpoint <= T",
        missing_data_policy="null",
    ),
    "ask_depth_5": FeatureMetadata(
        name="ask_depth_5",
        version="v1",
        description="Total quantity at the top 5 ask levels",
        source_dataset="Order Book Checkpoints",
        lookback="0",
        timestamp_semantics="last known checkpoint <= T",
        missing_data_policy="null",
    ),
    "depth_imbalance_5": FeatureMetadata(
        name="depth_imbalance_5",
        version="v1",
        description="(bid_depth_5 - ask_depth_5) / (bid_depth_5 + ask_depth_5)",
        source_dataset="Order Book Checkpoints",
        lookback="0",
        timestamp_semantics="last known checkpoint <= T",
        missing_data_policy="null",
    ),
    "bid_depth_10": FeatureMetadata(
        name="bid_depth_10",
        version="v1",
        description="Total quantity at the top 10 bid levels",
        source_dataset="Order Book Checkpoints",
        lookback="0",
        timestamp_semantics="last known checkpoint <= T",
        missing_data_policy="null",
    ),
    "ask_depth_10": FeatureMetadata(
        name="ask_depth_10",
        version="v1",
        description="Total quantity at the top 10 ask levels",
        source_dataset="Order Book Checkpoints",
        lookback="0",
        timestamp_semantics="last known checkpoint <= T",
        missing_data_policy="null",
    ),
    "depth_imbalance_10": FeatureMetadata(
        name="depth_imbalance_10",
        version="v1",
        description="(bid_depth_10 - ask_depth_10) / (bid_depth_10 + ask_depth_10)",
        source_dataset="Order Book Checkpoints",
        lookback="0",
        timestamp_semantics="last known checkpoint <= T",
        missing_data_policy="null",
    ),
    "bid_depth_20": FeatureMetadata(
        name="bid_depth_20",
        version="v1",
        description="Total quantity at the top 20 bid levels",
        source_dataset="Order Book Checkpoints",
        lookback="0",
        timestamp_semantics="last known checkpoint <= T",
        missing_data_policy="null",
    ),
    "ask_depth_20": FeatureMetadata(
        name="ask_depth_20",
        version="v1",
        description="Total quantity at the top 20 ask levels",
        source_dataset="Order Book Checkpoints",
        lookback="0",
        timestamp_semantics="last known checkpoint <= T",
        missing_data_policy="null",
    ),
    "depth_imbalance_20": FeatureMetadata(
        name="depth_imbalance_20",
        version="v1",
        description="(bid_depth_20 - ask_depth_20) / (bid_depth_20 + ask_depth_20)",
        source_dataset="Order Book Checkpoints",
        lookback="0",
        timestamp_semantics="last known checkpoint <= T",
        missing_data_policy="null",
    ),
}
