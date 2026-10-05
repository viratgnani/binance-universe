"""
universe/top_n_selector.py

Assigns ACTIVE_TOP_100 / WATCHLIST membership based on rank.

This is intentionally a thin, single-responsibility module.
All ranking logic lives in ranking_engine.py.
All configuration lives in config.py.

The selector accepts a ranked list and marks each contract according to
whether its rank falls within the configured TOP_N threshold.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from universe.config import UniverseConfig, config as default_config
from universe.models import RankResult, UniverseStatus

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class SelectionResult:
    """Outcome of the Top-N selection step for a single contract."""

    symbol: str
    rank: int
    score: float
    universe_status: UniverseStatus


class TopNSelector:
    """
    Assigns :class:`UniverseStatus` to each ranked contract.

    Contracts with rank <= TOP_N become ACTIVE_TOP_100.
    All others become WATCHLIST.

    The TOP_N threshold is taken from :class:`UniverseConfig`.
    """

    def __init__(self, cfg: UniverseConfig = default_config) -> None:
        self._cfg = cfg

    def select(self, ranked: list[RankResult]) -> list[SelectionResult]:
        """
        Apply Top-N status assignment.

        Parameters
        ----------
        ranked:
            Fully-ranked list from :class:`RankingEngine.rank`.
            Must already be sorted by rank (rank 1 = highest score).

        Returns
        -------
        List of :class:`SelectionResult` in the same order as *ranked*.
        """
        top_n = self._cfg.TOP_N
        results: list[SelectionResult] = []

        for rr in ranked:
            status = (
                UniverseStatus.ACTIVE_TOP_100
                if rr.rank <= top_n
                else UniverseStatus.WATCHLIST
            )
            results.append(
                SelectionResult(
                    symbol=rr.symbol,
                    rank=rr.rank,
                    score=rr.score,
                    universe_status=status,
                )
            )

        active_count = sum(1 for r in results if r.universe_status == UniverseStatus.ACTIVE_TOP_100)
        watchlist_count = len(results) - active_count

        logger.info(
            "Top-%d selection: %d ACTIVE_TOP_100, %d WATCHLIST",
            top_n,
            active_count,
            watchlist_count,
        )
        return results
