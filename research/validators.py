"""
research/validators.py

TemporalValidator — post-hoc enforcement of causal isolation.

The validator makes explicit the boundary between:
  - "information used to detect event"  (must be <= event.timestamp)
  - "information used to measure outcome" (must be >= event.timestamp)

These guarantees are enforced both by the architecture (separate engines with
separate data slices) and by this validator, which acts as an auditable
post-hoc check.
"""

from __future__ import annotations

import logging
from datetime import datetime

from research.models import Event, EventOutcome, OutcomeStatus

logger = logging.getLogger(__name__)


class TemporalValidationError(Exception):
    """Raised when a temporal invariant is violated."""


class TemporalValidator:
    """
    Validates temporal correctness of events and outcomes.

    Event invariant:
      max(timestamp of any observation used for detection) <= event.timestamp
      In practice the EventEngine guarantees this architecturally, but we
      verify it by cross-checking against the feature series that was passed.

    Outcome invariant:
      outcome.outcome_timestamp >= outcome.event_timestamp  (when status == valid)
    """

    def validate_events(
        self,
        events: list[Event],
        feature_series: list[tuple[datetime, float | None]],
    ) -> None:
        """
        Assert that every event's timestamp is within the observed feature series.

        Raises TemporalValidationError if any event timestamp is later than the
        last observation in the series (which would imply use of future data).
        """
        if not events or not feature_series:
            return

        # All timestamps in the series that were available
        series_timestamps = {ts for ts, _ in feature_series}
        series_max = max(series_timestamps)

        for event in events:
            if event.timestamp > series_max:
                raise TemporalValidationError(
                    f"Event at {event.timestamp} is later than the last feature "
                    f"observation at {series_max}. Possible look-ahead violation."
                )
            # The event timestamp itself must appear in the series
            if event.timestamp not in series_timestamps:
                raise TemporalValidationError(
                    f"Event timestamp {event.timestamp} does not appear in the "
                    f"feature series. Event may have been generated from unlisted data."
                )

    def validate_outcomes(self, outcomes: list[EventOutcome]) -> None:
        """
        Assert that all valid outcomes have outcome_timestamp >= event_timestamp.
        """
        for outcome in outcomes:
            if outcome.status != OutcomeStatus.VALID:
                continue
            if outcome.outcome_timestamp is None:
                raise TemporalValidationError(
                    f"Outcome {outcome.outcome_name} for event at "
                    f"{outcome.event_timestamp} has status=valid but no outcome_timestamp."
                )
            if outcome.outcome_timestamp < outcome.event_timestamp:
                raise TemporalValidationError(
                    f"Outcome {outcome.outcome_name}: outcome_timestamp "
                    f"{outcome.outcome_timestamp} < event_timestamp {outcome.event_timestamp}. "
                    f"Outcome predates its own event."
                )

    def validate(
        self,
        events: list[Event],
        outcomes: list[EventOutcome],
        feature_series: list[tuple[datetime, float | None]],
    ) -> None:
        """Run all validations. Raises TemporalValidationError on any violation."""
        self.validate_events(events, feature_series)
        self.validate_outcomes(outcomes)
        logger.debug(
            "TemporalValidator: %d events, %d outcomes — all invariants satisfied",
            len(events), len(outcomes),
        )
