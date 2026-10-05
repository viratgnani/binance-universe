"""
universe/refresh.py

Main universe refresh orchestrator.

Refresh workflow
----------------
1.  fetch_exchange_info()       — Binance /fapi/v1/exchangeInfo
2.  parse_exchange_info()       — raw JSON → list[ContractInfo]
3.  filter_eligible()           — remove non-PERPETUAL, non-TRADING, TradFi
4.  fetch_market_metrics()      — bulk ticker + concurrent OI per symbol
5.  get_normalizer_by_name(cfg.NORMALIZATION_METHOD) — resolve normalizer
    .normalize()                — log1p + min-max (V1.1 default, configurable)
6.  rank()                      — deterministic scoring → list[RankResult]
7.  select_top_n()              — assign ACTIVE_TOP_100 / WATCHLIST
8.  build_universe_members()    — merge all data into UniverseMember list
9.  save_snapshot()             — append to JSONL file
10. log_summary()               — structured summary to stdout / log

Entry point
-----------
    python -m universe.refresh

This module is also importable for programmatic use:

    from universe import run_refresh
    result = asyncio.run(run_refresh())
"""

from __future__ import annotations

import asyncio
import logging
import sys
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone

from universe.binance_client import BinanceFuturesClient
from universe.config import UniverseConfig, config as default_config
from universe.contract_filter import ContractFilter, FilterResult, parse_exchange_info
from universe.market_metrics import MarketMetricsFetcher
from universe.models import (
    ContractInfo,
    MarketMetrics,
    SnapshotHeader,
    SnapshotRecord,
    UniverseMember,
    UniverseStatus,
)
from universe.normalizers import get_normalizer_by_name
from universe.ranking_engine import RankingEngine
from universe.snapshot_repository import SnapshotRepository
from universe.top_n_selector import SelectionResult, TopNSelector

logger = logging.getLogger(__name__)


# --------------------------------------------------------------------------- #
#  Result dataclass returned by run_refresh()
# --------------------------------------------------------------------------- #


@dataclass
class RefreshResult:
    """Summary of a completed universe refresh run."""

    snapshot_id: str
    snapshot_timestamp: datetime

    total_discovered: int           # All perpetuals returned by Binance
    total_eligible: int             # After eligibility filtering
    total_excluded: int             # Rejected by filter
    total_ranked: int               # Have complete metrics, ranked
    total_failed_metrics: int       # Eligible but metrics fetch failed

    universe: list[UniverseMember]  # Complete master universe (ranked + unranked)
    top_100: list[UniverseMember]   # Convenience: only ACTIVE_TOP_100
    excluded: list[FilterResult]    # Details of each exclusion


# --------------------------------------------------------------------------- #
#  Core refresh function
# --------------------------------------------------------------------------- #


