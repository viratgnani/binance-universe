# Binance Crypto Perpetual Universe Engine — V1

A clean, extensible foundation for crypto quantitative research.

This module discovers and maintains the **complete universe of Binance USDS-M
perpetual futures contracts**, ranks them by market quality, and persists
timestamped snapshots for historical analysis.

---

## What it does

1. **Discovers** all Binance perpetual futures via the public API.
2. **Filters** to crypto-only contracts — excludes tokenized stocks, ETFs,
   index products, and any other non-crypto underlyings.
3. **Collects** 24h volume, open interest, and bid/ask spread for every eligible contract.
4. **Ranks** all contracts by a configurable weighted liquidity score.
5. **Selects** the top 100 as `ACTIVE_TOP_100`; the rest become `WATCHLIST`.
6. **Persists** an append-only JSONL snapshot so rank history is fully auditable.

---

## Project structure

```
BINANCE UNIVERSE/
├── universe/
│   ├── config.py               # All configurable constants (weights, TOP_N, etc.)
│   ├── models.py               # Pydantic v2 data models for every pipeline stage
│   ├── binance_client.py       # Async HTTP wrapper for Binance fapi endpoints
│   ├── contract_filter.py      # Eligibility rules + exchange info parser
│   ├── market_metrics.py       # Bulk ticker + concurrent OI collection
│   ├── normalization.py        # Min-max normalization into [0, 1]
│   ├── ranking_engine.py       # Deterministic weighted scoring + ranking
│   ├── top_n_selector.py       # Assigns ACTIVE_TOP_100 / WATCHLIST status
│   ├── snapshot_repository.py  # Append-only JSONL snapshot persistence
│   └── refresh.py              # Orchestrates the full pipeline; CLI entry point
├── tests/
│   ├── fixtures/
│   │   └── exchange_info.json  # Mocked Binance exchange info response
│   ├── test_contract_filter.py
│   ├── test_ranking_engine.py
│   ├── test_snapshot_repository.py
│   └── test_refresh.py
├── data/
│   └── snapshots/              # Runtime snapshot output (gitignored)
├── pyproject.toml
├── requirements.txt
└── README.md
```

---

## Requirements

- **Python 3.11+**
- Dependencies: `httpx`, `pydantic>=2`, `python-json-logger`

---

## Installation

```bash
# Create and activate a virtual environment
python -m venv .venv
.venv\Scripts\activate          # Windows
# source .venv/bin/activate     # macOS / Linux

# Install dependencies
pip install -r requirements.txt
```

---

## Running a universe refresh

```bash
python -m universe.refresh
```

Or equivalently:

```bash
python -m universe
```

### Example output

```
2026-08-31T18:56:00Z  INFO  universe.refresh  Universe refresh started  [id=20260831T185600Z]
2026-08-31T18:56:00Z  INFO  universe.refresh  [1/8] Fetching exchange info from Binance…
2026-08-31T18:56:01Z  INFO  universe.refresh        Discovered 358 contracts total
2026-08-31T18:56:01Z  INFO  universe.refresh  [2/8] Filtering eligible crypto perpetuals…
2026-08-31T18:56:01Z  INFO  universe.refresh        Eligible: 298  |  Excluded: 60
...
══════════════════════════════════════════════════════════════════════
UNIVERSE REFRESH COMPLETE
══════════════════════════════════════════════════════════════════════
  Snapshot ID          : 20260831T185600Z
  Snapshot timestamp   : 2026-08-31T18:56:00+00:00
  Total discovered     : 358
  Eligible perpetuals  : 298
  Excluded contracts   : 60
  Successfully ranked  : 293
  Metric fetch failures: 5
  ACTIVE_TOP_100 count : 100
  Snapshot file        : data/snapshots/snapshot_20260831.jsonl
──────────────────────────────────────────────────────────────────────
  Top-20 contracts:
    #1    BTCUSDT       score=0.9821  vol=$52.30B  OI=$18.40B
    #2    ETHUSDT       score=0.9314  vol=$28.10B  OI=$9.20B
    #3    SOLUSDT       score=0.8102  vol=$12.40B  OI=$3.80B
    ...
```

