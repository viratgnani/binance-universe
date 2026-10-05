"""
universe/normalization.py

Min-max normalization of raw MarketMetrics into the [0, 1] range required
by the ranking engine.

Design:
  - Operates on the full batch of metrics so min/max are computed globally.
  - Contracts with metrics_failed=True or any None ranking metric are excluded
    from the normalisation batch (they cannot be ranked).
  - spread_bps is inverted so that a tighter spread → higher normalized score.
  - epsilon prevents division by zero when all values in a column are identical.

This module contains ONLY normalisation arithmetic.
No API calls, no ranking logic, no persistence.
"""

from __future__ import annotations

import logging

from universe.models import MarketMetrics, NormalizedMetrics

logger = logging.getLogger(__name__)

# Small constant to prevent division by zero when all values in a column
# are identical (max - min == 0).
_EPSILON: float = 1e-10


def normalize_metrics(
    metrics_list: list[MarketMetrics],
) -> tuple[list[NormalizedMetrics], list[str]]:
    """
    Produce min-max-normalised metrics for all contracts that have complete
    ranking inputs.

    Parameters
    ----------
    metrics_list:
        Raw metrics for every eligible contract (including failed ones).

    Returns
    -------
    normalized:
        NormalizedMetrics list — only contracts with all three ranking inputs
        (volume, OI, spread) present and non-failed.
    skipped_symbols:
        Symbols excluded from normalization (failed or incomplete metrics).
    """
    # Partition into rankable (have all three) vs spread-missing vs fully skipped
    rankable: list[MarketMetrics] = []            # has volume + OI + spread
    rankable_no_spread: list[MarketMetrics] = []  # has volume + OI, no spread
    skipped: list[str] = []

    for m in metrics_list:
        if m.metrics_failed:
            skipped.append(m.symbol)
            logger.debug("%s: excluded from normalization (metrics_failed=True)", m.symbol)
        elif m.volume_24h_quote is None or m.open_interest is None:
            skipped.append(m.symbol)
            logger.debug(
                "%s: excluded from normalization (volume=%s, OI=%s)",
                m.symbol, m.volume_24h_quote, m.open_interest,
            )
        elif m.spread_bps is None:
            rankable_no_spread.append(m)
        else:
            rankable.append(m)

    all_rankable = rankable + rankable_no_spread

    if not all_rankable:
        logger.warning("No contracts with complete metrics — normalization produces empty list")
        return [], skipped

    if skipped:
        logger.info(
            "Normalization: %d with spread, %d without spread, %d skipped",
            len(rankable),
            len(rankable_no_spread),
            len(skipped),
        )

    # Compute per-column min / max across ALL rankable contracts (with and without spread)
    volumes = [m.volume_24h_quote for m in all_rankable]  # type: ignore[misc]
    oi_vals = [m.open_interest for m in all_rankable]      # type: ignore[misc]

    vol_min, vol_max = min(volumes), max(volumes)
    oi_min, oi_max = min(oi_vals), max(oi_vals)

    # Spread min/max computed only from contracts that have spread data
    spr_min, spr_max = (None, None)
    if rankable:
        spreads = [m.spread_bps for m in rankable]  # type: ignore[misc]
        spr_min, spr_max = min(spreads), max(spreads)

    def _normalize(value: float, mn: float, mx: float) -> float:
        return (value - mn) / (mx - mn + _EPSILON)

    normalized: list[NormalizedMetrics] = []
    for m in all_rankable:
        norm_volume = _normalize(m.volume_24h_quote, vol_min, vol_max)  # type: ignore[arg-type]
        norm_oi = _normalize(m.open_interest, oi_min, oi_max)           # type: ignore[arg-type]

        if m.spread_bps is not None and spr_min is not None and spr_max is not None:
            norm_spread_raw = _normalize(m.spread_bps, spr_min, spr_max)   # type: ignore[arg-type]
            norm_spread = 1.0 - norm_spread_raw
        else:
            # No spread data: use 0.5 as a neutral mid-point so the contract
            # is neither rewarded nor penalised on the spread dimension.
            norm_spread = 0.5

        normalized.append(
            NormalizedMetrics(
                symbol=m.symbol,
                norm_volume=round(norm_volume, 8),
                norm_oi=round(norm_oi, 8),
                norm_spread=round(norm_spread, 8),
            )
        )

    logger.debug("Normalization complete: %d contracts", len(normalized))
    return normalized, skipped
