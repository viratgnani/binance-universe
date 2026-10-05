"""
universe/ranking_engine.py

Deterministic scoring and ranking of eligible perpetual contracts.

Scoring formula
---------------
Each contract receives a composite score in [0, 1]:

    score = VOLUME_WEIGHT  * norm_volume
          + OI_WEIGHT      * norm_oi
          + SPREAD_WEIGHT  * norm_spread

Where:
  norm_volume  — min-max-normalized 24h quote volume  (higher = more liquid)
  norm_oi      — min-max-normalized open interest     (higher = deeper market)
  norm_spread  — 1 - min-max-normalized spread_bps    (higher = tighter spread)

All three normalized inputs are already in [0, 1] and represent "higher is
better" after inversion of spread_bps in normalization.py.

Weights are configured in config.py.  They must sum to 1.0.

Determinism guarantee
---------------------
Primary sort   : score descending
Secondary sort : symbol ascending (alphabetical tie-breaker)

This ensures identical input always produces identical rank ordering,
even when multiple contracts share the same score.

This module contains ONLY scoring/ranking logic.
No API calls, no normalisation, no persistence.
"""

from __future__ import annotations

import logging

from universe.config import UniverseConfig, config as default_config
from universe.models import NormalizedMetrics, RankResult

logger = logging.getLogger(__name__)


class RankingEngine:
    """
    Stateless ranking engine.

    Accepts a list of :class:`NormalizedMetrics` and returns a fully-ranked
    list of :class:`RankResult` objects sorted by score (descending).
    """

    def __init__(self, cfg: UniverseConfig = default_config) -> None:
        self._cfg = cfg
        self._validate_weights()

    # ------------------------------------------------------------------ #
    #  Validation
    # ------------------------------------------------------------------ #

    def _validate_weights(self) -> None:
        """
        Ensure the configured weights sum to 1.0.

        Raises ValueError at startup if misconfigured so bad weights are
        caught immediately rather than silently skewing all rankings.
        """
        total = (
            self._cfg.VOLUME_WEIGHT
            + self._cfg.OI_WEIGHT
            + self._cfg.SPREAD_WEIGHT
        )
        if abs(total - 1.0) > 1e-9:
            raise ValueError(
                f"Ranking weights must sum to 1.0, got "
                f"VOLUME={self._cfg.VOLUME_WEIGHT} + "
                f"OI={self._cfg.OI_WEIGHT} + "
                f"SPREAD={self._cfg.SPREAD_WEIGHT} = {total:.10f}"
            )

    # ------------------------------------------------------------------ #
    #  Public interface
    # ------------------------------------------------------------------ #

    def rank(self, normalized: list[NormalizedMetrics]) -> list[RankResult]:
        """
        Score and rank all contracts.

        Parameters
        ----------
        normalized:
            Normalised metrics for every rankable contract.

        Returns
        -------
        Sorted list of :class:`RankResult` with ranks assigned 1..N.
        """
        if not normalized:
            logger.warning("RankingEngine.rank() called with empty input")
            return []

        scored: list[tuple[float, str, NormalizedMetrics]] = []

        for nm in normalized:
            score = (
                self._cfg.VOLUME_WEIGHT * nm.norm_volume
                + self._cfg.OI_WEIGHT   * nm.norm_oi
                + self._cfg.SPREAD_WEIGHT * nm.norm_spread
            )
            # Clamp to [0, 1] to handle any floating-point drift
            score = max(0.0, min(1.0, score))
            scored.append((score, nm.symbol, nm))

        # Primary: score DESC; Secondary: symbol ASC (deterministic tie-break)
        scored.sort(key=lambda t: (-t[0], t[1]))

        results: list[RankResult] = []
        for rank, (score, symbol, _) in enumerate(scored, start=1):
            results.append(
                RankResult(
                    symbol=symbol,
                    score=round(score, 8),
                    rank=rank,
                )
            )

        logger.info(
            "Ranking complete: %d contracts scored. "
            "Top: %s (%.4f)  |  Bottom: %s (%.4f)",
            len(results),
            results[0].symbol,
            results[0].score,
            results[-1].symbol,
            results[-1].score,
        )
        return results
