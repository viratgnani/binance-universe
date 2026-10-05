# Research Feature Layer V1 — Final Adversarial Audit + Post-Remediation Verification

## Overview

This document covers two phases:

1. **Initial Adversarial Audit** — defects discovered without changing production code.
2. **Remediation Fixes** — production fixes applied to resolve each defect.
3. **Post-Remediation Verification** — deterministic test suite proving each fix works and no regression was introduced.

---

## Phase 1: Initial Adversarial Audit

### Audit Findings

#### Finding 1 [CRITICAL] — Input Ordering Determinism

**Defect:** `calculate_trade_features`, `calculate_volume_features`, `calculate_price_features`, and `calculate_volatility_features` assumed input arrays were sorted chronologically ascending. The `reversed()` + early-`break` iteration pattern would silently terminate early and discard valid observations when input was shuffled, reversed, or out-of-order (as can occur from upstream API responses or store reads).

**File:** `research_features/calculators.py`

---

#### Finding 2 [HIGH] — Order Book Staleness Leakage

**Defect:** `FeatureEngine` accepted any order-book checkpoint with `exchange_event_time <= T` regardless of how old it was. A 48-hour-old snapshot was silently passed to `calculate_order_book_features` as though it represented current microstructure.

**File:** `research_features/engine.py`

---

#### Finding 3 [HIGH] — Historical Survivorship Bias

**Defect:** `python -m research_features generate --symbols universe --start 2020-01-01` loaded the *current* `ACTIVE_TOP_100` ranking file (the latest snapshot) and applied it to historical dates, guaranteeing survivorship bias for any historical backfill.

**File:** `research_features/__main__.py`

---

#### Finding 4 [MEDIUM] — Incomplete Feature Registry

**Defect:** `bid_depth_10`, `ask_depth_10`, `depth_imbalance_10`, `bid_depth_20`, `ask_depth_20`, and `depth_imbalance_20` were computed by `calculate_order_book_features` and persisted in `FeatureRow`, but were entirely absent from `FEATURE_REGISTRY`.

**File:** `research_features/registry.py`

---

## Phase 2: Remediation

### Fix 1 — Input Ordering Determinism

**Change:** Added explicit `sorted()` normalization at the top of each calculator function:

- `calculate_price_features`: `candles = sorted(candles, key=lambda c: c.open_time)`
- `calculate_volatility_features`: `candles = sorted(candles, key=lambda c: c.open_time)`
- `calculate_volume_features`: `candles = sorted(candles, key=lambda c: c.open_time)`
- `calculate_trade_features`: `trades = sorted(trades, key=lambda t: t.timestamp)`

All calculators are now internally self-normalizing. The output is deterministic regardless of the ordering of their input arrays.

---

### Fix 2 — Order Book Staleness Policy

**Change:** Added a maximum staleness threshold of **5 minutes** in `FeatureEngine.generate_features()`:

```python
if latest_checkpoint is not None:
    if current_time - latest_checkpoint.exchange_event_time > timedelta(minutes=5):
        latest_checkpoint = None
```

A checkpoint older than 5 minutes produces `None`, not stale features. The `calculate_order_book_features(None)` path returns explicit `null` for all 14 order-book fields.

**Boundary:** The threshold is **exclusive**. A checkpoint exactly 5 minutes old (`T - 5m`) is still valid. A checkpoint at `T - 5m - 1s` is stale.

---

### Fix 3 — Historical Survivorship Bias

**Change:** Modified `_parse_symbols()` in `__main__.py` to accept the `start_dt` argument and traverse the snapshot list to find the last snapshot whose date is ≤ the requested `start` date:

```python
for f in reversed(files):
    f_date = datetime.strptime(f.stem.split("_")[-1], "%Y%m%d").date()
    if f_date <= target_date:
        target_file = f
        break
```

If no snapshot precedes the `start` date, the earliest available snapshot is used with a logged warning. Explicit `--symbols BTCUSDT,...` bypasses this lookup entirely.

---

### Fix 4 — Feature Registry Completeness

**Change:** Added all six missing depth-level features to `FEATURE_REGISTRY` in `registry.py`:
`bid_depth_10`, `ask_depth_10`, `depth_imbalance_10`, `bid_depth_20`, `ask_depth_20`, `depth_imbalance_20`.

---

## Phase 3: Post-Remediation Verification

### 3.1 Input Ordering Fix Verification (`tests/test_feature_ordering.py`)

**Test coverage:**
- Ascending, descending, randomly shuffled, and 5 random permutations of candle arrays → all produce identical price, volatility, and volume features.
- Ascending, descending, randomly shuffled, and 5 random permutations of trade arrays → all produce identical trade aggregations.
- Duplicate trade inputs produce deterministically consistent output (documented accumulation behavior).

**Result:** ✅ PASS

**Documented boundary:** The trade window cutoff is `timestamp > T - 1m` (strictly greater than). A trade exactly at the cutoff is excluded.

---

### 3.2 Order Book Staleness Verification (`tests/test_feature_staleness.py`)

**Exact boundary conditions tested:**

| Scenario | Checkpoint age | Expected spread |
|---|---|---|
| T - 1s | 1 second | 1.0 (valid) |
| T - 1m | 1 minute | 1.0 (valid) |
| T - 4m59s | 4m59s | 1.0 (valid) |
| T - exactly 5m | 5 minutes | 1.0 (valid) |
| T - 5m1s | 5m1s | null (stale) |
| T - 10m | 10 minutes | null (stale) |
| T - 1h | 1 hour | null (stale) |
| No checkpoint | — | null |