async def run_refresh(cfg: UniverseConfig = default_config) -> RefreshResult:
    """
    Execute one full universe refresh cycle.

    Safe to call repeatedly — idempotent, append-only snapshot writes.

    Parameters
    ----------
    cfg:
        Configuration object.  Defaults to the module-level singleton.

    Returns
    -------
    :class:`RefreshResult` containing the complete universe and summary stats.
    """
    snapshot_timestamp = datetime.now(tz=timezone.utc)
    snapshot_id = snapshot_timestamp.strftime("%Y%m%dT%H%M%SZ")

    logger.info("=" * 70)
    logger.info("Universe refresh started  [id=%s]", snapshot_id)
    logger.info("=" * 70)

    # ------------------------------------------------------------------ #
    #  Step 1 + 2: Fetch and parse exchange info
    # ------------------------------------------------------------------ #
    async with BinanceFuturesClient(cfg) as client:

        logger.info("[1/8] Fetching exchange info from Binance…")
        raw_info = await client.get_exchange_info()
        all_contracts: list[ContractInfo] = parse_exchange_info(raw_info)
        total_discovered = len(all_contracts)
        logger.info("      Discovered %d contracts total", total_discovered)

        # ---------------------------------------------------------------- #
        #  Step 3: Filter eligible contracts
        # ---------------------------------------------------------------- #
        logger.info("[2/8] Filtering eligible crypto perpetuals…")
        contract_filter = ContractFilter(cfg)
        eligible_contracts, rejected = contract_filter.filter_batch(all_contracts)
        total_excluded = len(rejected)
        total_eligible = len(eligible_contracts)
        logger.info(
            "      Eligible: %d  |  Excluded: %d",
            total_eligible,
            total_excluded,
        )

        # ---------------------------------------------------------------- #
        #  Step 4: Fetch market metrics
        # ---------------------------------------------------------------- #
        logger.info("[3/8] Fetching market metrics (ticker + open interest)…")
        fetcher = MarketMetricsFetcher(client, cfg)
        metrics_list: list[MarketMetrics] = await fetcher.fetch_all(eligible_contracts)

        failed_metrics = [m for m in metrics_list if m.metrics_failed]
        total_failed_metrics = len(failed_metrics)
        if failed_metrics:
            logger.warning(
                "      %d contracts had metric fetch failures: %s",
                total_failed_metrics,
                [m.symbol for m in failed_metrics[:10]],
            )

    # ------------------------------------------------------------------ #
    #  Step 5: Normalise
    # ------------------------------------------------------------------ #
    logger.info("[4/8] Normalising metrics (method=%s)…", cfg.NORMALIZATION_METHOD)
    normalizer = get_normalizer_by_name(cfg.NORMALIZATION_METHOD)
    normalized, skipped_symbols = normalizer.normalize(metrics_list)
    logger.info(
        "      Rankable: %d  |  Skipped (incomplete): %d",
        len(normalized),
        len(skipped_symbols),
    )

    # ------------------------------------------------------------------ #
    #  Step 6: Rank
    # ------------------------------------------------------------------ #
    logger.info("[5/8] Ranking contracts…")
    ranking_engine = RankingEngine(cfg)
    rank_results = ranking_engine.rank(normalized)
    total_ranked = len(rank_results)

    # ------------------------------------------------------------------ #
    #  Step 7: Top-N selection
    # ------------------------------------------------------------------ #
    logger.info("[6/8] Selecting Top-%d…", cfg.TOP_N)
    selector = TopNSelector(cfg)
    selection_results = selector.select(rank_results)

    # Build lookup maps for the merge step
    rank_map = {rr.symbol: rr for rr in rank_results}
    selection_map = {sr.symbol: sr for sr in selection_results}
    metrics_map = {m.symbol: m for m in metrics_list}

    # ------------------------------------------------------------------ #
    #  Step 8: Build master universe (UniverseMember list)
    # ------------------------------------------------------------------ #
    logger.info("[7/8] Building master universe…")
    universe: list[UniverseMember] = []

    for contract in eligible_contracts:
        sym = contract.symbol
        metrics = metrics_map.get(sym)
        rank_result = rank_map.get(sym)
        selection = selection_map.get(sym)

        member = UniverseMember(
            symbol=sym,
            base_asset=contract.base_asset,
            quote_asset=contract.quote_asset,
            margin_asset=contract.margin_asset,
            contract_type=contract.contract_type,
            status=contract.status,
            listing_time=contract.listing_time,
            rank=rank_result.rank if rank_result else None,
            universe_score=rank_result.score if rank_result else None,
            universe_status=(
                selection.universe_status if selection else UniverseStatus.WATCHLIST
            ),
            volume_24h_quote=metrics.volume_24h_quote if metrics else None,
            volume_24h_base=metrics.volume_24h_base if metrics else None,
            last_price=metrics.last_price if metrics else None,
            bid_price=metrics.bid_price if metrics else None,
            ask_price=metrics.ask_price if metrics else None,
            spread_bps=metrics.spread_bps if metrics else None,
            open_interest=metrics.open_interest if metrics else None,
            metrics_failed=metrics.metrics_failed if metrics else True,
            last_updated=snapshot_timestamp,
        )
        universe.append(member)

    # Sort universe: ranked members first (by rank), then unranked alphabetically
    universe.sort(
        key=lambda m: (m.rank if m.rank is not None else 999_999, m.symbol)
    )

    top_100 = [m for m in universe if m.universe_status == UniverseStatus.ACTIVE_TOP_100]

    # ------------------------------------------------------------------ #
    #  Step 9: Persist snapshot
    # ------------------------------------------------------------------ #
    logger.info("[8/8] Persisting snapshot…")
    repo = SnapshotRepository(cfg)

    snapshot_records = [
        SnapshotRecord(
            snapshot_timestamp=snapshot_timestamp,
            snapshot_id=snapshot_id,
            symbol=m.symbol,
            rank=m.rank,
            score=m.universe_score,
            universe_status=m.universe_status,
            volume_24h_quote=m.volume_24h_quote,
            open_interest=m.open_interest,
            spread_bps=m.spread_bps,
            metrics_failed=m.metrics_failed,
        )
        for m in universe
    ]

    snapshot_header = SnapshotHeader(
        snapshot_id=snapshot_id,
        snapshot_timestamp=snapshot_timestamp,
        total_eligible=total_eligible,
        total_ranked=total_ranked,
        total_failed=total_failed_metrics,
        top_n=cfg.TOP_N,
    )

    try:
        saved_path = repo.save(
            snapshot_id=snapshot_id,
            snapshot_timestamp=snapshot_timestamp,
            records=snapshot_records,
            header=snapshot_header,
        )
    except Exception as exc:
        logger.error("Snapshot persistence failed: %s", exc, exc_info=True)
        saved_path = None

    # ------------------------------------------------------------------ #
    #  Summary log
    # ------------------------------------------------------------------ #
    _log_summary(
        snapshot_id=snapshot_id,
        snapshot_timestamp=snapshot_timestamp,
        total_discovered=total_discovered,
        total_eligible=total_eligible,
        total_excluded=total_excluded,
        total_ranked=total_ranked,
        total_failed_metrics=total_failed_metrics,
        top_100=top_100,
        saved_path=saved_path,
        cfg=cfg,
    )

    return RefreshResult(
        snapshot_id=snapshot_id,
        snapshot_timestamp=snapshot_timestamp,
        total_discovered=total_discovered,
        total_eligible=total_eligible,
        total_excluded=total_excluded,
        total_ranked=total_ranked,
        total_failed_metrics=total_failed_metrics,
        universe=universe,
        top_100=top_100,
        excluded=rejected,
    )


