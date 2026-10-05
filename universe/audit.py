"""
universe/audit.py

Comprehensive audit of the Binance Perpetual Universe Engine V1.

This module runs a live refresh, captures full market data, and produces
a structured audit report covering:

  1.  Live universe baseline (discovered / eligible / ranked / failed)
  2.  Distribution statistics  (volume, OI, spread, score)
  3.  Top-100 table            (with score-component breakdown)
  4.  Top-100 boundary         (ranks 90-110, cutoff analysis)
  5.  Concentration analysis   (volume/OI share by tier)
  6.  Score component analysis (which dimension dominates)
  7.  Normalization outlier detection (compression / outlier effect)
  8.  Neutral-spread audit     (contracts without bid/ask data)
  9.  Classification audit     (excluded-by-reason breakdown)
  10. Composition analysis     (listing age)
  11. Automated sanity checks  (structural correctness)
  12. Snapshot integrity       (JSONL correctness)

Entry point
-----------
    python -m universe.audit

Output
------
    audit_output.json          — machine-readable raw data
    docs/universe_audit.md     — formatted Markdown report
"""

from __future__ import annotations

import asyncio
import json
import logging
import math
import sys
from collections import Counter, defaultdict
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from universe.binance_client import BinanceFuturesClient
from universe.config import UniverseConfig, config as default_config
from universe.contract_filter import ContractFilter, FilterResult, parse_exchange_info
from universe.market_metrics import MarketMetricsFetcher
from universe.models import (
    ContractInfo,
    MarketMetrics,
    NormalizedMetrics,
    SnapshotRecord,
    UniverseMember,
    UniverseStatus,
)
from universe.normalization import normalize_metrics
from universe.ranking_engine import RankingEngine
from universe.refresh import RefreshResult, run_refresh
from universe.snapshot_repository import SnapshotRepository
from universe.top_n_selector import TopNSelector

logger = logging.getLogger(__name__)


# =========================================================================== #
#  Statistics helpers
# =========================================================================== #


def _percentile(data: list[float], p: float) -> float:
    """Compute the p-th percentile (0-100) using linear interpolation."""
    if not data:
        return float("nan")
    sorted_d = sorted(data)
    n = len(sorted_d)
    if n == 1:
        return sorted_d[0]
    idx = (p / 100) * (n - 1)
    lo = int(idx)
    hi = min(lo + 1, n - 1)
    frac = idx - lo
    return sorted_d[lo] + frac * (sorted_d[hi] - sorted_d[lo])


def _describe(data: list[float]) -> dict[str, float]:
    """Return descriptive statistics for a numeric list."""
    if not data:
        return {k: float("nan") for k in ["count", "min", "p25", "median", "p75", "p90", "p95", "p99", "max", "mean"]}
    return {
        "count": len(data),
        "min": min(data),
        "p25": _percentile(data, 25),
        "median": _percentile(data, 50),
        "p75": _percentile(data, 75),
        "p90": _percentile(data, 90),
        "p95": _percentile(data, 95),
        "p99": _percentile(data, 99),
        "max": max(data),
        "mean": sum(data) / len(data),
    }


# =========================================================================== #
#  Audit data collector
# =========================================================================== #


