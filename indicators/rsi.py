"""
indicators/rsi.py

Wilder's RSI (Relative Strength Index) implementation.

Mathematical Specification
--------------------------
For a price series P_t:

  delta_t = P_t - P_{t-1}
  gain_t  = max(delta_t, 0)
  loss_t  = max(-delta_t, 0)

Initialization (first n gains/losses, where n = period):
  avg_gain_init = mean(gain_1, ..., gain_n)
  avg_loss_init = mean(loss_1, ..., loss_n)

Wilder smoothing for t > n:
  avg_gain_t = (avg_gain_{t-1} * (n - 1) + gain_t) / n
  avg_loss_t = (avg_loss_{t-1} * (n - 1) + loss_t) / n

RSI:
  if avg_loss == 0 and avg_gain > 0:   RSI = 100.0
  if avg_gain == 0 and avg_loss == 0:  RSI = 50.0   (flat — documented below)
  if avg_gain == 0 and avg_loss > 0:   RSI = 0.0
  else:
    RS  = avg_gain / avg_loss
    RSI = 100 - 100 / (1 + RS)

Edge Case Policies
------------------
avg_gain = 0, avg_loss = 0 → RSI = 50.0
  Rationale: the price series has been completely flat (no gains, no losses).
  50 is the neutral midpoint. This is the documented stable convention.

Invalid price → value = None (excluded from calculation, warm-up extended)
  Invalid means: None, NaN, +Inf, -Inf, <= 0.

First valid RSI
---------------
The first RSI value appears after exactly n+1 valid (non-None, valid price) observations,
producing n price changes and completing the initialisation average.
Bars before this point receive value = None.

Timestamp Safety
----------------
RSI(T) uses only prices with timestamp <= T.
Inputs are sorted ascending by timestamp before calculation.
No future observation is ever accessed.

Duplicate Timestamps
--------------------
If duplicate timestamps exist in the input, a TemporalValidationError is raised
before calculation begins. See indicators/validators.py.

Gap Handling
------------
Bars with null/invalid prices are skipped (missing_data_policy = 'skip_missing').
The engine does not interpolate gaps. The warm-up window advances only on valid prices.
A gap in the middle of the series does not reset the accumulator, but the Wilder
smoothing naturally down-weights old data over time.

Valid RSI Range
---------------
For valid finite inputs, RSI is always in [0.0, 100.0].
No NaN or Inf can appear in a persisted IndicatorValue.
"""

from __future__ import annotations

import logging
import math
from datetime import datetime

from indicators.models import IndicatorDefinition, IndicatorSeries, IndicatorValue
from indicators.validators import TemporalValidationError, validate_no_duplicate_timestamps

logger = logging.getLogger(__name__)

_INDICATOR_NAME = "rsi"
_INDICATOR_VERSION = "v1"


def _is_valid_price(price: float | None) -> bool:
    """Return True if price can be used in RSI calculation."""
    if price is None:
        return False
    if math.isnan(price) or math.isinf(price):
        return False
    if price <= 0:
        return False
    return True


def _compute_rsi(avg_gain: float, avg_loss: float) -> float:
    """
    Compute RSI from Wilder averages.
    Handles all documented edge cases deterministically.
    Result is always in [0.0, 100.0].
    """
    if avg_gain == 0.0 and avg_loss == 0.0:
        return 50.0   # flat price — no movement in either direction
    if avg_loss == 0.0:
        return 100.0  # all gains, no losses
    if avg_gain == 0.0:
        return 0.0    # all losses, no gains
    rs = avg_gain / avg_loss
    return 100.0 - 100.0 / (1.0 + rs)