# --------------------------------------------------------------------------- #
#  Summary logging
# --------------------------------------------------------------------------- #


def _log_summary(
    *,
    snapshot_id: str,
    snapshot_timestamp: datetime,
    total_discovered: int,
    total_eligible: int,
    total_excluded: int,
    total_ranked: int,
    total_failed_metrics: int,
    top_100: list[UniverseMember],
    saved_path,
    cfg: UniverseConfig,
) -> None:
    sep = "─" * 70
    logger.info(sep)
    logger.info("UNIVERSE REFRESH COMPLETE")
    logger.info(sep)
    logger.info("  Snapshot ID          : %s", snapshot_id)
    logger.info("  Snapshot timestamp   : %s", snapshot_timestamp.isoformat())
    logger.info("  Total discovered     : %d", total_discovered)
    logger.info("  Eligible perpetuals  : %d", total_eligible)
    logger.info("  Excluded contracts   : %d", total_excluded)
    logger.info("  Successfully ranked  : %d", total_ranked)
    logger.info("  Metric fetch failures: %d", total_failed_metrics)
    logger.info("  ACTIVE_TOP_%d count  : %d", cfg.TOP_N, len(top_100))
    if saved_path:
        logger.info("  Snapshot file        : %s", saved_path)
    logger.info(sep)

    display_n = min(cfg.LOG_TOP_N_SUMMARY, len(top_100))
    logger.info("  Top-%d contracts:", display_n)
    for member in top_100[:display_n]:
        vol_str = f"${member.volume_24h_quote / 1e9:.2f}B" if member.volume_24h_quote else "N/A"
        oi_str = f"${member.open_interest * (member.last_price or 0) / 1e9:.2f}B" if (member.open_interest and member.last_price) else "N/A"
        logger.info(
            "    #%-4d %-12s  score=%.4f  vol=%s  OI=%s",
            member.rank,
            member.symbol,
            member.universe_score or 0.0,
            vol_str,
            oi_str,
        )

    logger.info(sep)


# --------------------------------------------------------------------------- #
#  Logging setup
# --------------------------------------------------------------------------- #


def _setup_logging() -> None:
    """Configure structured logging for command-line invocation."""
    try:
        from pythonjsonlogger import jsonlogger
        handler = logging.StreamHandler(sys.stdout)
        formatter = jsonlogger.JsonFormatter(
            fmt="%(asctime)s %(name)s %(levelname)s %(message)s",
            datefmt="%Y-%m-%dT%H:%M:%SZ",
        )
        handler.setFormatter(formatter)
    except ImportError:
        # Fall back to plain text if python-json-logger is not installed
        handler = logging.StreamHandler(sys.stdout)
        formatter = logging.Formatter(
            fmt="%(asctime)s  %(levelname)-8s  %(name)s  %(message)s",
            datefmt="%Y-%m-%dT%H:%M:%SZ",
        )
        handler.setFormatter(formatter)

    root = logging.getLogger()
    root.setLevel(logging.INFO)
    root.addHandler(handler)


# --------------------------------------------------------------------------- #
#  CLI entry point:  python -m universe.refresh
# --------------------------------------------------------------------------- #


def main() -> None:
    _setup_logging()
    result = asyncio.run(run_refresh())
    # Exit code 1 if we couldn't rank anything meaningful
    if result.total_ranked == 0:
        logger.error("No contracts were successfully ranked. Check API connectivity.")
        sys.exit(1)


if __name__ == "__main__":
    main()
