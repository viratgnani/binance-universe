"""
research_discovery/outcome_definitions.py

Factory functions for reusable outcome sets.
These define standard return horizons for discovery experiments.
"""

from __future__ import annotations

from research.models import OutcomeDefinition


def standard_short_term_outcomes(price_feature: str = "close") -> list[OutcomeDefinition]:
    """
    Standard forward return horizons for intraday discovery.
    Note: The frozen research engine expects 'price_feature' to name the column.
    We pass "close" here, which our DiscoveryDataAdapter will pass through.
    """
    horizons = [1, 3, 5, 10, 15, 30, 60]
    return [
        OutcomeDefinition(
            name=f"fwd_return_{h}m",
            horizon_minutes=h,
            price_feature=price_feature,
        )
        for h in horizons
    ]

def extended_intraday_outcomes(price_feature: str = "close") -> list[OutcomeDefinition]:
    """
    Extended forward return horizons up to 4 hours.
    """
    horizons = [5, 15, 30, 60, 120, 240]
    return [
        OutcomeDefinition(
            name=f"fwd_return_{h}m",
            horizon_minutes=h,
            price_feature=price_feature,
        )
        for h in horizons
    ]