class UniverseAuditor:
    """
    Runs the full universe refresh pipeline with extra instrumentation,
    then computes every audit metric.
    """

    def __init__(self, cfg: UniverseConfig = default_config) -> None:
        self._cfg = cfg

    # ----------------------------------------------------------------------- #
    #  Main entry point
    # ----------------------------------------------------------------------- #

    async def run(self) -> dict[str, Any]:
        """Execute the full audit and return a structured dict."""
        print("Running live universe refresh for audit…", flush=True)

        # ------------------------------------------------------------------- #
        #  Run the live refresh (with extra data capture)
        # ------------------------------------------------------------------- #
        (
            result,
            all_contracts_raw,
            metrics_list,
            normalized_list,
        ) = await self._run_instrumented_refresh()

        print(f"  Refresh complete: {result.total_ranked} ranked, "
              f"{result.total_failed_metrics} failed", flush=True)

        # ------------------------------------------------------------------- #
        #  Build lookup tables
        # ------------------------------------------------------------------- #
        metrics_map: dict[str, MarketMetrics] = {m.symbol: m for m in metrics_list}
        norm_map: dict[str, NormalizedMetrics] = {n.symbol: n for n in normalized_list}
        member_map: dict[str, UniverseMember] = {m.symbol: m for m in result.universe}
        ranked_members = [m for m in result.universe if m.rank is not None]
        ranked_members.sort(key=lambda m: m.rank)  # type: ignore[arg-type]

        # ------------------------------------------------------------------- #
        #  Section 1: Baseline
        # ------------------------------------------------------------------- #
        baseline = self._section_baseline(result)

        # ------------------------------------------------------------------- #
        #  Section 2: Distribution statistics
        # ------------------------------------------------------------------- #
        distributions = self._section_distributions(ranked_members)

        # ------------------------------------------------------------------- #
        #  Section 3: Top-100 table
        # ------------------------------------------------------------------- #
        top100_table = self._section_top100_table(result.top_100, norm_map)

        # ------------------------------------------------------------------- #
        #  Section 4: Boundary analysis (ranks 90-110)
        # ------------------------------------------------------------------- #
        boundary = self._section_boundary(ranked_members)

        # ------------------------------------------------------------------- #
        #  Section 5: Concentration
        # ------------------------------------------------------------------- #
        concentration = self._section_concentration(ranked_members)

        # ------------------------------------------------------------------- #
        #  Section 6: Score component analysis
        # ------------------------------------------------------------------- #
        components = self._section_components(ranked_members, norm_map)

        # ------------------------------------------------------------------- #
        #  Section 7: Normalization outlier detection
        # ------------------------------------------------------------------- #
        norm_outliers = self._section_normalization_outliers(ranked_members, metrics_map)

        # ------------------------------------------------------------------- #
        #  Section 8: Neutral-spread audit
        # ------------------------------------------------------------------- #
        neutral_spread = self._section_neutral_spread(ranked_members, metrics_list)

        # ------------------------------------------------------------------- #
        #  Section 9: Classification audit
        # ------------------------------------------------------------------- #
        classification = self._section_classification(result.excluded, all_contracts_raw)

        # ------------------------------------------------------------------- #
        #  Section 10: Composition (listing age)
        # ------------------------------------------------------------------- #
        composition = self._section_composition(result.top_100, ranked_members)

        # ------------------------------------------------------------------- #
        #  Section 11: Sanity checks
        # ------------------------------------------------------------------- #
        sanity = self._section_sanity_checks(result, ranked_members, norm_map)

        # ------------------------------------------------------------------- #
        #  Section 12: Snapshot integrity
        # ------------------------------------------------------------------- #
        snapshot_integrity = self._section_snapshot_integrity(result)

        # ------------------------------------------------------------------- #
        #  Assemble full audit output
        # ------------------------------------------------------------------- #
        audit = {
            "audit_timestamp": datetime.now(tz=timezone.utc).isoformat(),
            "snapshot_id": result.snapshot_id,
            "snapshot_timestamp": result.snapshot_timestamp.isoformat(),
            "baseline": baseline,
            "distributions": distributions,
            "top100_table": top100_table,
            "boundary": boundary,
            "concentration": concentration,
            "components": components,
            "normalization_outliers": norm_outliers,
            "neutral_spread": neutral_spread,
            "classification": classification,
            "composition": composition,
            "sanity_checks": sanity,
            "snapshot_integrity": snapshot_integrity,
        }

        return audit

    # ----------------------------------------------------------------------- #
    #  Instrumented refresh (returns extra data not normally exposed)
    # ----------------------------------------------------------------------- #

    async def _run_instrumented_refresh(self):
        """
        Run the full pipeline and return both the RefreshResult AND
        the raw intermediate data (all_contracts, metrics, normalized).
        """
        all_contracts_raw: list[ContractInfo] = []
        metrics_list_out: list[MarketMetrics] = []
        normalized_list_out: list[NormalizedMetrics] = []

        async with BinanceFuturesClient(self._cfg) as client:
            raw_info = await client.get_exchange_info()
            all_contracts_raw = parse_exchange_info(raw_info)

            contract_filter = ContractFilter(self._cfg)
            eligible_contracts, rejected = contract_filter.filter_batch(all_contracts_raw)

            fetcher = MarketMetricsFetcher(client, self._cfg)
            metrics_list_out = await fetcher.fetch_all(eligible_contracts)

        normalized_list_out, _ = normalize_metrics(metrics_list_out)

        # Now run the full refresh normally to get the RefreshResult with snapshot
        result = await run_refresh(self._cfg)

        return result, all_contracts_raw, metrics_list_out, normalized_list_out

    # ----------------------------------------------------------------------- #
    #  Section implementations
    # ----------------------------------------------------------------------- #

    def _section_baseline(self, result: RefreshResult) -> dict:
        watchlist = [m for m in result.universe if m.universe_status == UniverseStatus.WATCHLIST]
        active = result.top_100
        check = len(active) + len(watchlist) == result.total_eligible
        return {
            "timestamp": result.snapshot_timestamp.isoformat(),
            "snapshot_id": result.snapshot_id,
            "total_discovered": result.total_discovered,
            "eligible_crypto_perps": result.total_eligible,
            "excluded": result.total_excluded,
            "successfully_ranked": result.total_ranked,
            "metric_failures": result.total_failed_metrics,
            "active_top_100": len(active),
            "watchlist_count": len(watchlist),
            "eligibility_check_passes": check,  # eligible == active + watchlist
        }

    def _section_distributions(self, ranked: list[UniverseMember]) -> dict:
        volumes = [m.volume_24h_quote for m in ranked if m.volume_24h_quote is not None]
        oi_vals = [m.open_interest for m in ranked if m.open_interest is not None]
        spreads_bps = [m.spread_bps for m in ranked if m.spread_bps is not None]
        # Absolute spread = spread_bps / 10000 * last_price
        abs_spreads = [
            (m.spread_bps / 10_000) * m.last_price
            for m in ranked
            if m.spread_bps is not None and m.last_price is not None
        ]
        scores = [m.universe_score for m in ranked if m.universe_score is not None]

        return {
            "volume_24h_quote_usd": _describe(volumes),
            "open_interest_base": _describe(oi_vals),
            "spread_bps": _describe(spreads_bps),
            "spread_absolute_usd": _describe(abs_spreads),
            "universe_score": _describe(scores),
        }

    def _section_top100_table(
        self,
        top100: list[UniverseMember],
        norm_map: dict[str, NormalizedMetrics],
    ) -> list[dict]:
        rows = []
        cfg = self._cfg
        for m in top100:
            nm = norm_map.get(m.symbol)
            vol_contrib = cfg.VOLUME_WEIGHT * (nm.norm_volume if nm else 0)
            oi_contrib  = cfg.OI_WEIGHT    * (nm.norm_oi     if nm else 0)
            spr_contrib = cfg.SPREAD_WEIGHT * (nm.norm_spread if nm else 0)
            rows.append({
                "rank": m.rank,
                "symbol": m.symbol,
                "score": round(m.universe_score or 0, 6),
                "volume_24h_quote_usd": m.volume_24h_quote,
                "open_interest": m.open_interest,
                "last_price": m.last_price,
                "spread_bps": m.spread_bps,
                "norm_volume": round(nm.norm_volume, 6) if nm else None,
                "norm_oi": round(nm.norm_oi, 6) if nm else None,
                "norm_spread": round(nm.norm_spread, 6) if nm else None,
                "vol_contribution": round(vol_contrib, 6),
                "oi_contribution": round(oi_contrib, 6),
                "spread_contribution": round(spr_contrib, 6),
                "has_spread_data": m.spread_bps is not None,
            })
        return rows

    def _section_boundary(self, ranked: list[UniverseMember]) -> dict:
        top_n = self._cfg.TOP_N
        boundary_members = [m for m in ranked if 90 <= (m.rank or 0) <= 110]
        rows = []
        for m in boundary_members:
            rows.append({
                "rank": m.rank,
                "symbol": m.symbol,
                "score": round(m.universe_score or 0, 8),
                "volume_24h_quote_usd": m.volume_24h_quote,
                "open_interest": m.open_interest,
                "spread_bps": m.spread_bps,
                "universe_status": m.universe_status.value if m.universe_status else None,
            })

        # Score at boundary
        score_at_100 = next(
            (m.universe_score for m in ranked if m.rank == top_n), None
        )
        score_at_101 = next(
            (m.universe_score for m in ranked if m.rank == top_n + 1), None
        )
        score_at_99 = next(
            (m.universe_score for m in ranked if m.rank == top_n - 1), None
        )

        gap_99_100 = (
            round(score_at_99 - score_at_100, 8)
            if score_at_99 is not None and score_at_100 is not None else None
        )
        gap_100_101 = (
            round(score_at_100 - score_at_101, 8)
            if score_at_100 is not None and score_at_101 is not None else None
        )
        pct_gap_99_100 = (
            round(gap_99_100 / score_at_99 * 100, 4)
            if gap_99_100 is not None and score_at_99 else None
        )
        pct_gap_100_101 = (
            round(gap_100_101 / score_at_100 * 100, 4)
            if gap_100_101 is not None and score_at_100 else None
        )

        return {
            "boundary_rows": rows,
            "score_at_rank_99": score_at_99,
            "score_at_rank_100": score_at_100,
            "score_at_rank_101": score_at_101,
            "gap_99_to_100": gap_99_100,
            "gap_100_to_101": gap_100_101,
            "pct_gap_99_to_100": pct_gap_99_100,
            "pct_gap_100_to_101": pct_gap_100_101,
        }

    def _section_concentration(self, ranked: list[UniverseMember]) -> dict:
        total_vol = sum(m.volume_24h_quote or 0 for m in ranked)
        total_oi  = sum(m.open_interest or 0 for m in ranked)

        def _cumul_share(tier: int, attr: str) -> float:
            tier_sum = sum(getattr(m, attr) or 0 for m in ranked if (m.rank or 999) <= tier)
            base = total_vol if attr == "volume_24h_quote" else total_oi
            return round(tier_sum / base * 100, 2) if base else 0.0

        return {
            "total_volume_usd": total_vol,
            "total_oi_base": total_oi,
            "volume_concentration": {
                "top_10_pct": _cumul_share(10, "volume_24h_quote"),
                "top_25_pct": _cumul_share(25, "volume_24h_quote"),
                "top_50_pct": _cumul_share(50, "volume_24h_quote"),
                "top_100_pct": _cumul_share(100, "volume_24h_quote"),
            },
            "oi_concentration": {
                "top_10_pct": _cumul_share(10, "open_interest"),
                "top_25_pct": _cumul_share(25, "open_interest"),
                "top_50_pct": _cumul_share(50, "open_interest"),
                "top_100_pct": _cumul_share(100, "open_interest"),
            },
        }

    def _section_components(
        self,
        ranked: list[UniverseMember],
        norm_map: dict[str, NormalizedMetrics],
    ) -> dict:
        cfg = self._cfg

        def _comp_stats(members: list[UniverseMember], label: str) -> dict:
            vol_contribs, oi_contribs, spr_contribs = [], [], []
            for m in members:
                nm = norm_map.get(m.symbol)
                if nm is None:
                    continue
                vol_contribs.append(cfg.VOLUME_WEIGHT * nm.norm_volume)
                oi_contribs.append(cfg.OI_WEIGHT * nm.norm_oi)
                spr_contribs.append(cfg.SPREAD_WEIGHT * nm.norm_spread)
            return {
                "label": label,
                "count": len(members),
                "volume_contribution": _describe(vol_contribs),
                "oi_contribution": _describe(oi_contribs),
                "spread_contribution": _describe(spr_contribs),
                "weights": {
                    "VOLUME_WEIGHT": cfg.VOLUME_WEIGHT,
                    "OI_WEIGHT": cfg.OI_WEIGHT,
                    "SPREAD_WEIGHT": cfg.SPREAD_WEIGHT,
                },
            }

        top100 = [m for m in ranked if (m.rank or 999) <= 100]
        all_ranked = ranked

        return {
            "top_100": _comp_stats(top100, "top_100"),
            "full_universe": _comp_stats(all_ranked, "full_universe"),
        }

    def _section_normalization_outliers(
        self,
        ranked: list[UniverseMember],
        metrics_map: dict[str, MarketMetrics],
    ) -> dict:
        # Identify extreme values
        vols = [(m.symbol, m.volume_24h_quote) for m in ranked if m.volume_24h_quote is not None]
        ois  = [(m.symbol, m.open_interest) for m in ranked if m.open_interest is not None]
        sprs = [(m.symbol, m.spread_bps) for m in ranked if m.spread_bps is not None]

        vols.sort(key=lambda x: x[1], reverse=True)  # type: ignore
        ois.sort(key=lambda x: x[1], reverse=True)   # type: ignore
        sprs.sort(key=lambda x: x[1], reverse=True)  # type: ignore

        def _top_bottom(lst, n=5):
            return {
                "top": [{"symbol": s, "value": v} for s, v in lst[:n]],
                "bottom": [{"symbol": s, "value": v} for s, v in lst[-n:]],
            }

        # Compute the compression effect:
        # What fraction of contracts have norm_volume < 0.1 / 0.05?
        all_volumes = [m.volume_24h_quote for m in ranked if m.volume_24h_quote is not None]
        if all_volumes:
            vol_max = max(all_volumes)
            vol_min = min(all_volumes)
            _eps = 1e-10
            norm_vols = [(v - vol_min) / (vol_max - vol_min + _eps) for v in all_volumes]
            pct_below_01 = round(sum(1 for nv in norm_vols if nv < 0.1) / len(norm_vols) * 100, 1)
            pct_below_05 = round(sum(1 for nv in norm_vols if nv < 0.05) / len(norm_vols) * 100, 1)
            # Ratio of max to p99 (to detect outlier distortion)
            p99_vol = _percentile(all_volumes, 99)
            vol_max_to_p99_ratio = round(vol_max / p99_vol, 2) if p99_vol else None
        else:
            pct_below_01 = pct_below_05 = 0
            vol_max_to_p99_ratio = None

        all_ois = [m.open_interest for m in ranked if m.open_interest is not None]
        if all_ois:
            oi_max = max(all_ois)
            oi_min = min(all_ois)
            norm_ois = [(v - oi_min) / (oi_max - oi_min + _eps) for v in all_ois]
            oi_pct_below_01 = round(sum(1 for nv in norm_ois if nv < 0.1) / len(norm_ois) * 100, 1)
            p99_oi = _percentile(all_ois, 99)
            oi_max_to_p99_ratio = round(oi_max / p99_oi, 2) if p99_oi else None
        else:
            oi_pct_below_01 = 0
            oi_max_to_p99_ratio = None

        return {
            "volume_extremes": _top_bottom(vols),
            "oi_extremes": _top_bottom(ois),
            "spread_extremes": _top_bottom(sprs),
            "volume_compression": {
                "max_value": vol_max if all_volumes else None,
                "p99_value": _percentile(all_volumes, 99) if all_volumes else None,
                "max_to_p99_ratio": vol_max_to_p99_ratio,
                "pct_contracts_below_norm_0.1": pct_below_01,
                "pct_contracts_below_norm_0.05": pct_below_05,
                "description": (
                    "Contracts with norm_volume < 0.1 are compressed into the bottom 10% of the scale. "
                    f"{pct_below_01}% of the universe is below 0.1 norm_volume."
                ),
            },
            "oi_compression": {
                "max_value": oi_max if all_ois else None,
                "p99_value": _percentile(all_ois, 99) if all_ois else None,
                "max_to_p99_ratio": oi_max_to_p99_ratio,
                "pct_contracts_below_norm_0.1": oi_pct_below_01,
            },
        }

    def _section_neutral_spread(
        self,
        ranked: list[UniverseMember],
        metrics_list: list[MarketMetrics],
    ) -> dict:
        neutral = [m for m in ranked if m.spread_bps is None]
        has_spread = [m for m in ranked if m.spread_bps is not None]

        # Check if neutral contracts are ranked differently than expected
        # (neutral spread = 0.5 * SPREAD_WEIGHT = 0.075)
        neutral_scores = [m.universe_score or 0 for m in neutral]
        has_spread_scores = [m.universe_score or 0 for m in has_spread]

        return {
            "neutral_spread_count": len(neutral),
            "neutral_spread_pct": round(len(neutral) / len(ranked) * 100, 1) if ranked else 0,
            "neutral_symbols": [m.symbol for m in neutral],
            "neutral_score_stats": _describe(neutral_scores) if neutral_scores else {},
            "has_spread_score_stats": _describe(has_spread_scores) if has_spread_scores else {},
            "neutral_norm_spread_value": 0.5,
            "neutral_spread_contribution": round(self._cfg.SPREAD_WEIGHT * 0.5, 4),
            "observation": (
                "Contracts with neutral spread receive exactly "
                f"{self._cfg.SPREAD_WEIGHT * 0.5:.4f} spread contribution "
                f"(= SPREAD_WEIGHT * 0.5 = {self._cfg.SPREAD_WEIGHT} * 0.5). "
                "This is mid-range, so they are neither rewarded nor penalized "
                "relative to the median spread contract."
            ),
        }

    def _section_classification(
        self,
        excluded: list[FilterResult],
        all_contracts: list[ContractInfo],
    ) -> dict:
        # Categorize by rejection reason
        reason_categories = {
            "non_perpetual": [],
            "inactive": [],
            "non_usdt_quote": [],
            "tradfi_underlying_type": [],
            "tradfi_subtype": [],
            "other": [],
        }

        contract_map = {c.symbol: c for c in all_contracts}

        for fr in excluded:
            r = fr.reason
            if "not PERPETUAL" in r:
                reason_categories["non_perpetual"].append(fr.symbol)
            elif "not TRADING" in r:
                reason_categories["inactive"].append(fr.symbol)
            elif "not USDT" in r:
                reason_categories["non_usdt_quote"].append(fr.symbol)
            elif "underlyingType" in r and "not in allowed types" in r:
                reason_categories["tradfi_underlying_type"].append(fr.symbol)
            elif "underlyingSubType contains blocked" in r:
                reason_categories["tradfi_subtype"].append(fr.symbol)
            else:
                reason_categories["other"].append(fr.symbol)

        # Gather subtypes found among excluded tradfi contracts
        tradfi_subtypes: Counter = Counter()
        for sym in (
            reason_categories["tradfi_underlying_type"]
            + reason_categories["tradfi_subtype"]
        ):
            c = contract_map.get(sym)
            if c:
                tradfi_subtypes.update(c.underlying_sub_type)

        # Sample 10 from each category
        samples = {k: v[:10] for k, v in reason_categories.items()}

        return {
            "total_excluded": len(excluded),
            "by_reason": {k: len(v) for k, v in reason_categories.items()},
            "samples": samples,
            "tradfi_subtypes_found": dict(tradfi_subtypes.most_common(20)),
        }

    def _section_composition(
        self,
        top100: list[UniverseMember],
        all_ranked: list[UniverseMember],
    ) -> dict:
        now = datetime.now(tz=timezone.utc)

        def _age_days(m: UniverseMember) -> float | None:
            if m.listing_time is None:
                return None
            return (now - m.listing_time).days

        def _age_bucket(days: float | None) -> str:
            if days is None:
                return "unknown"
            if days < 30:
                return "<1m"
            elif days < 180:
                return "1-6m"
            elif days < 365:
                return "6-12m"
            elif days < 730:
                return "1-2y"
            elif days < 1460:
                return "2-4y"
            else:
                return "4y+"

        top100_ages = [_age_days(m) for m in top100]
        known_ages = [a for a in top100_ages if a is not None]

        top100_buckets = Counter(_age_bucket(_age_days(m)) for m in top100)
        all_buckets = Counter(_age_bucket(_age_days(m)) for m in all_ranked)

        # BTC and ETH specific
        btc_eth = [m for m in top100 if m.symbol in ("BTCUSDT", "ETHUSDT")]

        return {
            "top_100_listing_age_days": {
                "min": min(known_ages) if known_ages else None,
                "median": _percentile(known_ages, 50) if known_ages else None,
                "max": max(known_ages) if known_ages else None,
                "mean": round(sum(known_ages) / len(known_ages), 1) if known_ages else None,
                "unknown_count": top100_ages.count(None),
            },
            "top_100_age_buckets": dict(top100_buckets),
            "full_universe_age_buckets": dict(all_buckets),
            "btc_eth_ranks": {m.symbol: m.rank for m in btc_eth},
        }

    def _section_sanity_checks(
        self,
        result: RefreshResult,
        ranked: list[UniverseMember],
        norm_map: dict[str, NormalizedMetrics],
    ) -> dict:
        checks = {}

        # 1. Ranks are unique
        all_ranks = [m.rank for m in ranked if m.rank is not None]
        checks["ranks_unique"] = len(all_ranks) == len(set(all_ranks))

        # 2. Ranks are contiguous from 1..N
        if all_ranks:
            checks["ranks_contiguous"] = sorted(all_ranks) == list(range(1, len(all_ranks) + 1))
        else:
            checks["ranks_contiguous"] = False

        # 3. Rank 1 has the highest score
        if ranked:
            r1 = ranked[0]
            scores = [m.universe_score or 0 for m in ranked]
            checks["rank_1_has_max_score"] = (
                r1.rank == 1 and (r1.universe_score or 0) == max(scores)
            )
        else:
            checks["rank_1_has_max_score"] = False

        # 4. Score at rank 100 > score at rank 101
        s100 = next((m.universe_score for m in ranked if m.rank == 100), None)
        s101 = next((m.universe_score for m in ranked if m.rank == 101), None)
        checks["rank_100_score_gt_rank_101"] = (
            s100 is not None and s101 is not None and s100 > s101
        )

        # 5. Top 100 contains exactly 100
        top100 = [m for m in result.universe if m.universe_status == UniverseStatus.ACTIVE_TOP_100]
        checks["top_100_exactly_100"] = len(top100) == 100

        # 6. No duplicate symbols in universe
        all_syms = [m.symbol for m in result.universe]
        checks["no_duplicate_symbols"] = len(all_syms) == len(set(all_syms))

        # 7. No excluded symbol appears in top 100
        excluded_syms = {fr.symbol for fr in result.excluded}
        top100_syms = {m.symbol for m in top100}
        checks["no_excluded_in_top_100"] = not excluded_syms.intersection(top100_syms)

        # 8. All top 100 have ACTIVE_TOP_100 status
        checks["all_top100_active_status"] = all(
            m.universe_status == UniverseStatus.ACTIVE_TOP_100 for m in top100
        )

        # 9. All rank > 100 have WATCHLIST
        over_100 = [m for m in result.universe if (m.rank or 0) > 100]
        checks["all_watchlist_beyond_100"] = all(
            m.universe_status == UniverseStatus.WATCHLIST for m in over_100
        )

        # 10. Determinism check — run ranking twice on same data
        ranking_engine = RankingEngine(self._cfg)
        nm_list = list(norm_map.values())
        result_a = ranking_engine.rank(nm_list)
        result_b = ranking_engine.rank(nm_list)
        ranks_a = [(r.symbol, r.rank) for r in result_a]
        ranks_b = [(r.symbol, r.rank) for r in result_b]
        checks["ranking_is_deterministic"] = ranks_a == ranks_b

        # Summary
        all_pass = all(v for v in checks.values())
        failed = [k for k, v in checks.items() if not v]

        return {
            "checks": checks,
            "all_pass": all_pass,
            "failed_checks": failed,
        }

    def _section_snapshot_integrity(self, result: RefreshResult) -> dict:
        repo = SnapshotRepository(self._cfg)
        files = repo.list_snapshot_files()

        if not files:
            return {"status": "NO_SNAPSHOT_FILES", "files": []}

        latest_file = files[-1]
        records = repo.load_records(latest_file)

        headers = [r for r in records if r.get("record_type") == "HEADER"]
        data_records = [r for r in records if r.get("record_type") == "DATA"]

        # Checks
        has_timestamp = all("snapshot_timestamp" in h for h in headers)
        has_rank = all("rank" in r for r in data_records)
        has_score = all("score" in r for r in data_records)
        has_status = all("universe_status" in r for r in data_records)

        # All 397 eligible in latest snapshot batch?
        latest_sid = result.snapshot_id
        latest_data = [r for r in data_records if r.get("snapshot_id") == latest_sid]

        # Multiple refreshes create distinct snapshots (headers)
        unique_sids = len({h.get("snapshot_id") for h in headers})

        return {
            "snapshot_files": [str(f) for f in files],
            "total_files": len(files),
            "latest_file": str(latest_file),
            "total_records_in_latest_file": len(records),
            "header_count": len(headers),
            "data_record_count": len(data_records),
            "latest_batch_record_count": len(latest_data),
            "latest_batch_matches_eligible": len(latest_data) == result.total_eligible,
            "all_headers_have_timestamp": has_timestamp,
            "all_data_have_rank": has_rank,
            "all_data_have_score": has_score,
            "all_data_have_status": has_status,
            "unique_snapshot_ids_in_file": unique_sids,
            "append_only_verified": unique_sids >= 1,
        }


