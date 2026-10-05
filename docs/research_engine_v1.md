# Research Engine V1 — Phase 1

## Overview

Research Engine V1 provides a generic, causally-correct **Event-Study Framework** that answers:

> "When condition X occurs at time T using only information available at T, what happens at T + H?"

This is research infrastructure. It is not a strategy engine, not an ML system, and not a backtester.

---

## Architecture

```
research/
├── models.py           — Pydantic data models
├── data_adapter.py     — Read-only access to frozen Feature Layer V1
├── event_engine.py     — Causal event detection (data <= T only)
├── outcome_engine.py   — Forward outcome measurement (data at T+H)
├── validators.py       — Post-hoc temporal invariant enforcement
├── research_runner.py  — Pipeline orchestrator
├── result_store.py     — Append-only JSONL persistence
└── __main__.py         — CLI entry point
```

**Data flow:**

```
ResearchSpec
      ↓
ResearchDataAdapter   (reads frozen FeatureStore only)
      ↓
EventEngine           (causal — receives data <= T)
      ↓
OutcomeEngine         (forward — receives data at T+H)
      ↓
TemporalValidator     (post-hoc correctness assertion)
      ↓
ResearchResult
      ↓
ResearchResultStore   (append-only JSONL)
```

---

## Data Models

### `ThresholdCondition`
A single feature comparison: `feature_name operator threshold`.

Supported operators: `>`, `>=`, `<`, `<=`, `==`, `!=`

### `EventDefinition`
Defines the full event-detection rule.

Fields:
- `condition`: ThresholdCondition
- `event_mode`: `condition` | `crossing`
- `event_policy`: `every_observation` | `first_entry` (condition mode only)
- `crossing_direction`: `cross_up` | `cross_down` | `any` (crossing mode only)

### `OutcomeDefinition`
Defines one forward measurement.

Fields:
- `name`: outcome identifier
- `horizon_minutes`: positive integer (minutes after event timestamp)
- `price_feature`: FeatureRow field to use as price (e.g. `mid_price`, `return_1m`)

### `ResearchSpec`
Complete specification of a research run. Fully serialisable and deterministic.

Fields: `research_id`, `symbols`, `start_time`, `end_time`, `feature_version`, `engine_version`, `event_definition`, `outcome_definitions`

### `Event`
One detected event instance. `timestamp` is when the event became observable.

### `EventOutcome`
One forward outcome for one event at one horizon. `status` is always explicit.

### `ResearchResult`
Complete output for one symbol: events, outcomes, metadata.

---

## Event Semantics

### Condition Mode

The condition `feature_name operator threshold` is evaluated against each bar's feature value.

**`event_policy: every_observation`**  
Every bar satisfying the condition generates an event. Suitable when you want the full population of satisfying observations.

**`event_policy: first_entry`**  
Generates an event only on the first bar satisfying the condition after a bar that did NOT satisfy it. This implements state-transition semantics (non-satisfied → satisfied). Sustained satisfying runs do not generate repeated events.

`None` values in the feature series are treated as non-satisfying for `first_entry` state tracking.

### Crossing Mode

Detects a sign change across the threshold boundary.

**`cross_up` (exact definition):**
```
previous valid observation: feature_value <= threshold
current observation:        feature_value > threshold
```

**`cross_down` (exact definition):**
```
previous valid observation: feature_value >= threshold
current observation:        feature_value < threshold
```

**Key properties:**
- The event timestamp is the **current** observation's timestamp.
- `None` values are **skipped** when tracking the previous state. The engine waits for the next non-None value.
- No crossing can be detected on the first observation (there is no previous value to compare against).
- A future observation (timestamp > T) is never used to determine whether a crossing occurred at T.

**Example:**
```
T=0: feature = 89  (below threshold=90)
T=1: feature = 91  → cross_up event at T=1
T=2: feature = 93
T=3: feature = 88  → cross_down event at T=3
T=4: feature = None (skipped, prev_val stays 88)
T=5: feature = 92  → cross_up event at T=5 (vs prev=88)
```

---

## Forward Outcome Semantics

### Formula

```
return(T, H) = price(T + H) / price(T) - 1
```

where:
- `T` = event timestamp
- `H` = `OutcomeDefinition.horizon` (timedelta)
- `price` = the FeatureRow field specified in `OutcomeDefinition.price_feature`

### Timestamp Policy

1. Look for an observation with `timestamp == T + H` **exactly**.
2. If found and `price > 0`: `status = valid`, compute return.
3. If `T + H` is beyond the last available observation: `status = insufficient_future_data`, `value = None`.
4. If `T + H` is within range but no exact match: `status = missing_price`, `value = None`.
5. If price at `T` is missing or `<= 0`: `status = missing_price`, `value = None`.

