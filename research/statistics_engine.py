"""
research/statistics_engine.py

Descriptive Statistics Engine.

Computes central tendency, dispersion, quantiles, and sample quality metrics
over populations of EventOutcomes. Grouping is deterministic and inputs are
explicitly sorted to guarantee stable results.

Algorithm for Quantiles:
  Linear interpolation between empirical order statistics.
  index = (N - 1) * p
  lower = floor(index)
  upper = lower + 1
  value = x[lower] * (1 - fraction) + x[upper] * fraction
"""

from __future__ import annotations

import logging
import math
from collections import defaultdict
from statistics import mean, median

from research.models import (
    DescriptiveStats,
    EventOutcome,
    OutcomeDefinition,
    OutcomeStatus,
    OutcomeType,
    Quantiles,
    ReturnStats,
    SampleQuality,
    StatisticsResult,
)

logger = logging.getLogger(__name__)


def _is_valid_number(val: float | None) -> bool:
    if val is None:
        return False
    if math.isnan(val) or math.isinf(val):
        return False
    return True


def _calculate_quantile(sorted_vals: list[float], p: float) -> float | None:
    """
    Standard linear interpolation quantile.
    sorted_vals MUST be pre-sorted.
    """
    n = len(sorted_vals)
    if n == 0:
        return None
    if n == 1:
        return sorted_vals[0]
        
    idx = (n - 1) * p
    lower = int(idx)
    upper = lower + 1
    fraction = idx - lower
    
    if upper >= n:
        return sorted_vals[-1]
        
    return sorted_vals[lower] * (1.0 - fraction) + sorted_vals[upper] * fraction


def _sample_std(vals: list[float], m: float) -> float | None:
    """Sample standard deviation (ddof=1)."""
    n = len(vals)
    if n < 2:
        return None
    variance = sum((x - m) ** 2 for x in vals) / (n - 1)
    return math.sqrt(variance)


class StatisticsEngine:
    """
    Computes descriptive statistics on event outcomes.
    """

    def compute(
        self,
        outcomes: list[EventOutcome],
        outcome_defs: list[OutcomeDefinition],
        groupings: list[str],
    ) -> list[StatisticsResult]:
        """
        Compute statistics for the given grouping dimensions.

        Supported groupings:
          "overall", "symbol", "horizon", "symbol_horizon"
        """
        def_map = {od.name: od for od in outcome_defs}
        results: list[StatisticsResult] = []

        # We first split outcomes by their outcome_name (so we process fwd_1m independently from fwd_3m)
        by_outcome: dict[str, list[EventOutcome]] = defaultdict(list)
        for o in outcomes:
            by_outcome[o.outcome_name].append(o)

        for oname, pop in by_outcome.items():
            od = def_map.get(oname)
            if not od:
                continue

            for gtype in groupings:
                grouped = self._group_population(pop, gtype)
                for (sym_key, hor_key), group_pop in sorted(grouped.items()):
                    res = self._compute_group(group_pop, gtype, sym_key, hor_key, od)
                    results.append(res)

        return results

    def _group_population(
        self, pop: list[EventOutcome], grouping_type: str
    ) -> dict[tuple[str | None, str | None], list[EventOutcome]]:
        """
        Group outcomes. Returns dict of (symbol, horizon) -> list[EventOutcome].
        None is used when a dimension is aggregated over.
        """
        groups: dict[tuple[str | None, str | None], list[EventOutcome]] = defaultdict(list)
        
        for o in pop:
            sym_key = o.symbol if "symbol" in grouping_type else None
            hor_key = str(o.horizon_minutes) if "horizon" in grouping_type else None
            groups[(sym_key, hor_key)].append(o)
            
        return dict(groups)

    def _compute_group(
        self,
        pop: list[EventOutcome],
        grouping_type: str,
        symbol: str | None,
        horizon: str | None,
        od: OutcomeDefinition,
    ) -> StatisticsResult:
        """Compute statistics for one grouped subpopulation."""
        
        # 1. Sample Quality
        event_count = len(pop)
        valid_outcomes = []
        missing_count = 0
        insufficient_count = 0
        invalid_count = 0

        for o in pop:
            if o.status == OutcomeStatus.MISSING_PRICE:
                missing_count += 1
            elif o.status == OutcomeStatus.INSUFFICIENT_FUTURE_DATA:
                insufficient_count += 1
            elif o.status == OutcomeStatus.VALID:
                if _is_valid_number(o.outcome_value):
                    valid_outcomes.append(o.outcome_value)
                else:
                    invalid_count += 1
            elif o.status == OutcomeStatus.INVALID:
                invalid_count += 1

        sample = SampleQuality(
            event_count=event_count,
            valid_outcome_count=len(valid_outcomes),
            missing_outcome_count=missing_count,
            insufficient_future_data_count=insufficient_count,
            invalid_outcome_count=invalid_count,
        )

        n = len(valid_outcomes)
        sorted_vals = sorted(valid_outcomes)

        # 2. Descriptive Stats
        desc = DescriptiveStats()
        if n > 0:
            desc.mean = mean(sorted_vals)
            desc.median = median(sorted_vals)
            desc.min = sorted_vals[0]
            desc.max = sorted_vals[-1]
            desc.std = _sample_std(sorted_vals, desc.mean)

        # 3. Quantiles
        quantiles = Quantiles(
            p01=_calculate_quantile(sorted_vals, 0.01),
            p05=_calculate_quantile(sorted_vals, 0.05),
            p10=_calculate_quantile(sorted_vals, 0.10),
            p25=_calculate_quantile(sorted_vals, 0.25),
            p50=_calculate_quantile(sorted_vals, 0.50),
            p75=_calculate_quantile(sorted_vals, 0.75),
            p90=_calculate_quantile(sorted_vals, 0.90),
            p95=_calculate_quantile(sorted_vals, 0.95),
            p99=_calculate_quantile(sorted_vals, 0.99),
        )

        # 4. Return Stats (only if return_like)
        ret_stats = None
        if od.outcome_type == OutcomeType.RETURN_LIKE:
            ret_stats = ReturnStats()
            if n > 0:
                pos = [x for x in sorted_vals if x > 0]
                neg = [x for x in sorted_vals if x < 0]
                zeros = n - len(pos) - len(neg)
                
                ret_stats.positive_count = len(pos)
                ret_stats.negative_count = len(neg)
                ret_stats.zero_count = zeros
                ret_stats.win_rate = len(pos) / n
                ret_stats.mean_positive = mean(pos) if pos else None
                ret_stats.mean_negative = mean(neg) if neg else None
                ret_stats.largest_gain = sorted_vals[-1]
                ret_stats.largest_loss = sorted_vals[0]
            else:
                ret_stats.win_rate = None

        # Determine research_id
        rid = pop[0].research_id if pop else "unknown"

        return StatisticsResult(
            research_id=rid,
            symbol=symbol,
            horizon=horizon,
            grouping_type=grouping_type,
            outcome_name=od.name,
            outcome_type=od.outcome_type,
            sample=sample,
            descriptive=desc,
            returns=ret_stats,
            quantiles=quantiles,
        )
