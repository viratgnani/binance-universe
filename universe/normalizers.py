"""
universe/normalizers.py

Interchangeable normalization methods for the ranking pipeline.

Design
------
All normalizers share the same interface as the existing normalize_metrics()
function so they can be substituted into the ranking pipeline without any
changes to upstream or downstream code.

    normalizer.normalize(metrics_list) -> (list[NormalizedMetrics], list[str])

The four concrete implementations are:

  MinMaxNormalizer          — V1 baseline, delegates to normalize_metrics()
  LogMinMaxNormalizer       — log1p transform on volume & OI, then min-max
  PercentileNormalizer      — empirical percentile rank → [0, 1]
  WinsorizedMinMaxNormalizer— clip to [p_lo, p_hi] percentiles, then min-max

All implementations preserve:
  - spread direction: lower spread_bps = better = higher norm_spread
  - missing spread fallback: norm_spread = 0.5 (neutral, neither rewarded nor penalised)
  - identical inputs → identical outputs (determinism)
  - contracts with missing volume or OI are skipped (returned in skipped list)
  - no NaN or Inf values in output

This module contains ONLY normalization arithmetic.
No Binance API calls, no ranking logic, no persistence.
"""

from __future__ import annotations

import logging
import math
from abc import ABC, abstractmethod

from universe.models import MarketMetrics, NormalizedMetrics
from universe.normalization import normalize_metrics  # V1 baseline implementation

logger = logging.getLogger(__name__)

# Small epsilon to prevent division by zero when max == min.
_EPSILON: float = 1e-10


# =========================================================================== #
#  Shared helpers
# =========================================================================== #


def _percentile(data: list[float], p: float) -> float:
    """
    Compute the p-th percentile (0–100) via linear interpolation.
    Returns 0.0 for empty input.
    """
    if not data:
        return 0.0
    sorted_d = sorted(data)
    n = len(sorted_d)
    if n == 1:
        return sorted_d[0]
    idx = (p / 100.0) * (n - 1)
    lo = int(idx)
    hi = min(lo + 1, n - 1)
    frac = idx - lo
    return sorted_d[lo] + frac * (sorted_d[hi] - sorted_d[lo])


def _partition(
    metrics_list: list[MarketMetrics],
) -> tuple[list[MarketMetrics], list[MarketMetrics], list[str]]:
    """
    Partition raw metrics into:
      rankable         — has volume + OI + spread
      rankable_no_spread — has volume + OI but no spread
      skipped          — failed metrics OR missing volume/OI

    This is the canonical partitioning rule used by ALL normalizers.
    """
    rankable: list[MarketMetrics] = []
    rankable_no_spread: list[MarketMetrics] = []
    skipped: list[str] = []

    for m in metrics_list:
        if m.metrics_failed:
            skipped.append(m.symbol)
        elif m.volume_24h_quote is None or m.open_interest is None:
            skipped.append(m.symbol)
        elif m.spread_bps is None:
            rankable_no_spread.append(m)
        else:
            rankable.append(m)

    return rankable, rankable_no_spread, skipped


def _apply_neutral_spread(
    m: MarketMetrics,
    norm_volume: float,
    norm_oi: float,
    spr_min: float | None,
    spr_max: float | None,
    norm_spread_fn,  # callable(spread_bps, spr_min, spr_max) -> float in [0,1]
) -> NormalizedMetrics:
    """
    Build a NormalizedMetrics, applying norm_spread_fn for contracts with spread
    data and assigning 0.5 (neutral) for those without.
    """
    if m.spread_bps is not None and spr_min is not None and spr_max is not None:
        norm_spread = norm_spread_fn(m.spread_bps, spr_min, spr_max)
    else:
        norm_spread = 0.5  # neutral fallback

    return NormalizedMetrics(
        symbol=m.symbol,
        norm_volume=round(max(0.0, min(1.0, norm_volume)), 8),
        norm_oi=round(max(0.0, min(1.0, norm_oi)), 8),
        norm_spread=round(max(0.0, min(1.0, norm_spread)), 8),
    )


# =========================================================================== #
#  Abstract base class
# =========================================================================== #


