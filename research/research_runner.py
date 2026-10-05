"""
research/research_runner.py

ResearchRunner — orchestrates the full event-study pipeline.

Pipeline
--------
  ResearchSpec
        ↓
  ResearchDataAdapter   (load feature + price series)
        ↓
  EventEngine           (causal detection — data <= T only)
        ↓
  OutcomeEngine         (forward measurement — data at T+H)
        ↓
  TemporalValidator     (post-hoc correctness check)
        ↓
  ResearchResult
        ↓
  ResearchResultStore   (append-only persistence)

The runner is deterministic: identical spec + stored data → identical result.
No statistics are computed here.
"""

from __future__ import annotations

import logging
from datetime import timedelta, timezone

from research.data_adapter import ResearchDataAdapter
from research.event_engine import EventEngine
from research.models import ResearchResult, ResearchSpec, StatisticsResult
from research.outcome_engine import OutcomeEngine
from research.result_store import ResearchResultStore
from research.statistics_engine import StatisticsEngine
from research.validators import TemporalValidator

logger = logging.getLogger(__name__)


class ResearchRunner:
    """
    Deterministic research pipeline orchestrator.
    """

    def __init__(
        self,
        adapter: ResearchDataAdapter | None = None,
        store: ResearchResultStore | None = None,
    ) -> None:
        self._adapter   = adapter or ResearchDataAdapter()
        self._store     = store   or ResearchResultStore()
        self._event_eng = EventEngine()
        self._outcome_eng = OutcomeEngine()
        self._stats_eng = StatisticsEngine()
        self._validator = TemporalValidator()

    def run(
        self,
        spec: ResearchSpec,
        compute_statistics: bool = False,
        group_by: list[str] | None = None,
    ) -> tuple[list[ResearchResult], list[StatisticsResult]]:
        """
        Execute the research spec for all symbols and return one ResearchResult per symbol.
        If compute_statistics is True, also computes and returns StatisticsResult objects
        according to the requested grouping dimensions.
        Results are persisted to the ResearchResultStore.
        """
        results: list[ResearchResult] = []
        all_outcomes = []

        for symbol in spec.symbols:
            logger.info("ResearchRunner: processing %s (%s)", symbol, spec.research_id)
            result = self._run_symbol(spec, symbol)
            results.append(result)
            all_outcomes.extend(result.outcomes)

        stats_results = []
        if compute_statistics and group_by:
            logger.info("ResearchRunner: computing statistics %s", group_by)
            stats_results = self._stats_eng.compute(all_outcomes, spec.outcome_definitions, group_by)
            written, skipped = self._store.save_statistics(spec.research_id, stats_results)
            logger.info(
                "ResearchRunner: statistics computed (+%d new, %d skipped)",
                written, skipped,
            )

        return results, stats_results

    # ------------------------------------------------------------------
    # Per-symbol pipeline
    # ------------------------------------------------------------------

    def _run_symbol(self, spec: ResearchSpec, symbol: str) -> ResearchResult:
        ed   = spec.event_definition
        ods  = spec.outcome_definitions

        # Maximum forward horizon — extend the data window far enough
        max_horizon = max(od.horizon for od in ods) if ods else timedelta(0)

        # 1. Load feature series for event detection (causal window only)
        # Hack for V1: if feature_name is 'rsi_14', load from indicator store.
        if ed.condition.feature_name.startswith("rsi"):
            from indicators.models import IndicatorDefinition
            # We assume RSI(14) is used for this experiment
            ind_def = IndicatorDefinition(indicator_name="rsi", indicator_version="v1", input_feature="mid_price", parameters={"period": 14})
            feature_series = self._adapter.get_indicator_series(
                symbol,
                "rsi",
                "v1",
                ind_def.parameter_hash(),
                spec.start_time,
                spec.end_time,
            )
        else:
            feature_series = self._adapter.get_feature_series(
                symbol,
                ed.condition.feature_name,
                spec.start_time,
                spec.end_time,
            )

        # 2. Load price series for outcome measurement (extended to cover all horizons)
        outcome_price_feature = ods[0].price_feature if ods else ed.condition.feature_name
        extended_end = spec.end_time + max_horizon + timedelta(minutes=1)
        price_series = self._adapter.get_price_series(
            symbol,
            outcome_price_feature,
            spec.start_time,
            extended_end,
        )

        # 3. Event detection (causal — receives only feature_series [start, end])
        events = self._event_eng.detect_events(
            spec.research_id,
            symbol,
            ed,
            feature_series,
        )

        # 4. Outcome calculation (forward-looking — receives full price_series)
        outcomes = self._outcome_eng.calculate_outcomes(events, ods, price_series)

        # 5. Temporal validation
        self._validator.validate(events, outcomes, feature_series)

        # 6. Persist
        written, skipped = self._store.save(spec.research_id, symbol, outcomes)
        logger.info(
            "ResearchRunner: %s — %d events, %d outcomes (+%d new, %d skipped)",
            symbol, len(events), len(outcomes), written, skipped,
        )

        return ResearchResult(
            research_id=spec.research_id,
            symbol=symbol,
            feature_version=spec.feature_version,
            engine_version=spec.engine_version,
            events=events,
            outcomes=outcomes,
            metadata={
                "written": written,
                "skipped": skipped,
                "feature_series_length": len(feature_series),
                "price_series_length": len(price_series),
            },
        )
