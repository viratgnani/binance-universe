# Data Readiness Audit — Research Feature Layer V1 / RSI(14) Event Study

Generated: 2026-09-08T10:55:00Z

---

## Scope

This document audits the data readiness for the planned research experiment:

> **"After RSI(14) crosses above 90 on 1-minute closes, what happens to eligible
> Binance USDⓈ-M altcoin perpetuals over +1m, +3m, +5m, and +10m?"**

Experiment exclusions: BTCUSDT, ETHUSDT, SOLUSDT

---

## Section 1 — Frozen Layer Status

All frozen upstream layers remain untouched. This audit does not modify them.

| Layer | Status | Tests |
|---|---|---|
| Universe Engine V1.1 | FROZEN | ✅ |
| Market Data Layer V1 | FROZEN | ✅ |
| Market Data V2 / Order Book | FROZEN | ✅ |
| Research Feature Layer V1 | FROZEN | ✅ |
| Research Engine Phase 1 | FROZEN | ✅ |
| Research Engine Phase 2 | FROZEN | ✅ |
| Research Indicator Layer V1 | FROZEN | ✅ |

**Test suite baseline before this task: 561/561 passing.**
**Test suite after adding readiness layer: 603/603 passing (+42 new tests, 0 regressions).**

---

## Section 2 — Pre-Acquisition Data Audit

### OHLCV Data Stored Before This Task

Inspection of `data/ohlcv/` before any acquisition:

| Symbol | Interval | Files | Candles | Earliest | Latest | Notes |
|---|---|---|---|---|---|---|
| BTCUSDT | 1m | 3 | 78 | 2024-08-31T00:00 | 2026-09-01T13:45 | 31+31+16 rows; EXCLUDED from experiment |
| BTCUSDT | 15m | 1 | 31 | 2024-08-31T00:00 | 2024-08-31T07:30 | EXCLUDED |
| ETHUSDT | 1m | 3 | 78 | 2024-08-31T00:00 | 2026-09-01T13:45 | EXCLUDED |

**Before this task: 2 symbols, 156 1m candles total, all EXCLUDED from experiment.**
**Zero alt-perpetual OHLCV data existed.**

### Feature Store (data/features/)

| Symbol | Candles | Close field | Notes |
|---|---|---|---|
| BNBUSDT | ~61 | NULL | Trade-derived fields only; no price data |
| BTCUSDT | ~61 | NULL | EXCLUDED |
| ETHUSDT | ~61 | NULL | EXCLUDED |
| SOLUSDT | ~61 | NULL | EXCLUDED |
| XRPUSDT | ~61 | NULL | All-zero values |

**Feature store contains no usable close prices for RSI calculation.**

### Indicator Store (data/indicators/)

| Symbol | Field used | Notes |
|---|---|---|
| BTCUSDT | trade_count (proxy) | EXCLUDED; trade_count is not a valid RSI input |
| ETHUSDT | trade_count (proxy) | EXCLUDED |

**No valid RSI data exists for any alt symbol.**

---

## Section 3 — Universe Snapshot Status

Snapshot: `data/snapshots/snapshot_20260831.jsonl`

| Field | Value |
|---|---|
| Snapshot timestamp | 2026-08-31T13:37:53Z |
| Total DATA records | 2,382 |
| ACTIVE_TOP_100 | 500 |
| WATCHLIST | 1,882 |
| Ranked (rank ≠ None) | 1,985 |
| Historical ranked available | **YES** |

**Correction from earlier analysis:** The universe snapshot DOES contain non-None ranks for 1,985 of 2,382 records. Historical ranked universe data is partially available.

**However:** For the RSI experiment, we are using all eligible USDT perpetuals (ACTIVE_TOP_100 + WATCHLIST) excluding BTC/ETH/SOL, because:
1. The experiment is about the broader alt universe, not a filtered top-N.
2. 394 eligible symbols with valid ASCII alphanumeric tickers were identified.

**Universe description (honest):**
> "Eligible Binance USDⓈ-M crypto perpetuals (ACTIVE_TOP_100 + WATCHLIST status in the 2026-08-31 snapshot), excluding BTCUSDT, ETHUSDT, and SOLUSDT."
> NOT called "Top-100" because we include WATCHLIST symbols.
> NOT a historical-membership universe (snapshot is from 2026, experiment data is from 2024–2025).

---

## Section 4 — Readiness Specification

```
ExperimentReadinessSpec:
  interval              = "1m"
  rsi_period            = 14
  rsi_min_candles       = 15   (= rsi_period + 1)
  preferred_history     = 30 days
  required_forward_min  = 10 minutes
  exclude_symbols       = {BTCUSDT, ETHUSDT, SOLUSDT}
```

### Why 30 days as the threshold?
- RSI(14) requires 15 candles to initialize but produces one value from a 15-minute window.
- A meaningful event study needs many independent event occurrences.
- RSI(14) > 90 is a rare event (typically 1–5 per day on individual symbols).
- 30 days provides a reasonable minimum sample of ~30–150 potential events per symbol.
- The target acquisition (2024-09-01 to 2025-09-01 = 365 days) exceeds the minimum by 12×.

---

## Section 5 — Data Acquisition Plan

**Command executed:**
```bash
python -m data_readiness acquire \
  --symbols eligible_alts \
  --start 2024-09-01 \
  --end 2025-09-01
```

