"""
indicators/__init__.py

Research Indicator Layer V1.

Provides a generic indicator engine with RSI as the first registered indicator.
Indicators are calculated from frozen Feature Layer V1 data — no live API calls.
"""

from indicators.registry import registry

__all__ = ["registry"]
