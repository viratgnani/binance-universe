# Research Indicator Layer V1

## Overview

Research Indicator Layer V1 provides a generic architecture for deriving deterministic technical indicators from frozen market historical data (the Feature Layer V1). It is strictly an analytical layer—no trading semantics, entry/exit logic, or portfolio construction rules exist here.

The first implementation is RSI (Relative Strength Index) using Wilder's original exponential smoothing methodology.

## Architecture

```text
Feature Layer V1 (Stored JSONL)
        ↓
Indicator Engine
  ├── Registry: Discovers available calculators.
  ├── Calculator: Implementation of the indicator logic (e.g. RSI).
  └── Validators: Enforces temporal ordering and duplication checks.
        ↓
Indicator Store (JSONL)
        ↓
Research Engine V1
```

## RSI Definition

The V1 implementation of RSI uses **Wilder's Smoothing**.

Given a price series $P_t$, we calculate changes:
$delta_t = P_t - P_{t-1}$
$gain_t = max(delta_t, 0)$
$loss_t = max(-delta_t, 0)$

For the first $n$ valid price changes (where $n$ is the period):
$avg\_gain = mean(gain_1 \dots gain_n)$
$avg\_loss = mean(loss_1 \dots loss_n)$

For subsequent observations, we apply Wilder's exponential smoothing:
$avg\_gain_t = \frac{avg\_gain_{t-1} \times (n - 1) + gain_t}{n}$
$avg\_loss_t = \frac{avg\_loss_{t-1} \times (n - 1) + loss_t}{n}$

Finally:
$RS = \frac{avg\_gain}{avg\_loss}$
$RSI = 100 - \frac{100}{1 + RS}$

## Parameters

- **`period` (int)**: The lookback parameter for Wilder's smoothing. Default is 14. Must be $\ge 2$.

## Initialization

The first valid RSI value requires exactly `period + 1` valid price observations to establish the first `period` changes. During this "warm-up" phase, the RSI `value` is explicitly persisted as `null`. No zero-filling or backward-filling is applied.

## Edge Cases

- **Zero Gain & Zero Loss**: $RSI = 50.0$. Represents a perfectly flat series.
- **Zero Loss Only**: $RSI = 100.0$.
- **Zero Gain Only**: $RSI = 0.0$.
- **Invalid Prices**: Inputs containing `NaN`, `Inf`, or prices $\le 0$ are explicitly rejected. The indicator returns `null` for these timestamps, and the value is not included in the smoothing accumulators.

## Timestamp Semantics

Timestamp causality is strictly enforced. For an indicator value $V_T$:
- Only prices with timestamp $\le T$ are utilized.
- No future observation can retroactively affect $V_T$.
- This guarantees safety against look-ahead bias.

## Missing Data

Handled via the `skip_missing` policy. If a feature observation is missing or null, the indicator value for that timestamp is recorded as `null`, and the accumulator state remains unchanged. This ensures that the engine only operates on actual realized data.

## Duplicate Data

If identical timestamps exist in the raw input, the engine raises a `TemporalValidationError` before calculation starts. The architecture mandates clean chronological inputs.

## Numerical Safety

The engine guarantees that $0.0 \le RSI \le 100.0$ for all valid inputs. No $NaN$ or $\pm Inf$ values will be persisted in an `IndicatorValue` record.

## Versioning & Idempotency

Rows in the `IndicatorStore` are uniquely identified by:
`(symbol, timestamp, indicator_name, indicator_version, parameter_hash)`

The `parameter_hash` is a deterministic SHA-256 derivation of the indicator's parameters (e.g. `period=14`). This allows $RSI(14)$ and $RSI(7)$ to coexist without silently overwriting each other.

## Known Limitations

- **V1 implementation focuses entirely on RSI**.
- **No Signal interpretation**: A value of $RSI > 70$ is mathematically recorded, but is not translated into "Overbought" or "Sell". Event semantics belong downstream in the Research Event Engine.