class NormalizerBase(ABC):
    """
    Abstract base class for all normalization methods.

    Subclasses must implement `normalize()`.  All other contract behaviour
    (spread direction, neutral spread fallback, skipping rules) is enforced
    through the shared `_partition()` helper and documented in this class.
    """

    @property
    @abstractmethod
    def name(self) -> str:
        """Short identifier string, e.g. 'minmax', 'log_minmax'."""

    @property
    @abstractmethod
    def description(self) -> str:
        """One-line human-readable description."""

    @abstractmethod
    def normalize(
        self,
        metrics_list: list[MarketMetrics],
    ) -> tuple[list[NormalizedMetrics], list[str]]:
        """
        Normalize raw metrics for a batch of contracts.

        Parameters
        ----------
        metrics_list:
            Raw metrics for every eligible contract (including failed ones).

        Returns
        -------
        normalized:
            NormalizedMetrics list for all rankable contracts.
        skipped_symbols:
            Symbols excluded from normalization (failed or missing volume/OI).
        """


# =========================================================================== #
#  A: V1 MinMax baseline — delegates to existing normalize_metrics()
# =========================================================================== #


class MinMaxNormalizer(NormalizerBase):
    """
    V1 baseline: pure min-max normalization.

    Delegates to the existing `normalize_metrics()` function so behaviour is
    guaranteed to be byte-for-byte identical to the current live pipeline.

    This is the control in all comparison experiments.
    """

    @property
    def name(self) -> str:
        return "minmax"

    @property
    def description(self) -> str:
        return "V1 baseline: min-max normalization (existing behavior)"

    def normalize(
        self,
        metrics_list: list[MarketMetrics],
    ) -> tuple[list[NormalizedMetrics], list[str]]:
        # Exact same behaviour as the current refresh pipeline
        return normalize_metrics(metrics_list)


# =========================================================================== #
#  B: Log + MinMax normalizer
# =========================================================================== #


class LogMinMaxNormalizer(NormalizerBase):
    """
    Log + min-max normalization for heavy-tailed metrics.

    Transform:
        volume' = log(1 + volume)
        oi'     = log(1 + oi)
        spread  — unchanged (do NOT apply log to spread)

    Then apply standard min-max to the transformed values.

    Rationale:
        In the live universe ETH/BTC have volume ~10B vs the median of ~3M.
        This 3000x range means 98.7% of contracts have norm_volume < 0.10
        under plain min-max.  The log transform compresses the dynamic range
        so the bulk of the universe occupies a wider normalized band.
    """

    @property
    def name(self) -> str:
        return "log_minmax"

    @property
    def description(self) -> str:
        return "Log(1+x) transform on volume & OI, then min-max normalization"

    def normalize(
        self,
        metrics_list: list[MarketMetrics],
    ) -> tuple[list[NormalizedMetrics], list[str]]:
        rankable, rankable_no_spread, skipped = _partition(metrics_list)
        all_rankable = rankable + rankable_no_spread

        if not all_rankable:
            logger.warning("[log_minmax] No rankable contracts.")
            return [], skipped

        # Log-transform volume and OI
        log_vols = [math.log1p(m.volume_24h_quote) for m in all_rankable]  # type: ignore[arg-type]
        log_ois  = [math.log1p(m.open_interest) for m in all_rankable]      # type: ignore[arg-type]
        raw_sprs = [m.spread_bps for m in rankable]  # type: ignore[misc]

        vol_min, vol_max = min(log_vols), max(log_vols)
        oi_min,  oi_max  = min(log_ois),  max(log_ois)
        spr_min = min(raw_sprs) if raw_sprs else None
        spr_max = max(raw_sprs) if raw_sprs else None

        def _mm(val: float, mn: float, mx: float) -> float:
            return (val - mn) / (mx - mn + _EPSILON)

        def _spread_norm(spr: float, mn: float, mx: float) -> float:
            # Lower spread is better → invert
            return 1.0 - _mm(spr, mn, mx)

        normalized: list[NormalizedMetrics] = []
        for m, lv, li in zip(all_rankable, log_vols, log_ois):
            nv = _mm(lv, vol_min, vol_max)
            ni = _mm(li, oi_min, oi_max)
            normalized.append(
                _apply_neutral_spread(m, nv, ni, spr_min, spr_max, _spread_norm)
            )

        logger.debug("[log_minmax] Normalized %d contracts, %d skipped", len(normalized), len(skipped))
        return normalized, skipped


# =========================================================================== #
#  C: Percentile / Rank normalizer
# =========================================================================== #