---

## Running tests

```bash
pytest tests/ -v
```

All tests use mocked Binance responses — **no live API calls required**.

---

## Configuration

All configurable values live in [`universe/config.py`](universe/config.py).

| Setting | Default | Description |
|---|---|---|
| `TOP_N` | `100` | Number of contracts in `ACTIVE_TOP_100` |
| `VOLUME_WEIGHT` | `0.50` | Weight for 24h quote volume in the score |
| `OI_WEIGHT` | `0.35` | Weight for open interest in the score |
| `SPREAD_WEIGHT` | `0.15` | Weight for bid/ask spread in the score |
| `REQUIRE_USDT_QUOTE` | `True` | Only include USDT-margined perpetuals |
| `BLOCKED_UNDERLYING_SUBTYPES` | `{INDEX, ETF, STOCK, COMMODITY, LEVERAGED, DEFI, NFT}` | Non-crypto contract categories to exclude |
| `OI_CONCURRENCY_LIMIT` | `20` | Max concurrent open-interest requests |
| `SNAPSHOT_DIR` | `data/snapshots` | Where JSONL snapshots are written |

> **Weights must sum to 1.0.** The engine validates this at startup.

---

## Ranking formula

```
score = VOLUME_WEIGHT  * norm_volume_24h_quote
      + OI_WEIGHT      * norm_open_interest
      + SPREAD_WEIGHT  * (1 - norm_spread_bps)
```

All inputs are min-max normalised to [0, 1] across the full eligible universe
before combining.  Spread is inverted so that a tighter spread produces a
higher score.  Ties are broken alphabetically (deterministic).

---

## Snapshot format

Snapshots are written as **JSONL files** (one JSON object per line) to
`data/snapshots/snapshot_YYYYMMDD.jsonl`.

Each refresh appends:
- One **HEADER** line with aggregate stats.
- One **DATA** line per eligible contract.

Files are **never overwritten**.  Multiple refreshes on the same day accumulate
in the same file.

### Querying examples

```python
from universe.snapshot_repository import SnapshotRepository

repo = SnapshotRepository()

# Rank history for a single contract
history = repo.get_snapshots_for_symbol("BTCUSDT")

# Universe at a specific point in time
from datetime import datetime, timezone
snapshot = repo.get_snapshot_at(datetime(2026, 8, 31, 12, 0, tzinfo=timezone.utc))
```

Or with `grep` / `jq` from the terminal:

```bash
# All BTC records
grep '"BTCUSDT"' data/snapshots/snapshot_20260831.jsonl | jq '{rank, score, universe_status}'

# All refresh headers (one per run)
grep '"HEADER"' data/snapshots/snapshot_20260831.jsonl | jq .
```

---

## Adding the next research module

The universe engine is designed to be an upstream dependency:

```python
from universe import run_refresh
import asyncio

result = asyncio.run(run_refresh())

# result.universe    → list[UniverseMember] — full ranked master universe
# result.top_100     → list[UniverseMember] — only ACTIVE_TOP_100
```

`UniverseMember` in [`universe/models.py`](universe/models.py) has `Optional`
fields reserved for future research data (funding rates, OI change, volatility,
etc.).  Add fields there without breaking existing consumers.

---

## Architecture

```
binance_client          (HTTP layer — Binance API only)
      ↓
contract_filter         (eligibility rules — pure metadata inspection)
      ↓
market_metrics          (data collection — bulk ticker + concurrent OI)
      ↓
normalization           (min-max scaling — pure math)
      ↓
ranking_engine          (weighted scoring — pure math)
      ↓
top_n_selector          (status assignment — threshold comparison)
      ↓
snapshot_repository     (persistence — JSONL append-only)
      ↑
refresh.py              (orchestrator — wires everything together)
```

Each layer has **one responsibility** and can be tested or replaced independently.

---

## Excluded from V1 (intentionally)

- Trading strategies
- Signal generation
- ML models
- Backtesting
- Portfolio construction
- Execution engine
- Order-flow analytics
- Funding rate analytics
- Liquidation data
- Frontend / dashboard