**No nearest-neighbour substitution. No forward-fill. No interpolation.**

### Outcome Status

| Status | Meaning |
|---|---|
| `valid` | Return computed successfully |
| `insufficient_future_data` | Target timestamp is beyond the available dataset |
| `missing_price` | Price missing at T or at T+H |

---

## Temporal Safety Guarantees

### Causal Wall

The `EventEngine` and `OutcomeEngine` are **separate classes with separate data slices**:

- `EventEngine` receives `feature_series` covering `[start, end]` — the causal window.
- `OutcomeEngine` receives `price_series` covering `[start, end + max_horizon]` — the full outcome window.

These two data slices are never mixed. The event detection cannot access the outcome data.

### Post-hoc Validation

`TemporalValidator` enforces two invariants after each run:

1. **Event invariant:** `event.timestamp` must appear in the feature series that was used for detection. If an event timestamp is beyond the series maximum, `TemporalValidationError` is raised.

2. **Outcome invariant:** For `status = valid` outcomes, `outcome_timestamp >= event_timestamp`. An outcome that precedes its own event raises `TemporalValidationError`.

### Proven Properties

| Property | Evidence |
|---|---|
| Future features cannot change Event(T) | `TestA_FutureFeatureMutation` — mutations at T+1m, T+5m, T+1h, T+1d, mid-array insertion |
| Future prices cannot change Event(T) | `TestB_FuturePriceMutation` |
| Input ordering cannot change events | `TestC_InputOrdering` — ascending, descending, 10 random shuffles |
| TemporalValidator rejects future events | `TestD_TemporalValidator` |
| Outcomes are explicitly forward-looking | `TestE_OutcomeUsesForwardData` |
| Insufficient data → explicit status | `TestF_InsufficientFutureData` |

---

## Missing Data

The engine never imputes missing data. All missing-data behaviors are explicit:

| Scenario | Behavior |
|---|---|
| Feature value `None` at some bar | Skipped (crossing) or non-satisfying (condition) |
| Price at event timestamp is `None` or `<= 0` | `missing_price` status |
| No observation at exactly `T + H` | `missing_price` status |
| Dataset ends before `T + H` | `insufficient_future_data` status |
| Empty feature series | Zero events |

---

## Overlapping Events

Multiple events may share overlapping time windows. The engine preserves the full raw event population without any hidden deduplication. If deduplication is desired for a specific research question, it belongs at the research-query layer, not inside the engine.

---

## Persistence & Idempotency

**Storage layout:**
```
data/research/{research_id}/{symbol}/{YYYYMMDD}.jsonl
```

One `EventOutcome` JSON object per line.

**Idempotency key:**
```
(research_id, symbol, event_timestamp, event_definition_hash, outcome_name)
```

Repeated execution of the same `ResearchSpec` against the same stored data produces zero new rows. Historical results are never silently overwritten.

---

## Versioning

Every research result carries:
- `engine_version = "research_v1"`
- `feature_version = "v1"` (inherited from `ResearchSpec`)
- `event_definition_hash` (deterministic SHA-256 of the `EventDefinition`)

These fields together with `research_id` are sufficient to reproduce any research run given the same stored data.

---

## CLI

```bash
python -m research run \
  --symbols BTCUSDT,ETHUSDT \
  --feature return_1m \
  --operator ">" \
  --threshold 0.005 \
  --event-mode crossing \
  --crossing-direction cross_up \
  --event-policy every_observation \
  --horizons 1,3,5,10 \
  --price-feature mid_price \
  --start 2026-08-31T00:00:00Z \
  --end 2026-08-31T01:00:00Z \
  --research-id my_study_001
```

If `--research-id` is omitted, a deterministic ID is generated from the spec content.

The CLI reports: research ID, symbols, event definition, events detected, outcome counts by status, new rows persisted, output directory.

**The CLI does not compute statistics** (mean, Sharpe, win rate, etc.) — those belong to the future Statistics Engine.

---

## Known Limitations (Intentionally Deferred)

The following are out of scope for Phase 1 and will be addressed in future phases:

- **Statistics Engine:** Mean/median/Sharpe/win-rate/significance testing on outcome populations.
- **Multi-condition events:** Events requiring simultaneous satisfaction of multiple features.
- **Universe-aware event detection:** Automatic selection of active-at-time symbols.
- **Continuous outcome tracking:** Horizon-free path-dependent metrics (max drawdown, time-to-cross, etc.).
- **Event clustering / deduplication policies:** Research-level dedup of overlapping events.
- **Parallel execution:** Per-symbol parallelism for large universe runs.