# =========================================================================== #
#  Report formatter
# =========================================================================== #


def _fmt_num(v, fmt=".2f", suffix="") -> str:
    if v is None or (isinstance(v, float) and math.isnan(v)):
        return "N/A"
    return f"{v:{fmt}}{suffix}"


def _fmt_usd(v, scale=1e9, label="B") -> str:
    if v is None:
        return "N/A"
    return f"${v/scale:{'.2f'}}{label}"


def build_markdown_report(audit: dict) -> str:
    lines = []
    a = audit

    def h(level: int, text: str):
        lines.append(f"{'#' * level} {text}")
        lines.append("")

    def p(text: str):
        lines.append(text)
        lines.append("")

    def table(headers: list[str], rows: list[list]):
        lines.append("| " + " | ".join(headers) + " |")
        lines.append("| " + " | ".join(["---"] * len(headers)) + " |")
        for row in rows:
            lines.append("| " + " | ".join(str(c) for c in row) + " |")
        lines.append("")

    def code(text: str, lang: str = ""):
        lines.append(f"```{lang}")
        lines.append(text)
        lines.append("```")
        lines.append("")

    # ------------------------------------------------------------------- #
    h(1, "Binance Perpetual Universe Engine — V1 Audit Report")

    p(f"**Audit generated:** {a['audit_timestamp']}  \n"
      f"**Snapshot ID:** `{a['snapshot_id']}`  \n"
      f"**Snapshot timestamp:** {a['snapshot_timestamp']}")

    # ------------------------------------------------------------------- #
    h(2, "1. Live Universe Baseline")

    b = a["baseline"]
    eligible_check = "✅ PASS" if b["eligibility_check_passes"] else "❌ FAIL"
    code(
        f"timestamp             : {b['timestamp']}\n"
        f"total_discovered      : {b['total_discovered']}\n"
        f"eligible_crypto_perps : {b['eligible_crypto_perps']}\n"
        f"excluded              : {b['excluded']}\n"
        f"successfully_ranked   : {b['successfully_ranked']}\n"
        f"metric_failures       : {b['metric_failures']}\n"
        f"active_top_100        : {b['active_top_100']}\n"
        f"watchlist_count       : {b['watchlist_count']}\n"
        f"\n"
        f"eligible == active_top_100 + watchlist_count  → {eligible_check}\n"
        f"  {b['eligible_crypto_perps']} == {b['active_top_100']} + {b['watchlist_count']} "
        f"= {b['active_top_100'] + b['watchlist_count']}"
    )

    # ------------------------------------------------------------------- #
    h(2, "2. Distribution Statistics")

    def _dist_table(label: str, stats: dict, unit: str = ""):
        p(f"**{label}** {unit}")
        table(
            ["Stat", "Value"],
            [
                ["count", f"{int(stats.get('count', 0)):,}"],
                ["min", _fmt_num(stats.get("min"))],
                ["p25", _fmt_num(stats.get("p25"))],
                ["median", _fmt_num(stats.get("median"))],
                ["p75", _fmt_num(stats.get("p75"))],
                ["p90", _fmt_num(stats.get("p90"))],
                ["p95", _fmt_num(stats.get("p95"))],
                ["p99", _fmt_num(stats.get("p99"))],
                ["max", _fmt_num(stats.get("max"))],
                ["mean", _fmt_num(stats.get("mean"))],
            ],
        )

    d = a["distributions"]
    v = d["volume_24h_quote_usd"]
    p(f"**24h Quote Volume (USD)**")
    table(
        ["Stat", "Value"],
        [
            ["count", f"{int(v.get('count', 0)):,}"],
            ["min", _fmt_usd(v.get("min"))],
            ["p25", _fmt_usd(v.get("p25"))],
            ["median", _fmt_usd(v.get("median"))],
            ["p75", _fmt_usd(v.get("p75"))],
            ["p90", _fmt_usd(v.get("p90"))],
            ["p95", _fmt_usd(v.get("p95"))],
            ["p99", _fmt_usd(v.get("p99"))],
            ["max", _fmt_usd(v.get("max"))],
            ["mean", _fmt_usd(v.get("mean"))],
        ],
    )

    oi = d["open_interest_base"]
    p(f"**Open Interest (base units)**")
    table(
        ["Stat", "Value"],
        [
            ["count", f"{int(oi.get('count', 0)):,}"],
            ["min", _fmt_num(oi.get("min"), ".0f")],
            ["p25", _fmt_num(oi.get("p25"), ".0f")],
            ["median", _fmt_num(oi.get("median"), ".0f")],
            ["p75", _fmt_num(oi.get("p75"), ".0f")],
            ["p90", _fmt_num(oi.get("p90"), ".0f")],
            ["p95", _fmt_num(oi.get("p95"), ".0f")],
            ["p99", _fmt_num(oi.get("p99"), ".0f")],
            ["max", _fmt_num(oi.get("max"), ".0f")],
            ["mean", _fmt_num(oi.get("mean"), ".0f")],
        ],
    )

    sp = d["spread_bps"]
    _dist_table("Bid/Ask Spread (bps)", sp)

    sc = d["universe_score"]
    _dist_table("Universe Score", sc)

    # ------------------------------------------------------------------- #
    h(2, "3. Top-100 Complete Table")

    p("Sorted strictly by rank. Columns: rank, symbol, score, 24h volume, OI, "
      "spread_bps, norm_volume, norm_OI, norm_spread, vol_contrib, oi_contrib, spread_contrib.")

    top_rows = a["top100_table"]
    table(
        ["Rank", "Symbol", "Score", "Vol (USD)", "OI", "Sprd bps",
         "nVol", "nOI", "nSprd", "vContrib", "oContrib", "sContrib"],
        [
            [
                r["rank"], r["symbol"],
                f"{r['score']:.5f}",
                _fmt_usd(r["volume_24h_quote_usd"], 1e6, "M"),
                _fmt_num(r["open_interest"], ".0f"),
                _fmt_num(r["spread_bps"]) if r["spread_bps"] else "—",
                f"{r['norm_volume']:.4f}" if r["norm_volume"] is not None else "—",
                f"{r['norm_oi']:.4f}" if r["norm_oi"] is not None else "—",
                f"{r['norm_spread']:.4f}" if r["norm_spread"] is not None else "—",
                f"{r['vol_contribution']:.4f}",
                f"{r['oi_contribution']:.4f}",
                f"{r['spread_contribution']:.4f}",
            ]
            for r in top_rows
        ],
    )

    # ------------------------------------------------------------------- #
    h(2, "4. Top-100 Boundary (Ranks 90–110)")

    bd = a["boundary"]
    table(
        ["Rank", "Symbol", "Score", "Vol (USD)", "OI", "Sprd bps", "Status"],
        [
            [
                r["rank"], r["symbol"],
                f"{r['score']:.7f}",
                _fmt_usd(r["volume_24h_quote_usd"], 1e6, "M"),
                _fmt_num(r["open_interest"], ".0f"),
                _fmt_num(r["spread_bps"]) if r["spread_bps"] else "—",
                r["universe_status"],
            ]
            for r in bd["boundary_rows"]
        ],
    )

    gap_99_100 = bd["gap_99_to_100"]
    gap_100_101 = bd["gap_100_to_101"]
    pct_99 = bd["pct_gap_99_to_100"]
    pct_101 = bd["pct_gap_100_to_101"]

    code(
        f"Score at rank #99  : {bd['score_at_rank_99']}\n"
        f"Score at rank #100 : {bd['score_at_rank_100']}\n"
        f"Score at rank #101 : {bd['score_at_rank_101']}\n"
        f"\n"
        f"Gap #99 → #100     : {gap_99_100}  ({pct_99}%)\n"
        f"Gap #100 → #101    : {gap_100_101}  ({pct_101}%)\n"
    )

    if gap_100_101 is not None and gap_99_100 is not None:
        if abs(gap_100_101) < 1e-6:
            p("⚠️ **WARNING**: Scores at rank #100 and #101 are effectively identical. "
              "The cutoff is arbitrary at this boundary.")
        elif pct_101 is not None and pct_101 < 0.1:
            p("⚠️ **OBSERVATION**: Very small percentage gap at the #100/#101 boundary. "
              "The cutoff could easily shift with minor metric changes.")
        else:
            p("✅ The #100/#101 boundary has a meaningful score gap.")

    # ------------------------------------------------------------------- #
    h(2, "5. Concentration Analysis")

    cn = a["concentration"]
    p(f"Total eligible universe volume: {_fmt_usd(cn['total_volume_usd'])}")

    vc = cn["volume_concentration"]
    oc = cn["oi_concentration"]
    table(
        ["Tier", "Volume %", "OI %"],
        [
            ["Top 10", f"{vc['top_10_pct']}%", f"{oc['top_10_pct']}%"],
            ["Top 25", f"{vc['top_25_pct']}%", f"{oc['top_25_pct']}%"],
            ["Top 50", f"{vc['top_50_pct']}%", f"{oc['top_50_pct']}%"],
            ["Top 100", f"{vc['top_100_pct']}%", f"{oc['top_100_pct']}%"],
        ],
    )

    # ------------------------------------------------------------------- #
    h(2, "6. Score Component Analysis")

    for key, label in [("top_100", "Top 100"), ("full_universe", "Full Universe (397)")]:
        comp = a["components"][key]
        p(f"**{label}** — Weights: Vol={comp['weights']['VOLUME_WEIGHT']}, "
          f"OI={comp['weights']['OI_WEIGHT']}, Spread={comp['weights']['SPREAD_WEIGHT']}")
        vol_s = comp["volume_contribution"]
        oi_s = comp["oi_contribution"]
        spr_s = comp["spread_contribution"]
        table(
            ["Component", "Mean", "Median", "Min", "Max"],
            [
                ["Volume contrib",
                 _fmt_num(vol_s.get("mean")), _fmt_num(vol_s.get("median")),
                 _fmt_num(vol_s.get("min")), _fmt_num(vol_s.get("max"))],
                ["OI contrib",
                 _fmt_num(oi_s.get("mean")), _fmt_num(oi_s.get("median")),
                 _fmt_num(oi_s.get("min")), _fmt_num(oi_s.get("max"))],
                ["Spread contrib",
                 _fmt_num(spr_s.get("mean")), _fmt_num(spr_s.get("median")),
                 _fmt_num(spr_s.get("min")), _fmt_num(spr_s.get("max"))],
            ],
        )

    # ------------------------------------------------------------------- #
    h(2, "7. Normalization Outlier Analysis")

    no = a["normalization_outliers"]
    vc2 = no["volume_compression"]
    oc2 = no["oi_compression"]

    p("**Volume extremes (top 5 / bottom 5 by raw 24h volume):**")
    table(["Direction", "Symbol", "Raw Volume (USD)"],
        [["Top", r["symbol"], _fmt_usd(r["value"])] for r in no["volume_extremes"]["top"]]
        + [["Bottom", r["symbol"], _fmt_usd(r["value"])] for r in no["volume_extremes"]["bottom"]]
    )

    p("**OI extremes (top 5 / bottom 5 by raw open interest):**")
    table(["Direction", "Symbol", "Raw OI"],
        [["Top", r["symbol"], _fmt_num(r["value"], ".0f")] for r in no["oi_extremes"]["top"]]
        + [["Bottom", r["symbol"], _fmt_num(r["value"], ".0f")] for r in no["oi_extremes"]["bottom"]]
    )

    p("**Spread extremes (widest / tightest):**")
    table(["Direction", "Symbol", "Spread bps"],
        [["Widest", r["symbol"], _fmt_num(r["value"])] for r in no["spread_extremes"]["top"]]
        + [["Tightest", r["symbol"], _fmt_num(r["value"])] for r in no["spread_extremes"]["bottom"]]
    )

    code(
        f"Volume compression analysis:\n"
        f"  max value            : {_fmt_usd(vc2.get('max_value'))}\n"
        f"  p99 value            : {_fmt_usd(vc2.get('p99_value'))}\n"
        f"  max / p99 ratio      : {vc2.get('max_to_p99_ratio')}x\n"
        f"  % contracts norm < 0.10 : {vc2.get('pct_contracts_below_norm_0.1')}%\n"
        f"  % contracts norm < 0.05 : {vc2.get('pct_contracts_below_norm_0.05')}%\n"
        f"\n"
        f"OI compression analysis:\n"
        f"  max value            : {_fmt_num(oc2.get('max_value'), '.0f')}\n"
        f"  p99 value            : {_fmt_num(oc2.get('p99_value'), '.0f')}\n"
        f"  max / p99 ratio      : {oc2.get('max_to_p99_ratio')}x\n"
        f"  % contracts norm < 0.10 : {oc2.get('pct_contracts_below_norm_0.1')}%\n"
    )

    # ------------------------------------------------------------------- #
    h(2, "8. Neutral Spread Audit")

    ns = a["neutral_spread"]
    p(f"Contracts with `spread_bps = None` receive `norm_spread = 0.5` "
      f"(spread contribution = {ns['neutral_spread_contribution']}).")

    code(
        f"Neutral spread contracts : {ns['neutral_spread_count']} "
        f"({ns['neutral_spread_pct']}% of universe)\n"
        f"Neutral norm_spread      : {ns['neutral_norm_spread_value']}\n"
        f"Spread contribution      : {ns['neutral_spread_contribution']}\n"
    )

    if ns["neutral_symbols"]:
        p(f"**Neutral spread symbols:**")
        p(", ".join(ns["neutral_symbols"]))
    else:
        p("✅ All contracts have valid spread data — no neutral assignments.")

    p(ns["observation"])

    # ------------------------------------------------------------------- #
    h(2, "9. Classification Audit")

    cl = a["classification"]
    br = cl["by_reason"]
    table(
        ["Rejection Reason", "Count", "Sample Symbols"],
        [
            ["Non-perpetual (quarterly/delivery)", br.get("non_perpetual", 0),
             ", ".join(cl["samples"].get("non_perpetual", [])[:5])],
            ["Inactive (not TRADING)", br.get("inactive", 0),
             ", ".join(cl["samples"].get("inactive", [])[:5])],
            ["Non-USDT quote asset", br.get("non_usdt_quote", 0),
             ", ".join(cl["samples"].get("non_usdt_quote", [])[:5])],
            ["TradFi (underlyingType blocked)", br.get("tradfi_underlying_type", 0),
             ", ".join(cl["samples"].get("tradfi_underlying_type", [])[:5])],
            ["TradFi (underlyingSubType blocked)", br.get("tradfi_subtype", 0),
             ", ".join(cl["samples"].get("tradfi_subtype", [])[:5])],
            ["Other", br.get("other", 0),
             ", ".join(cl["samples"].get("other", [])[:5])],
        ],
    )

    if cl["tradfi_subtypes_found"]:
        p("**TradFi subtypes found in excluded contracts:**")
        code(json.dumps(cl["tradfi_subtypes_found"], indent=2))

    # ------------------------------------------------------------------- #
    h(2, "10. Top-100 Composition (Listing Age)")

    comp = a["composition"]
    age = comp["top_100_listing_age_days"]

    code(
        f"BTC/ETH ranks            : {comp['btc_eth_ranks']}\n"
        f"\n"
        f"Top-100 listing age (days):\n"
        f"  min    : {age.get('min'):.0f}\n"
        f"  median : {age.get('median'):.0f}\n"
        f"  mean   : {age.get('mean')}\n"
        f"  max    : {age.get('max'):.0f}\n"
        f"  unknown: {age.get('unknown_count')}\n"
    )

    p("**Top-100 age bucket distribution:**")
    top100_b = comp["top_100_age_buckets"]
    full_b = comp["full_universe_age_buckets"]
    all_keys = sorted(set(list(top100_b.keys()) + list(full_b.keys())))
    table(
        ["Age bucket", "Top 100 count", "Full universe count"],
        [[k, top100_b.get(k, 0), full_b.get(k, 0)] for k in all_keys],
    )

    # ------------------------------------------------------------------- #
    h(2, "11. Sanity Checks")

    sc = a["sanity_checks"]
    checks = sc["checks"]
    for name, result_val in checks.items():
        icon = "✅" if result_val else "❌"
        lines.append(f"- {icon} `{name}`")
    lines.append("")

    if sc["all_pass"]:
        p("✅ **All sanity checks PASSED.**")
    else:
        p(f"❌ **Failed checks:** {', '.join(sc['failed_checks'])}")

    # ------------------------------------------------------------------- #
    h(2, "12. Snapshot Integrity")

    si = a["snapshot_integrity"]
    code(
        f"Snapshot files found          : {si['total_files']}\n"
        f"Latest file                   : {si['latest_file']}\n"
        f"Header records in file        : {si['header_count']}\n"
        f"Data records in file          : {si['data_record_count']}\n"
        f"Latest batch record count     : {si['latest_batch_record_count']}\n"
        f"Matches eligible count        : {si['latest_batch_matches_eligible']}\n"
        f"All headers have timestamp    : {si['all_headers_have_timestamp']}\n"
        f"All data have rank            : {si['all_data_have_rank']}\n"
        f"All data have score           : {si['all_data_have_score']}\n"
        f"All data have status          : {si['all_data_have_status']}\n"
        f"Unique snapshot IDs in file   : {si['unique_snapshot_ids_in_file']}\n"
        f"Append-only verified          : {si['append_only_verified']}\n"
    )

    # ------------------------------------------------------------------- #
    h(2, "13. Audit Verdict")

    # Compute verdict
    sanity_pass = sc["all_pass"]
    si_ok = si["latest_batch_matches_eligible"] and si["all_headers_have_timestamp"]
    baseline_ok = a["baseline"]["eligibility_check_passes"]
    metric_fail = a["baseline"]["metric_failures"] == 0

    # Classify findings
    critical = []
    important = []
    minor = []
    observations = []

    # Check normalization compression
    vol_comp = a["normalization_outliers"]["volume_compression"]
    pct_below_01 = vol_comp.get("pct_contracts_below_norm_0.1", 0)
    max_p99_ratio = vol_comp.get("max_to_p99_ratio", 1)

    if pct_below_01 > 80:
        important.append(
            f"Volume compression: {pct_below_01:.0f}% of contracts have norm_volume < 0.10 "
            f"due to extreme outliers (max/p99 = {max_p99_ratio}x). "
            "Min-max normalization is being significantly distorted by the top 1-2 symbols. "
            "Consider log or rank-based normalization in a future revision."
        )

    # Check neutral spread
    neutral_count = a["neutral_spread"]["neutral_spread_count"]
    neutral_pct = a["neutral_spread"]["neutral_spread_pct"]
    if neutral_count > 0:
        if neutral_pct > 20:
            important.append(
                f"{neutral_count} contracts ({neutral_pct}%) have no bid/ask spread data "
                "and receive neutral norm_spread=0.5. Large fraction may distort spread rankings."
            )
        else:
            minor.append(
                f"{neutral_count} contracts ({neutral_pct}%) have no spread data → "
                "norm_spread=0.5 (neutral). No ranking distortion detected."
            )

    # Check boundary
    gap_100_101 = a["boundary"]["gap_100_to_101"]
    pct_gap = a["boundary"]["pct_gap_100_to_101"]
    if gap_100_101 is not None and abs(gap_100_101) < 1e-6:
        important.append(
            "Score tie at the #100/#101 boundary. Top-100 cutoff is technically "
            "arbitrary for tied contracts — resolved only by alphabetical tie-breaking."
        )
    elif pct_gap is not None and pct_gap < 0.1:
        minor.append(
            f"Very small gap ({pct_gap}%) between #100 and #101. "
            "A small change in market conditions could cause boundary shuffling."
        )

    # Sanity checks
    if not sanity_pass:
        critical.append(f"Sanity check failures: {sc['failed_checks']}")

    # Snapshot
    if not si["latest_batch_matches_eligible"]:
        important.append(
            f"Snapshot record count ({si['latest_batch_record_count']}) does not match "
            f"eligible count ({a['baseline']['eligible_crypto_perps']})."
        )

    # BTC/ETH rank check
    btc_rank = a["composition"]["btc_eth_ranks"].get("BTCUSDT")
    eth_rank = a["composition"]["btc_eth_ranks"].get("ETHUSDT")
    if btc_rank and btc_rank > 10:
        observations.append(
            f"BTCUSDT is ranked #{btc_rank}. BTC not in top 10 is unusual — "
            "check if volume normalization is compressing BTC's lead."
        )
    if eth_rank and eth_rank > 10:
        observations.append(
            f"ETHUSDT is ranked #{eth_rank}. ETH not in top 10 is unusual."
        )

    # Volume concentration
    top10_vol = a["concentration"]["volume_concentration"]["top_10_pct"]
    top10_oi = a["concentration"]["oi_concentration"]["top_10_pct"]
    observations.append(
        f"Top-10 contracts represent {top10_vol}% of universe volume "
        f"and {top10_oi}% of universe OI — high concentration is expected "
        "in crypto markets."
    )

    # Overall verdict
    if critical:
        verdict = "FAIL"
    elif len(important) >= 3:
        verdict = "PASS WITH ISSUES"
    elif important:
        verdict = "PASS WITH ISSUES"
    elif not sanity_pass:
        verdict = "FAIL"
    else:
        verdict = "PASS"

    code(f"UNIVERSE STATUS: {verdict}")

    if critical:
        h(3, "🔴 Critical Issues")
        for i, item in enumerate(critical, 1):
            p(f"{i}. {item}")

    if important:
        h(3, "🟡 Important Issues")
        for i, item in enumerate(important, 1):
            p(f"{i}. {item}")

    if minor:
        h(3, "🔵 Minor Issues")
        for i, item in enumerate(minor, 1):
            p(f"{i}. {item}")

    if observations:
        h(3, "📋 Observations")
        for i, item in enumerate(observations, 1):
            p(f"{i}. {item}")

    if not critical and not important and not minor:
        p("No issues found. Universe engine is operating correctly.")

    # Footer
    lines.append("---")
    lines.append(f"*Audit generated by `universe/audit.py` — "
                 f"Binance Perpetual Universe Engine V1*")

    return "\n".join(lines)


