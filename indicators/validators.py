"""
indicators/validators.py

Validation utilities for the Indicator Layer to guarantee temporal safety.
"""

from __future__ import annotations

from datetime import datetime


class TemporalValidationError(Exception):
    """Raised when temporal invariants (e.g. strict chronological ordering) are violated."""
    pass


def validate_no_duplicate_timestamps(series: list[tuple[datetime, float | None]]) -> None:
    """
    Ensure the series contains exactly one observation per timestamp.
    Assumes the series is already sorted by timestamp.
    
    Raises:
        TemporalValidationError: If duplicate timestamps exist.
    """
    if not series:
        return

    prev_ts = series[0][0]
    for ts, _ in series[1:]:
        if ts == prev_ts:
            raise TemporalValidationError(f"Duplicate timestamp detected: {ts}")
        if ts < prev_ts:
            raise TemporalValidationError(f"Series is not sorted correctly. {ts} < {prev_ts}")
        prev_ts = ts
