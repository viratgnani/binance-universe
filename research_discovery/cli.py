"""
research_discovery/cli.py

Command-line interface for the Market Behavior Discovery Laboratory.
"""

from __future__ import annotations

import argparse
import concurrent.futures
import logging
import sys
from datetime import datetime, timezone

from market_data.config import config as default_config
from research_discovery.feature_engine import DiscoveryFeatureEngine
from research_discovery.experiment_registry import ExperimentRegistry
from research_discovery.data_adapter import DiscoveryDataAdapter

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(name)s  %(message)s",
    datefmt="%Y-%m-%dT%H:%M:%SZ",
)
logger = logging.getLogger("discovery")


def _parse_datetime(s: str) -> datetime:
    s = s.strip().replace("Z", "+00:00")
    dt = datetime.fromisoformat(s)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def cmd_feature_generate(args: argparse.Namespace) -> int:
    symbols = [s.strip().upper() for s in args.symbols.split(",") if s.strip()]
    start = _parse_datetime(args.start)
    end = _parse_datetime(args.end)
    workers = args.workers
    
    logger.info("Starting discovery feature generation for %d symbols using %d workers.", len(symbols), workers)
    logger.info("Period: %s to %s", start.isoformat(), end.isoformat())

    engine = DiscoveryFeatureEngine()

    if workers <= 1:
        for sym in symbols:
            engine.process_symbol(sym, start, end)
    else:
        with concurrent.futures.ProcessPoolExecutor(max_workers=workers) as executor:
            futures = {
                executor.submit(engine.process_symbol, sym, start, end): sym 
                for sym in symbols
            }
            for future in concurrent.futures.as_completed(futures):
                sym = futures[future]
                try:
                    w, s = future.result()
                    logger.info("Completed %s: +%d rows (%d skipped)", sym, w, s)
                except Exception as e:
                    logger.error("Failed processing %s: %s", sym, e)
                    
    logger.info("Discovery feature generation complete.")
    return 0


def cmd_list(args: argparse.Namespace) -> int:
    registry = ExperimentRegistry()
    entries = registry.list_entries()
    
    print("\n" + "=" * 80)
    print("DISCOVERY LABORATORY — EXPERIMENT REGISTRY")
    print("=" * 80)
    print(f"{'ID':<25} {'Status':<12} {'Created (UTC)':<20} {'Exploratory'}")
    print("-" * 80)
    
    for e in entries:
        is_exp = e.spec_summary.get("is_exploratory", True)
        print(f"{e.experiment_id:<25} {e.status.value:<12} {e.created_at.strftime('%Y-%m-%d %H:%M'):<20} {is_exp}")
        
    print(f"\nTotal registered experiments: {len(entries)}\n")
    return 0


def cmd_feature_status(args: argparse.Namespace) -> int:
    start = _parse_datetime(args.start)
    end = _parse_datetime(args.end)
    
    adapter = DiscoveryDataAdapter()
    symbols = adapter.get_available_symbols(start, end)
    
    print("\n" + "=" * 80)
    print("DISCOVERY LABORATORY — FEATURE DATA STATUS")
    print("=" * 80)
    print(f"Period: {start.isoformat()} to {end.isoformat()}")
    print(f"Symbols with discovery features: {len(symbols)}")
    if len(symbols) <= 20:
        print(f"Symbols: {', '.join(symbols)}")
    else:
        print(f"Symbols: {', '.join(symbols[:20])}... (+{len(symbols)-20} more)")
    print()
    return 0


def main() -> None:
    parser = argparse.ArgumentParser(description="Market Behavior Discovery Laboratory")
    sub = parser.add_subparsers(dest="command", required=True)

    # feature-generate
    gen_p = sub.add_parser("feature-generate", help="Generate O(N) discovery features")
    gen_p.add_argument("--symbols", required=True, help="Comma-separated symbols")
    gen_p.add_argument("--start", required=True, help="ISO-8601 UTC start")
    gen_p.add_argument("--end", required=True, help="ISO-8601 UTC end")
    gen_p.add_argument("--workers", type=int, default=1, help="Number of parallel workers")

    # feature-status
    stat_p = sub.add_parser("feature-status", help="Check availability of discovery features")
    stat_p.add_argument("--start", required=True, help="ISO-8601 UTC start")
    stat_p.add_argument("--end", required=True, help="ISO-8601 UTC end")

    # list
    sub.add_parser("list", help="List registered experiments")

    args = parser.parse_args()

    if args.command == "feature-generate":
        sys.exit(cmd_feature_generate(args))
    elif args.command == "feature-status":
        sys.exit(cmd_feature_status(args))
    elif args.command == "list":
        sys.exit(cmd_list(args))