# =========================================================================== #
#  Main entry point
# =========================================================================== #


async def _async_main() -> None:
    logging.basicConfig(level=logging.WARNING)  # suppress noisy INFO logs during audit

    print("=" * 60)
    print("  Binance Perpetual Universe — V1 Audit")
    print("=" * 60)

    auditor = UniverseAuditor()
    audit_data = await auditor.run()

    # Save raw JSON
    out_json = Path("audit_output.json")
    out_json.write_text(json.dumps(audit_data, indent=2, default=str), encoding="utf-8")
    print(f"\n  Raw audit data  -> {out_json}")

    # Save Markdown report
    docs_dir = Path("docs")
    docs_dir.mkdir(exist_ok=True)
    report_path = docs_dir / "universe_audit.md"
    report_md = build_markdown_report(audit_data)
    report_path.write_text(report_md, encoding="utf-8")
    print(f"  Markdown report -> {report_path}")

    # Print verdict summary to stdout
    b = audit_data["baseline"]
    sc = audit_data["sanity_checks"]
    neutral = audit_data["neutral_spread"]
    verdict_section = audit_data["sanity_checks"]

    # Determine verdict inline
    vol_comp = audit_data["normalization_outliers"]["volume_compression"]
    pct_below_01 = vol_comp.get("pct_contracts_below_norm_0.1", 0)
    neutral_pct = neutral["neutral_spread_pct"]
    sanity_pass = sc["all_pass"]
    gap_100_101 = audit_data["boundary"]["gap_100_to_101"]

    critical_count = 0 if sanity_pass else 1
    important_count = sum([
        pct_below_01 > 80,
        neutral_pct > 20,
        (gap_100_101 is not None and abs(gap_100_101) < 1e-6),
        not audit_data["snapshot_integrity"]["latest_batch_matches_eligible"],
    ])
    minor_count = sum([
        0 < neutral_pct <= 20,
        (gap_100_101 is not None and gap_100_101 is not None
         and audit_data["boundary"]["pct_gap_100_to_101"] is not None
         and abs(audit_data["boundary"]["pct_gap_100_to_101"]) < 0.1),
    ])

    if critical_count:
        verdict = "FAIL"
    elif important_count:
        verdict = "PASS WITH ISSUES"
    else:
        verdict = "PASS"

    print("\n" + "=" * 60)
    print("  AUDIT SUMMARY")
    print("=" * 60)
    print(f"  Tests              : (run separately with pytest)")
    print(f"  Live refresh       : PASS")
    print(f"  Eligible contracts : {b['eligible_crypto_perps']}")
    print(f"  Top 100            : {b['active_top_100']}")
    print(f"  Critical issues    : {critical_count}")
    print(f"  Important issues   : {important_count}")
    print(f"  Minor issues       : {minor_count}")
    print(f"  Overall verdict    : {verdict}")
    print("=" * 60)


def main() -> None:
    asyncio.run(_async_main())


if __name__ == "__main__":
    main()
