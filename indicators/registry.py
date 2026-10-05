"""
indicators/registry.py

Registry for discovering and instantiating indicator calculators.
Maintains the mapping between an indicator_name (e.g., 'rsi') and its class.
"""

from __future__ import annotations

import logging
from typing import Type

from indicators.calculator import IndicatorCalculator
from indicators.rsi import RsiCalculator

logger = logging.getLogger(__name__)


class IndicatorRegistry:
    """
    Central registry for available indicators.
    Allows dynamic lookup without hardcoding specific subclasses everywhere.
    """

    def __init__(self) -> None:
        self._calculators: dict[str, Type[IndicatorCalculator]] = {}

    def register(self, name: str, calc_class: Type[IndicatorCalculator]) -> None:
        """Register a new calculator class under the given name."""
        name = name.lower()
        if name in self._calculators:
            logger.warning("Overwriting existing indicator registration for %s", name)
        self._calculators[name] = calc_class

    def get_calculator(self, name: str) -> IndicatorCalculator:
        """
        Instantiate and return the calculator for the given name.
        
        Raises:
            KeyError: if the indicator is not registered.
        """
        name = name.lower()
        if name not in self._calculators:
            raise KeyError(f"Indicator '{name}' not found in registry.")
        calc_class = self._calculators[name]
        return calc_class()

    def list_available(self) -> list[str]:
        """Return a sorted list of registered indicator names."""
        return sorted(self._calculators.keys())


# Global singleton registry
registry = IndicatorRegistry()

# Pre-register built-in indicators
registry.register("rsi", RsiCalculator)
