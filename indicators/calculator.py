"""
indicators/calculator.py

IndicatorCalculator protocol — the minimal interface that every indicator
must implement.

Each calculator receives:
  - symbol:        the contract identifier
  - price_series:  list of (timestamp, price) tuples, may be unsorted
  - definition:    the IndicatorDefinition describing parameters

And returns:
  - IndicatorSeries for that symbol

The calculator is responsible for:
  - Sorting inputs by timestamp before calculation
  - Validating input prices (reject NaN, Inf, zero, negative)
  - Returning None values for warm-up bars and invalid-input bars
  - Never accessing data beyond the current timestamp
"""

from __future__ import annotations

from datetime import datetime
from typing import Protocol, runtime_checkable

from indicators.models import IndicatorDefinition, IndicatorSeries


@runtime_checkable
class IndicatorCalculator(Protocol):
    """
    Minimal protocol for indicator calculators.

    All indicator implementations must satisfy this interface.
    The interface is intentionally small to remain extensible.
    """

    def calculate(
        self,
        symbol: str,
        price_series: list[tuple[datetime, float | None]],
        definition: IndicatorDefinition,
    ) -> IndicatorSeries:
        """
        Calculate the indicator for the given price series.

        Parameters
        ----------
        symbol:
            The contract symbol (e.g. 'BTCUSDT').
        price_series:
            List of (timestamp, price) tuples. May be in any order.
            Null/invalid prices follow the definition's missing_data_policy.
        definition:
            The IndicatorDefinition specifying parameters, version, etc.

        Returns
        -------
        IndicatorSeries with one IndicatorValue per input timestamp.
        Values are None during warm-up and for invalid input bars.
        The series is sorted ascending by timestamp.
        """
        ...
