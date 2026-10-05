"""
research_discovery/event_definitions.py

Reusable event primitives that compose frozen EventDefinitions.
These factories define the standard semantic language of the discovery lab.
"""

from __future__ import annotations

from research.models import (
    CrossingDirection,
    EventDefinition,
    EventMode,
    EventPolicy,
    Operator,
    ThresholdCondition,
)

# ---------------------------------------------------------------------------
# Price Move Events
# ---------------------------------------------------------------------------

def price_move_up(threshold_pct: float, feature: str = "return_5m") -> EventDefinition:
    """Event generated on every observation where the return > threshold_pct."""
    return EventDefinition(
        condition=ThresholdCondition(
            feature_name=feature,
            operator=Operator.GT,
            threshold=threshold_pct,
        ),
        event_mode=EventMode.CONDITION,
        event_policy=EventPolicy.EVERY_OBSERVATION,
    )

def price_move_down(threshold_pct: float, feature: str = "return_5m") -> EventDefinition:
    """Event generated on every observation where the return < -threshold_pct."""
    return EventDefinition(
        condition=ThresholdCondition(
            feature_name=feature,
            operator=Operator.LT,
            threshold=-abs(threshold_pct),
        ),
        event_mode=EventMode.CONDITION,
        event_policy=EventPolicy.EVERY_OBSERVATION,
    )


# ---------------------------------------------------------------------------
# Volume & Volatility Shock Events
# ---------------------------------------------------------------------------

def volume_shock(threshold_multiple: float = 5.0) -> EventDefinition:
    """
    Event generated exactly when volume crosses above X times its trailing median.
    Uses CROSSING mode so we capture the onset of the shock.
    """
    return EventDefinition(
        condition=ThresholdCondition(
            feature_name="relative_volume_vs_1h",
            operator=Operator.GT,
            threshold=threshold_multiple,
        ),
        event_mode=EventMode.CROSSING,
        crossing_direction=CrossingDirection.CROSS_UP,
    )

def volatility_shock(threshold_percentile: float = 0.95) -> EventDefinition:
    """
    Event generated exactly when volatility crosses into the top X percentile
    of its recent trailing distribution.
    """
    return EventDefinition(
        condition=ThresholdCondition(
            feature_name="volatility_pct_rank_1h",
            operator=Operator.GT,
            threshold=threshold_percentile,
        ),
        event_mode=EventMode.CROSSING,
        crossing_direction=CrossingDirection.CROSS_UP,
    )


# ---------------------------------------------------------------------------
# Extreme Candle Events
# ---------------------------------------------------------------------------

def extreme_candle_up(threshold_percentile: float = 0.01) -> EventDefinition:
    """
    Event generated when a single 1-minute candle's return > threshold.
    Note: We use absolute return vs a direct threshold for simplicity since
    the primitive specifies 'percentile', we should probably rename or use a 
    direct absolute threshold. Let's use a direct threshold on return_1m.
    """
    return EventDefinition(
        condition=ThresholdCondition(
            feature_name="return_1m",
            operator=Operator.GT,
            threshold=threshold_percentile,
        ),
        event_mode=EventMode.CONDITION,
        event_policy=EventPolicy.EVERY_OBSERVATION,
    )

def extreme_candle_down(threshold_percentile: float = 0.01) -> EventDefinition:
    """
    Event generated when a single 1-minute candle's return < -threshold.
    """
    return EventDefinition(
        condition=ThresholdCondition(
            feature_name="return_1m",
            operator=Operator.LT,
            threshold=-abs(threshold_percentile),
        ),
        event_mode=EventMode.CONDITION,
        event_policy=EventPolicy.EVERY_OBSERVATION,
    )


# ---------------------------------------------------------------------------
# Breakout / Breakdown Events
# ---------------------------------------------------------------------------

def breakout() -> EventDefinition:
    """
    Breakout above the trailing 24h high.
    The feature `distance_from_high_24h` is computed as: close(T) / rolling_max(1440) - 1
    So when it crosses above 0, it means close(T) > max(high).
    Note: feature library ensures the current candle is excluded from the reference high.
    """
    return EventDefinition(
        condition=ThresholdCondition(
            feature_name="distance_from_high_24h",
            operator=Operator.GT,
            threshold=0.0,
        ),
        event_mode=EventMode.CROSSING,
        crossing_direction=CrossingDirection.CROSS_UP,
    )

def breakdown() -> EventDefinition:
    """
    Breakdown below the trailing 24h low.
    `distance_from_low_24h` = close(T) / rolling_min(1440) - 1
    When it crosses below 0, close(T) < min(low).
    """
    return EventDefinition(
        condition=ThresholdCondition(
            feature_name="distance_from_low_24h",
            operator=Operator.LT,
            threshold=0.0,
        ),
        event_mode=EventMode.CROSSING,
        crossing_direction=CrossingDirection.CROSS_DOWN,
    )
