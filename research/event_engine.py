"""
research/event_engine.py

EventEngine — causal event detection.

STRICT TEMPORAL CONTRACT
------------------------
For every candidate timestamp T, the EventEngine receives ONLY observations
with timestamp <= T.  No future observation may influence the detection of
Event(T).  This is the foundational causal guarantee of the research engine.

Supported modes
---------------
CONDITION + EVERY_OBSERVATION
    Every observation satisfying the condition generates an event.

CONDITION + FIRST_ENTRY
    An event is generated only on the FIRST bar that satisfies the condition
    after a bar that did NOT satisfy it.  This tracks state transitions
    (non-satisfying -> satisfying), not sustained satisfying runs.

CROSSING
    Detects a sign change across the threshold boundary.

    cross_up:   previous valid observation <= threshold
                AND current observation > threshold
    cross_down: previous valid observation >= threshold
                AND current observation < threshold
    any:        either direction

    Observations with None values are skipped when tracking the previous state.
    The event timestamp is the current observation's timestamp.

No future observation may ever participate in determining a crossing.
"""

from __future__ import annotations

import logging
from datetime import datetime

from research.models import (
    CrossingDirection,
    Event,
    EventDefinition,
    EventMode,
    EventPolicy,
)

logger = logging.getLogger(__name__)

# A timestamped series: list of (timestamp, value | None)
TimestampedSeries = list[tuple[datetime, float | None]]


class EventEngine:
    """
    Detects events from a historical feature series.

    All inputs are sorted internally — callers need not pre-sort.
    The engine only ever evaluates data at or before each candidate timestamp.
    """

    def detect_events(
        self,
        research_id: str,
        symbol: str,
        event_def: EventDefinition,
        feature_series: TimestampedSeries,
    ) -> list[Event]:
        """
        Evaluate *event_def* against *feature_series* and return a list of Events.

        Parameters
        ----------
        research_id:    Identifier carried into each Event.
        symbol:         Symbol carried into each Event.
        event_def:      The EventDefinition to evaluate.
        feature_series: List of (timestamp, value) pairs.  None values are handled
                        per-mode: skipped for crossings, treated as non-satisfying
                        for conditions.
        """
        # Defensive: sort by timestamp ascending — guarantees chronological traversal
        series = sorted(feature_series, key=lambda x: x[0])

        def_hash = event_def.stable_hash()
        feature_name = event_def.condition.feature_name

        if event_def.event_mode == EventMode.CONDITION:
            return self._detect_condition(
                research_id, symbol, event_def, series, def_hash, feature_name
            )
        else:
            return self._detect_crossing(
                research_id, symbol, event_def, series, def_hash, feature_name
            )

    # ------------------------------------------------------------------
    # Condition mode
    # ------------------------------------------------------------------

    def _detect_condition(
        self,
        research_id: str,
        symbol: str,
        event_def: EventDefinition,
        series: TimestampedSeries,
        def_hash: str,
        feature_name: str,
    ) -> list[Event]:
        condition = event_def.condition
        policy    = event_def.event_policy
        events: list[Event] = []

        # State for FIRST_ENTRY mode
        # None = no prior observation seen yet; True = previously satisfied; False = not
        prev_satisfied: bool | None = None

        for ts, val in series:
            if val is None:
                # None observation: treated as non-satisfying for FIRST_ENTRY state tracking
                if policy == EventPolicy.FIRST_ENTRY:
                    prev_satisfied = False
                continue

            satisfied = condition.evaluate(val)

            emit = False
            if policy == EventPolicy.EVERY_OBSERVATION:
                emit = satisfied
            elif policy == EventPolicy.FIRST_ENTRY:
                # Emit only on the transition: not-satisfied -> satisfied
                if satisfied and (prev_satisfied is None or prev_satisfied is False):
                    emit = True
                prev_satisfied = satisfied

            if emit:
                events.append(Event(
                    research_id=research_id,
                    symbol=symbol,
                    timestamp=ts,
                    event_definition_hash=def_hash,
                    feature_name=feature_name,
                    feature_value=val,
                    direction=None,
                ))

        logger.debug(
            "EventEngine.condition: %s %s → %d events (policy=%s)",
            symbol, feature_name, len(events), policy.value,
        )
        return events

    # ------------------------------------------------------------------
    # Crossing mode
    # ------------------------------------------------------------------

    def _detect_crossing(
        self,
        research_id: str,
        symbol: str,
        event_def: EventDefinition,
        series: TimestampedSeries,
        def_hash: str,
        feature_name: str,
    ) -> list[Event]:
        condition = event_def.condition
        direction = event_def.crossing_direction
        events: list[Event] = []

        prev_val: float | None = None  # last non-None observation

        for ts, val in series:
            if val is None:
                # Skip None — do NOT update prev_val so we keep waiting for a valid observation
                continue

            if prev_val is not None:
                crossed_up   = (prev_val <= condition.threshold) and (val > condition.threshold)
                crossed_down = (prev_val >= condition.threshold) and (val < condition.threshold)

                emit_direction: CrossingDirection | None = None

                if direction == CrossingDirection.CROSS_UP and crossed_up:
                    emit_direction = CrossingDirection.CROSS_UP
                elif direction == CrossingDirection.CROSS_DOWN and crossed_down:
                    emit_direction = CrossingDirection.CROSS_DOWN
                elif direction == CrossingDirection.ANY:
                    if crossed_up:
                        emit_direction = CrossingDirection.CROSS_UP
                    elif crossed_down:
                        emit_direction = CrossingDirection.CROSS_DOWN

                if emit_direction is not None:
                    events.append(Event(
                        research_id=research_id,
                        symbol=symbol,
                        timestamp=ts,
                        event_definition_hash=def_hash,
                        feature_name=feature_name,
                        feature_value=val,
                        direction=emit_direction,
                    ))

            prev_val = val  # update only with non-None values

        logger.debug(
            "EventEngine.crossing: %s %s → %d events (dir=%s)",
            symbol, feature_name, len(events), direction.value,
        )
        return events