class RsiCalculator:
    """
    Wilder RSI calculator implementing the IndicatorCalculator protocol.

    Parameters (read from IndicatorDefinition.parameters):
      period (int): Lookback period. Default 14.
        Must be >= 2.
    """

    name = _INDICATOR_NAME
    version = _INDICATOR_VERSION
    description = (
        "Relative Strength Index using Wilder's exponential smoothing. "
        "Measures the magnitude of recent price changes to evaluate "
        "overbought or oversold conditions. Range: [0, 100]. "
        "No trading signal semantics are part of this implementation."
    )

    def calculate(
        self,
        symbol: str,
        price_series: list[tuple[datetime, float | None]],
        definition: IndicatorDefinition,
    ) -> IndicatorSeries:
        """
        Calculate RSI for the given price series.

        Inputs are sorted internally. Duplicate timestamps raise
        TemporalValidationError before any calculation begins.
        """
        period = int(definition.parameters.get("period", 14))
        if period < 2:
            raise ValueError(f"RSI period must be >= 2, got {period}")

        param_hash = definition.parameter_hash()

        # 1. Sort ascending by timestamp (guarantee causal ordering)
        sorted_series = sorted(price_series, key=lambda x: x[0])

        # 2. Validate: no duplicate timestamps
        validate_no_duplicate_timestamps(sorted_series)

        # 3. Build result: one IndicatorValue per input timestamp
        #    We iterate in order, skipping invalid prices for the accumulator
        #    but still emitting a record (with value=None) for each timestamp.

        # State
        avg_gain: float | None = None
        avg_loss: float | None = None
        init_gains: list[float] = []
        init_losses: list[float] = []
        prev_valid_price: float | None = None   # last valid price seen

        output_values: list[IndicatorValue] = []

        for ts, price in sorted_series:
            if not _is_valid_price(price):
                # Emit None for this bar — invalid/missing price
                output_values.append(
                    IndicatorValue(
                        symbol=symbol,
                        timestamp=ts,
                        indicator_name=_INDICATOR_NAME,
                        indicator_version=_INDICATOR_VERSION,
                        parameter_hash=param_hash,
                        input_feature=definition.input_feature,
                        value=None,
                    )
                )
                # Do NOT update prev_valid_price — skip this bar entirely
                continue

            # We have a valid price
            if prev_valid_price is None:
                # This is the first valid price — no change yet, emit None
                prev_valid_price = price
                output_values.append(
                    IndicatorValue(
                        symbol=symbol,
                        timestamp=ts,
                        indicator_name=_INDICATOR_NAME,
                        indicator_version=_INDICATOR_VERSION,
                        parameter_hash=param_hash,
                        input_feature=definition.input_feature,
                        value=None,
                    )
                )
                continue

            # Compute gain/loss for this bar
            delta = price - prev_valid_price
            gain = max(delta, 0.0)
            loss = max(-delta, 0.0)
            prev_valid_price = price

            if avg_gain is None:
                # Still in initialisation phase
                init_gains.append(gain)
                init_losses.append(loss)

                if len(init_gains) == period:
                    # Complete initialisation: simple mean of first n changes
                    avg_gain = sum(init_gains) / period
                    avg_loss = sum(init_losses) / period
                    rsi_value = _compute_rsi(avg_gain, avg_loss)
                    output_values.append(
                        IndicatorValue(
                            symbol=symbol,
                            timestamp=ts,
                            indicator_name=_INDICATOR_NAME,
                            indicator_version=_INDICATOR_VERSION,
                            parameter_hash=param_hash,
                            input_feature=definition.input_feature,
                            value=rsi_value,
                        )
                    )
                else:
                    # Still warming up
                    output_values.append(
                        IndicatorValue(
                            symbol=symbol,
                            timestamp=ts,
                            indicator_name=_INDICATOR_NAME,
                            indicator_version=_INDICATOR_VERSION,
                            parameter_hash=param_hash,
                            input_feature=definition.input_feature,
                            value=None,
                        )
                    )
            else:
                # Wilder smoothing
                avg_gain = (avg_gain * (period - 1) + gain) / period
                avg_loss = (avg_loss * (period - 1) + loss) / period
                rsi_value = _compute_rsi(avg_gain, avg_loss)
                output_values.append(
                    IndicatorValue(
                        symbol=symbol,
                        timestamp=ts,
                        indicator_name=_INDICATOR_NAME,
                        indicator_version=_INDICATOR_VERSION,
                        parameter_hash=param_hash,
                        input_feature=definition.input_feature,
                        value=rsi_value,
                    )
                )

        # Determine series bounds
        start = sorted_series[0][0] if sorted_series else None
        end   = sorted_series[-1][0] if sorted_series else None

        valid_n   = sum(1 for v in output_values if v.value is not None)
        warmup_n  = len(output_values) - valid_n

        return IndicatorSeries(
            symbol=symbol,
            definition=definition,
            start=start,
            end=end,
            values=output_values,
            metadata={
                "period": period,
                "total_bars": len(output_values),
                "valid_values": valid_n,
                "warmup_or_missing": warmup_n,
            },
        )
