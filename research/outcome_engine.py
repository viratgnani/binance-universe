"""
research/outcome_engine.py

OutcomeEngine — forward outcome measurement.

INTENTIONALLY FORWARD-LOOKING
------------------------------
The OutcomeEngine is explicitly allowed to access data with timestamp > T,
because it measures what happened AFTER the event.  This is not a look-ahead
violation — it is the scientific intent.

The EventEngine and OutcomeEngine must never share a data slice.

Forward return formula
----------------------
  return(T, H) = price(T + H) / price(T) - 1

  where:
    T = event.timestamp
    H = outcome_definition.horizon  (timedelta)

Timestamp policy
----------------
  1. Look for an observation with timestamp == T + H exactly.
  2. If found and price is valid (> 0): status = valid, compute return.
  3. If the target timestamp falls after the last available observation:
       status = insufficient_future_data, value = None.
  4. If the target timestamp is within range but no exact match:
       status = missing_price, value = None.
  5. If price at T is missing or <= 0:
       status = missing_price, value = None.

No nearest-neighbour substitution.
No forward-fill.
No interpolation.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

from research.models import (
    Event,
    EventOutcome,
    OutcomeDefinition,
    OutcomeStatus,
)

logger = logging.getLogger(__name__)

TimestampedSeries = list[tuple[datetime, float | None]]


class OutcomeEngine:
    """
    Calculates forward outcomes for detected events.
    Operates on a price series covering T and beyond.
    """

    def calculate_outcomes(
        self,
        events: list[Event],
        outcome_defs: list[OutcomeDefinition],
        price_series: TimestampedSeries,
    ) -> list[EventOutcome]:
        """
        For each (event, outcome_def) pair, calculate the realised forward outcome.

        Parameters
        ----------
        events:       Detected events from the EventEngine.
        outcome_defs: List of OutcomeDefinitions specifying horizons.
        price_series: Full price series (timestamps covering both T and T+H).
                      Sorted ascending internally — callers need not pre-sort.
        """
        # Build an O(1) lookup: timestamp -> price
        # Defensive sort then build dict
        sorted_series = sorted(price_series, key=lambda x: x[0])
        price_map: dict[datetime, float | None] = {ts: v for ts, v in sorted_series}
        last_ts = sorted_series[-1][0] if sorted_series else None

        outcomes: list[EventOutcome] = []

        for event in events:
            for od in outcome_defs:
                outcome = self._calculate_one(event, od, price_map, last_ts)
                outcomes.append(outcome)

        logger.debug(
            "OutcomeEngine: %d events × %d outcomes = %d total",
            len(events), len(outcome_defs), len(outcomes),
        )
        return outcomes

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _calculate_one(
        self,
        event: Event,
        od: OutcomeDefinition,
        price_map: dict[datetime, float | None],
        last_ts: datetime | None,
    ) -> EventOutcome:
        base = EventOutcome(
            research_id=event.research_id,
            symbol=event.symbol,
            event_timestamp=event.timestamp,
            event_definition_hash=event.event_definition_hash,
            outcome_name=od.name,
            horizon_minutes=od.horizon_minutes,
            status=OutcomeStatus.MISSING_PRICE,  # default; overridden below
        )

        target_ts = event.timestamp + od.horizon

        # Price at event time
        price_at_t = price_map.get(event.timestamp)
        if price_at_t is None or price_at_t <= 0:
            base.status = OutcomeStatus.MISSING_PRICE
            return base

        # Determine status for the forward price
        if last_ts is not None and target_ts > last_ts:
            base.status = OutcomeStatus.INSUFFICIENT_FUTURE_DATA
            return base

        price_at_h = price_map.get(target_ts)
        if price_at_h is None or price_at_h <= 0:
            base.status = OutcomeStatus.MISSING_PRICE
            return base

        fwd_return = price_at_h / price_at_t - 1.0

        base.outcome_value = fwd_return
        base.outcome_timestamp = target_ts
        base.status = OutcomeStatus.VALID
        return base