class PercentileNormalizer(NormalizerBase):
    """
    Percentile / empirical rank normalization.

    Each metric value is converted to its empirical percentile rank across
    the full batch of rankable contracts:

        rank position 1 (lowest)  → normalized = 0.0
        rank position N (highest) → normalized = 1.0

    For equal values, all ties receive the same percentile (average rank method).

    For spread: lower spread_bps is better, so the inversion is applied
    AFTER ranking (contract with lowest spread gets norm_spread = 1.0).

    Benefits:
    - Completely insensitive to extreme outliers — BTC/ETH volume pushes them
      to rank N regardless of the magnitude of their lead.
    - Produces a near-uniform distribution of normalized values.
    - Simple and explainable.

    Trade-off:
    - Loses information about the absolute size of gaps between contracts.
      e.g. Rank 1 and Rank 2 get norm values 1.0 and ~0.997 even if one has
      100x the volume of the other.
    """

    @property
    def name(self) -> str:
        return "percentile"

    @property
    def description(self) -> str:
        return "Empirical percentile rank normalization (rank / (N-1))"

    def normalize(
        self,
        metrics_list: list[MarketMetrics],
    ) -> tuple[list[NormalizedMetrics], list[str]]:
        rankable, rankable_no_spread, skipped = _partition(metrics_list)
        all_rankable = rankable + rankable_no_spread

        if not all_rankable:
            logger.warning("[percentile] No rankable contracts.")
            return [], skipped

        n = len(all_rankable)

        # Helper: compute percentile ranks (average tie method), return map symbol → rank_norm
        def _rank_norm(values: list[float], higher_is_better: bool = True) -> list[float]:
            """
            Assign each element a normalized rank in [0, 1].
            Ties get the average of their rank positions.
            higher_is_better=True  → max value gets 1.0.
            higher_is_better=False → min value gets 1.0 (used for spread, lower=better).
            """
            m = len(values)
            if m == 0:
                return []
            if m == 1:
                return [0.5]  # single element: neutral
            indexed = sorted(enumerate(values), key=lambda x: x[1])
            ranks = [0.0] * m

            i = 0
            while i < m:
                j = i
                # Find all equal elements
                while j < m - 1 and indexed[j + 1][1] == indexed[j][1]:
                    j += 1
                # Average rank for ties (0-indexed positions i..j)
                avg_rank_norm = (i + j) / 2.0 / max(m - 1, 1)
                for k in range(i, j + 1):
                    orig_idx = indexed[k][0]
                    ranks[orig_idx] = avg_rank_norm
                i = j + 1

            if higher_is_better:
                return ranks
            else:
                return [1.0 - r for r in ranks]

        vols = [m.volume_24h_quote for m in all_rankable]  # type: ignore[misc]
        ois  = [m.open_interest for m in all_rankable]      # type: ignore[misc]

        norm_vols = _rank_norm(vols, higher_is_better=True)
        norm_ois  = _rank_norm(ois,  higher_is_better=True)

        # Spread: only computed for contracts that have it
        # Build a separate ranking for spread among those with spread data
        spread_norm_map: dict[str, float] = {}
        if rankable:
            spr_values = [m.spread_bps for m in rankable]   # type: ignore[misc]
            # Lower spread = better, so invert
            spr_ranks = _rank_norm(spr_values, higher_is_better=False)
            for m, sr in zip(rankable, spr_ranks):
                spread_norm_map[m.symbol] = sr

        normalized: list[NormalizedMetrics] = []
        for m, nv, ni in zip(all_rankable, norm_vols, norm_ois):
            ns = spread_norm_map.get(m.symbol, 0.5)  # neutral if no spread data
            normalized.append(
                NormalizedMetrics(
                    symbol=m.symbol,
                    norm_volume=round(max(0.0, min(1.0, nv)), 8),
                    norm_oi=round(max(0.0, min(1.0, ni)), 8),
                    norm_spread=round(max(0.0, min(1.0, ns)), 8),
                )
            )

        logger.debug("[percentile] Normalized %d contracts, %d skipped", len(normalized), len(skipped))
        return normalized, skipped


# =========================================================================== #
#  D: Winsorized MinMax normalizer
# =========================================================================== #


