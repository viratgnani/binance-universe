# Market Behavior Discovery Laboratory

## Overview
The **Market Behavior Discovery Laboratory** (`research_discovery/`) is an overlay framework designed to define market events and measure what statistically happens afterward. It runs exclusively on the frozen `ResearchEngine` architecture without modifying it.

## Architecture

1. **Feature Library (`feature_library.py`)**: Computes lightweight OHLCV features (returns, volatility, relative volume) using O(N) streaming algorithms. Ensures strict causal correctness (features at time T only use data $\le T$).
2. **Feature Store (`feature_store.py`)**: Stores `DiscoveryFeatureRow`s efficiently in JSONL format, independent of the frozen O(N²) `FeatureStore`.
3. **Event Primitives (`event_definitions.py`)**: Provides factory functions that emit frozen `EventDefinition` objects. These standard primitives form the semantic vocabulary of the lab (e.g., `price_move_up`, `volume_shock`, `breakout`).
4. **Outcome Definitions (`outcome_definitions.py`)**: Standardizes forward return measurements. The discovery layer standardizes on `close` terminology, which the Data Adapter translates to the frozen engine's expectations.
5. **Experiment Registry (`experiment_registry.py`)**: Catalogs every study before execution, tracking whether it is exploratory or confirmatory to guard against multiple-testing amnesia.
6. **Data Adapter (`data_adapter.py`)**: Implements the frozen `DataAdapter` interface, mapping `mid_price` requests to discovery `close` and serving feature series directly to the engine.
7. **Discovery Runner (`discovery_runner.py`)**: Wraps the frozen `ResearchRunner`, orchestrating the pipeline from registry to statistics.

## Feature Catalog

- **Price/Return**: `return_Nm` = `close(T) / close(T - N) - 1`. `absolute_return_Nm` = `abs(return_Nm)`. (1m, 3m, 5m, 10m, 15m, 30m, 1h).
- **Range**: `range_Nm` = `(rolling_high - rolling_low) / rolling_close`. Distance features map exactly against the trailing 24h extreme (excluding current candle).
- **Volatility**: `volatility_Nm` = standard deviation of 1m returns over N minutes. `volatility_pct_rank_1h` = contextual percentile rank within trailing 1h window.
- **Volume**: `volume_Nm` = direct sums. `relative_volume_vs_1h` = `volume_1m / median(last 60m volume)`. `volume_pct_rank_1h` = contextual percentile rank.
- **Candle Structure**: `body_pct`, `upper_wick_pct`, `lower_wick_pct`, `close_location`, `is_bullish`, `is_bearish`.

## Methodological Guardrails

- **Exploratory vs Confirmatory**: Every experiment must declare its status.
- **Strict Timestamps**: Gaps are respected. We use timestamp lookbacks, not array offsets.
- **No Interpolation**: Missing data emits `None` and skips the observation.
- **Causal Guarantee**: The pipeline mathematically cannot look ahead.
