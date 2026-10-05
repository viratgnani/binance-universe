# Market Behavior Discovery Laboratory

A rigorous quantitative research layer built on top of the frozen infrastructure.

## Core Philosophy

We are building a **Discovery Lab**, not a strategy generator.
The goal is to define specific market events (e.g., "volume shock", "price breakout") and measure what statistically happens afterward across a universe of assets.

## Architecture

This package (`research_discovery`) sits cleanly above all frozen layers:
- `universe/`
- `market_data/`
- `research_features/`
- `research/`
- `indicators/`

**Zero modifications are made to the frozen stack.**

## Features

- **O(N) Streaming Features**: Calculates returns, volatility, volume relative percentiles, and ranges in a single chronological pass.
- **Strict Causal Correctness**: Features computed at timestamp $T$ only ever use data $\le T$.
- **Experiment Registry**: Prevents multiple-testing amnesia by cataloging experiments with explicit `is_exploratory` flags before execution.
- **Thin Orchestration**: Wraps the frozen `ResearchRunner` and injects discovery-specific data adapters.

## Usage

Generate features for a universe:
```bash
python -m research_discovery feature-generate --symbols BTCUSDT,ETHUSDT --start 2024-09-01T00:00:00Z --end 2025-09-01T00:00:00Z --workers 8
```

Check feature status:
```bash
python -m research_discovery feature-status --start 2024-09-01T00:00:00Z --end 2025-09-01T00:00:00Z
```

List registry:
```bash
python -m research_discovery list
```