class WinsorizedMinMaxNormalizer(NormalizerBase):
    """
    Winsorized min-max normalization.

    Before min-max normalization:
      1. Compute the lower_pct and upper_pct percentiles of each metric.
      2. Clip all values to [lower_cap, upper_cap].
      3. Apply min-max on the clipped distribution.

    This limits the distorting influence of extreme outliers while preserving
    the original scale and relative ordering within the bulk of the distribution.

    Parameters
    ----------
    lower_pct:
        Lower clip percentile (0–100).  Default 1.0 (1st percentile).
    upper_pct:
        Upper clip percentile (0–100).  Default 99.0 (99th percentile).

    Example
    -------
    With upper_pct=99, BTC/ETH volume is clipped to the 99th-percentile value
    (~1.25B in the live universe) so they still rank highest but no longer
    monopolize the top of the normalized scale in a way that compresses
    everything else to near-zero.
    """

    def __init__(self, lower_pct: float = 1.0, upper_pct: float = 99.0) -> None:
        if not (0.0 <= lower_pct < upper_pct <= 100.0):
            raise ValueError(
                f"Require 0 <= lower_pct < upper_pct <= 100, "
                f"got lower={lower_pct}, upper={upper_pct}"
            )
        self.lower_pct = lower_pct
        self.upper_pct = upper_pct

    @property
    def name(self) -> str:
        return f"winsorized_p{int(self.lower_pct)}_p{int(self.upper_pct)}"

    @property
    def description(self) -> str:
        return (
            f"Min-max after winsorizing to [{self.lower_pct}%, {self.upper_pct}%] "
            f"for volume & OI; spread unchanged"
        )

    def normalize(
        self,
        metrics_list: list[MarketMetrics],
    ) -> tuple[list[NormalizedMetrics], list[str]]:
        rankable, rankable_no_spread, skipped = _partition(metrics_list)
        all_rankable = rankable + rankable_no_spread

        if not all_rankable:
            logger.warning("[winsorized] No rankable contracts.")
            return [], skipped

        vols = [m.volume_24h_quote for m in all_rankable]  # type: ignore[misc]
        ois  = [m.open_interest for m in all_rankable]      # type: ignore[misc]
        sprs = [m.spread_bps for m in rankable]              # type: ignore[misc]

        # Compute winsorization boundaries
        vol_lo  = _percentile(vols, self.lower_pct)
        vol_hi  = _percentile(vols, self.upper_pct)
        oi_lo   = _percentile(ois,  self.lower_pct)
        oi_hi   = _percentile(ois,  self.upper_pct)
        spr_lo  = _percentile(sprs, self.lower_pct) if sprs else None
        spr_hi  = _percentile(sprs, self.upper_pct) if sprs else None

        def _clip(val: float, lo: float, hi: float) -> float:
            return max(lo, min(hi, val))

        def _mm(val: float, mn: float, mx: float) -> float:
            return (val - mn) / (mx - mn + _EPSILON)

        # Clip then min-max on clipped distribution
        # min of clipped = vol_lo, max of clipped = vol_hi
        def _norm_metric(val: float, lo: float, hi: float) -> float:
            clipped = _clip(val, lo, hi)
            return _mm(clipped, lo, hi)

        def _spread_norm(spr: float, spr_lo: float, spr_hi: float) -> float:
            clipped = _clip(spr, spr_lo, spr_hi)
            raw_norm = _mm(clipped, spr_lo, spr_hi)
            return 1.0 - raw_norm  # invert: lower spread = better

        normalized: list[NormalizedMetrics] = []
        for m in all_rankable:
            nv = _norm_metric(m.volume_24h_quote, vol_lo, vol_hi)  # type: ignore[arg-type]
            ni = _norm_metric(m.open_interest, oi_lo, oi_hi)       # type: ignore[arg-type]
            normalized.append(
                _apply_neutral_spread(m, nv, ni, spr_lo, spr_hi, _spread_norm)
            )

        logger.debug("[winsorized] Normalized %d contracts, %d skipped", len(normalized), len(skipped))
        return normalized, skipped


# =========================================================================== #
#  Factory
# =========================================================================== #


def get_all_normalizers() -> list[NormalizerBase]:
    """
    Return the default set of normalizers used in the comparison experiment.

    Order: baseline first, then candidates A→C.
    """
    return [
        MinMaxNormalizer(),
        LogMinMaxNormalizer(),
        PercentileNormalizer(),
        WinsorizedMinMaxNormalizer(lower_pct=1.0, upper_pct=99.0),
    ]


def get_normalizer_by_name(name: str) -> NormalizerBase:
    """
    Resolve a normalizer by its .name string.

    Used by the production refresh pipeline to instantiate the configured
    normalization method without importing specific subclasses.

    Parameters
    ----------
    name:
        Normalizer name, e.g. "log_minmax", "minmax", "percentile",
        "winsorized_p1_p99".

    Returns
    -------
    An instance of the matching :class:`NormalizerBase` subclass.

    Raises
    ------
    ValueError
        If no normalizer with that name exists.
    """
    registry: dict[str, NormalizerBase] = {n.name: n for n in get_all_normalizers()}
    if name not in registry:
        raise ValueError(
            f"Unknown normalization method '{name}'. "
            f"Valid values: {sorted(registry.keys())}"
        )
    return registry[name]
