# Research Feature Layer V1

## Overview

The Research Feature Layer transforms raw OHLCV, Trades, and Order Book data from Market Data V1 & V2 into a strictly versioned, explicitly timestamped, look-ahead-free feature dataset. This layer forms the foundation for all quantitative research and downstream modeling.

## Core Principles

1. **Deterministic Execution:** The same code processing the same historical data will always produce identical output JSONL feature rows.
2. **Strict Look-Ahead Prevention:** The core algorithm slices source arrays such that only data known strictly *before or exactly at* `T` is permitted into the feature row timestamped `T`. 
3. **Idempotency:** Generated feature files are strictly append-only JSONL files deduplicated by the composite key `(timestamp, feature_version)`.
4. **Transparency:** Every calculated metric maps cleanly to a `FeatureMetadata` registry outlining lookbacks and semantic boundaries.

## Architecture

* **`models.py`:** Pydantic models for `FeatureRow` and `FeatureMetadata`.
* **`registry.py`:** Hardcoded registry of all features.
* **`calculators.py`:** Functional mathematical implementations for computing metrics from strictly filtered historical slices.
* **`engine.py`:** The `FeatureEngine`, orchestrating data loading, precise temporal alignment boundaries, and generator loops.
* **`quality.py`:** Ex-post data validation guaranteeing bounding box constraints (e.g., return size, absence of negative volume, valid spreads).
* **`store.py`:** Handles IO for feature persistence (`data/features/{SYMBOL}/{YYYYMMDD}.jsonl`).

## Available Features (V1)

### Price & Returns
- `return_1m`, `return_5m`, `return_15m`, `return_1h`: Close-to-close returns.

### Volatility & Range
- `volatility_5m`, `volatility_15m`, `volatility_1h`: Realized volatility of 1m returns over the window.
- `range_pct`: Current candle High/Low range relative to Close.

### Volume
- `volume_1m`, `volume_5m`, `volume_15m`, `volume_1h`: Aggregated base volume.
- `relative_volume`: Current 1m volume / 1h rolling mean.

### Trade Features
- `trade_count`, `total_trade_volume`, `total_trade_quote_volume`
- `average_trade_size`, `median_trade_size`

### Order Book (Microstructure)
- `spread`, `spread_bps`, `mid_price`, `best_bid`, `best_ask`
- `bid_depth_5`, `ask_depth_5`, `bid_depth_10`, `ask_depth_10`, `bid_depth_20`, `ask_depth_20`
- `depth_imbalance_5`, `depth_imbalance_10`, `depth_imbalance_20`

## Look-Ahead Mechanics

A `FeatureRow` generated for `T` mathematically isolates historical inputs:
- Candles must fully close (`open_time + interval <= T`).
- Trades must execute strictly at or before `T` (`timestamp <= T`).
- Order Book Checkpoints must have an exchange sequence event time at or before `T` (`exchange_event_time <= T`).

This guarantees that an ML model trained on `FeatureRow(T)` uses data that would have been unconditionally known natively at that exact microsecond.

## Order Book Staleness Policy

The engine enforces a **5-minute maximum staleness threshold** for order book data.

For each feature timestamp `T`:
- The latest available `OrderBookCheckpoint` with `exchange_event_time <= T` is identified.
- If `T - checkpoint.exchange_event_time > 5 minutes`, the checkpoint is discarded.
- A discarded or absent checkpoint causes all 14 order-book features to be explicitly `null`.

**Boundary:** The threshold is exclusive — a checkpoint exactly 5 minutes old is still valid. A checkpoint at `T - 5m - 1s` is stale and yields `null`.

This prevents silently consuming stale microstructure data as though it were current.

## Chronological Input Normalization

All calculator functions internally sort their input arrays before processing:

- `calculate_price_features`, `calculate_volatility_features`, `calculate_volume_features`: candles sorted by `open_time` ascending.
- `calculate_trade_features`: trades sorted by `timestamp` ascending.

This means the calculators are robust to out-of-order API responses, reversed inputs, or shuffled arrays — they always produce the same output for logically identical datasets.

## Historical Universe Snapshot Selection

When using `--symbols universe` for historical feature generation, the CLI resolves the correct historical snapshot to avoid survivorship bias:

1. All universe snapshot files are enumerated from the `SnapshotRepository`.
2. The latest snapshot whose date is **≤ the requested start date** is selected.
3. If no snapshot precedes the start date, the earliest available snapshot is used (with a warning).
4. Explicit `--symbols BTCUSDT,ETHUSDT` bypasses this lookup entirely.

This ensures historical backfills reflect the universe membership as it existed at the time, not the current state.

## Feature Registry

Every feature output by the calculators is registered in `FEATURE_REGISTRY` (`research_features/registry.py`), providing a machine-readable catalogue of:
- Name and version
- Description
- Source dataset
- Lookback window
- Timestamp semantics
- Missing-data policy

The registry, Pydantic `FeatureRow` schema, and calculator outputs are maintained in strict bidirectional consistency — no orphaned features and no undocumented outputs.

## Freeze Status

**Research Feature Layer V1 is FROZEN as of 2026-09-08.**

- 429/429 tests passing
- All adversarial correctness checks passed
- Idempotency and reproducibility verified
- Live 5-symbol, 1-hour validation passed with 0 violations