**Boundary:** **Inclusive at exactly 5 minutes.** `>` not `>=` is used in the staleness check.

**Staleness + look-ahead interaction:**
- Stale old book (`T-10m`) + future book (`T+1s`) → `null` (old is stale, future is ignored by temporal slice).
- Valid book (`T-4m`) + future extreme book (`T+1s`) → valid book features used, future book has zero influence.
- All 14 order-book fields verified (`spread`, `best_bid`, `best_ask`, `mid_price`, `spread_bps`, `bid_depth_5/10/20`, `ask_depth_5/10/20`, `depth_imbalance_5/10/20`).

**Result:** ✅ PASS

---

### 3.3 Historical Survivorship Bias Verification (`tests/test_feature_survivorship.py`)

**Fixture:**
- Snapshot A (`snapshot_20250101`): Contains SYMBOL_A (`ACTIVE_TOP_100`), not SYMBOL_B.
- Snapshot B (`snapshot_20260831`): Contains SYMBOL_B (`ACTIVE_TOP_100`), not SYMBOL_A (delisted).

**Tests:**
- `--symbols universe --start 2025-01-15` → selects Snapshot A → SYMBOL_A returned, SYMBOL_B excluded ✅
- `--symbols universe --start 2026-09-01` → selects Snapshot B → SYMBOL_B returned ✅
- `--symbols universe --start 2024-01-01` (pre-history) → falls back to earliest snapshot (A) ✅
- `--symbols BTCUSDT,ETHUSDT` → bypasses lookup, returns explicit list as-is ✅

**Result:** ✅ PASS

---

### 3.4 Feature Registry Completeness (`tests/test_feature_registry_audit.py`)

**Bidirectional audit:**
- **IMPLEMENTATION → REGISTRY:** All calculator output keys present in `FEATURE_REGISTRY` ✅
- **REGISTRY → IMPLEMENTATION:** All registry entries have a corresponding calculator output ✅
- **SCHEMA (Pydantic FeatureRow) = IMPLEMENTATION:** Schema field set exactly matches calculator output ✅
- Specific confirmation of: `depth_imbalance_10`, `depth_imbalance_20`, `bid_depth_10`, `ask_depth_10`, `bid_depth_20`, `ask_depth_20` ✅

**Metadata completeness:** Every registry entry has non-empty `name`, `version`, `description`, `source_dataset`, `lookback`, `timestamp_semantics`, `missing_data_policy` ✅

**Result:** ✅ PASS

---

### 3.5 Look-Ahead Invariant (`tests/test_feature_adversarial.py`)

Adversarial mutations verified (future candles, trades, order-book checkpoints injected at T+1s, T+1m, T+1h, T+1d):

- All mutations produce FeatureRow(T) **identical** to the baseline.
- Future candles injected mid-array (simulating out-of-order API response) are correctly filtered.

**Result:** ✅ PASS — Look-ahead invariant holds after all remediation changes.

---

### 3.6 Numerical Safety, Missing Data, and Idempotency

Tested via `tests/test_feature_adversarial.py` (numerical torture, empty arrays) and `tests/test_feature_serialization.py` (null preservation, NaN rejection):

- No NaN/Inf reach persisted rows ✅
- Empty inputs return explicit `null` fields, not exceptions ✅
- Crossed and zero-depth order books return `null`, no division-by-zero ✅
- `(symbol, timestamp, feature_version)` idempotency key prevents duplicate rows ✅
- Second identical generation run: 0 rows created, 305 skipped ✅

**Result:** ✅ PASS

---

### 3.7 Full Regression Suite

```text
429 tests collected
429 tests passed
0 failed
0 skipped
0 warnings
```

All upstream layers (Universe V1.1, Market Data V1, Market Data V2) and all Feature Layer tests pass without regression.

---

### 3.8 Live Validation

5-symbol validation (BTCUSDT, ETHUSDT, SOLUSDT, BNBUSDT, XRPUSDT), 1-hour window:

- Run 1: 183 rows created, 122 skipped (no data), 0 violations ✅
- Run 2 (idempotency): 0 rows created, 305 skipped, 0 violations ✅

---

## Final Freeze Decision

```text
AUDIT_STATUS:               PASSED
CRITICAL_FINDINGS:          0
HIGH_FINDINGS:              0
MEDIUM_FINDINGS:            0
LOW_FINDINGS:               0
TESTS_TOTAL:                429
TESTS_PASSED:               429
TESTS_FAILED:               0
WARNINGS:                   0
LOOKAHEAD_INVARIANT:        PASSED
INPUT_ORDERING_STATUS:      PASSED
ORDERBOOK_STALENESS_STATUS: PASSED
SURVIVORSHIP_BIAS_STATUS:   PASSED
REGISTRY_COMPLETENESS_STATUS: PASSED
IDEMPOTENCY_STATUS:         PASSED
DETERMINISM_STATUS:         PASSED
NUMERICAL_SAFETY_STATUS:    PASSED
MISSING_DATA_STATUS:        PASSED
LIVE_VALIDATION_STATUS:     PASSED
DOCUMENTATION_STATUS:       PASSED
FREEZE_RECOMMENDATION:      SAFE TO FREEZE
```