**Parameters:**
- Symbols: 394 eligible alt perpetuals (from 2026-08-31 snapshot, ex-BTC/ETH/SOL)
- Date range: 365 days (2024-09-01 00:00 UTC to 2025-09-01 00:00 UTC)
- Interval: 1m
- Estimated candles: ~525,600 per symbol (~207M total)

**Implementation:**
- Delegates entirely to the frozen `backfill_ohlcv()` function.
- Progress files written per symbol at `data/ohlcv/{SYMBOL}/1m/.backfill_progress.json`.
- Idempotent: re-running is safe.
- Restartable: incomplete symbols will resume from last checkpoint.

**Acquisition status:** ▶ IN PROGRESS as of 2026-09-08T10:55Z.

---

## Section 6 — New Layer Components

### `market_data/readiness.py` [NEW]

Pure read-only classification module. Never modifies any data.

Key classes:
- `ExperimentReadinessSpec` — frozen dataclass with experiment requirements
- `SymbolReadiness` — per-symbol audit result
- `ReadinessSummary` — aggregate over all symbols
- `ReadinessClassifier` — reads OHLCVStore, runs integrity checks, classifies

Key functions:
- `load_universe_snapshot_status()` — reports snapshot availability without modifying it
- `load_eligible_alt_symbols()` — reads snapshot, applies filters, deduplicates

### `data_readiness/__main__.py` [NEW]

CLI with three commands:
- `audit` — inspect current data, no API calls
- `acquire` — thin wrapper over frozen `backfill_ohlcv`; supports `--dry-run`
- `report` — generate `data_readiness_report.md` + `data_readiness.json`

### Tests [NEW]

| File | Tests | Covers |
|---|---|---|
| `tests/test_data_readiness.py` | 28 | Readiness spec, MISSING/EXCLUDED/INCOMPLETE/READY classification, gaps, coverage, universe snapshot |
| `tests/test_data_acquisition.py` | 14 | Dry-run zero API calls, excluded symbol enforcement, idempotency, pagination, boundary conditions |

---

## Section 7 — Quality Checks

The `market_data/integrity.py` (frozen) runs these checks on every batch:

| Check | Detects |
|---|---|
| `check_candle_duplicates` | Identical (symbol, interval, open_time) |
| `check_candle_gaps` | Missing expected 1-minute slots |
| `check_candle_sort_order` | Out-of-order timestamps |
| `check_ohlc_validity` | High < Low, Open/Close outside range, negative volume |
| `check_timestamp_alignment` | Timestamps not on 1-minute UTC boundaries |

Violations are recorded in `SymbolResult.violations` and included in `CollectionSummary`.

---

## Section 8 — Frozen Layer Modification Audit

A line-by-line diff confirms **zero changes** to any frozen module:

| Module | Modified? |
|---|---|
| `market_data/backfill.py` | ❌ No |
| `market_data/ohlcv_store.py` | ❌ No |
| `market_data/client.py` | ❌ No |
| `market_data/integrity.py` | ❌ No |
| `market_data/quality.py` | ❌ No |
| `market_data/models.py` | ❌ No |
| `market_data/config.py` | ❌ No |
| `market_data/__main__.py` | ❌ No |
| `research/` (all) | ❌ No |
| `indicators/` (all) | ❌ No |
| `features/` (all) | ❌ No |
| `universe/` (all) | ❌ No |

---

## Section 9 — Experiment Readiness Decision (as of start of acquisition)

| Criterion | Status |
|---|---|
| 1m OHLCV for alt universe | ⏳ ACQUISITION IN PROGRESS |
| Preferred history (30+ days) | ⏳ PENDING — targeting 365 days |
| No invalid candles | ✅ integrity checks run on every batch |
| Duplicate-free | ✅ idempotent dedup in frozen store |
| Universe membership clear | ✅ documented as "eligible universe" (not Top-100) |
| Historical ranked universe available | ⚠️ PARTIAL — snapshot from 2026-08-31, not from 2024-09-01 |
| RSI(14) computable | ⏳ PENDING — will compute from OHLCV close after acquisition |
| Forward outcomes measureable | ⏳ PENDING — requires continuous coverage at T+1/3/5/10m |

**VERDICT: NOT READY — acquisition in progress.**

Re-run `python -m data_readiness report --symbols eligible_alts` after acquisition completes.

---

## Section 10 — Known Limitations

1. **Universe snapshot is from 2026-08-31.** We are acquiring data for 2024-09-01 to 2025-09-01.
   Some symbols in the snapshot may not have existed in 2024. The exchange will return empty
   responses for those periods; the backfill handles this gracefully (no-data range is skipped).

2. **No historical Top-100 ranking.** The snapshot ranks reflect 2026-08-31, not 2024.
   We use eligibility status only, not ranking. This is documented as a methodology limitation
   in the experiment specification.

3. **Some symbols were listed as WATCHLIST/ACTIVE but may not have perpetual contracts
   available on the futures API.** These will fail with 400/404 errors captured in
   `SymbolResult.error` and reported in the summary. They are NOT silently excluded.

4. **Exchange data gaps.** For very new tokens listed after 2024-09-01, the futures API will
   return data only from their listing date. These will have `INCOMPLETE` coverage with
   gaps reported honestly.
