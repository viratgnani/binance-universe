"""
research_features/__main__.py

CLI entry point for the Research Feature Layer V1.

Usage
-----
python -m research_features generate \
    --symbols BTCUSDT,ETHUSDT \
    --start 2026-08-31T00:00:00Z \
    --end 2026-08-31T01:00:00Z
"""

from __future__ import annotations

import argparse
import sys
import logging
from datetime import datetime, timezone

from research_features.engine import FeatureEngine
from research_features.store import FeatureStore
from research_features.quality import FeatureQualityValidator

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(name)s  %(message)s",
    datefmt="%Y-%m-%dT%H:%M:%SZ",
)
logger = logging.getLogger("research_features")


def _parse_datetime(s: str) -> datetime:
    s = s.strip()
    if len(s) == 10:
        s += "T00:00:00Z"
    s = s.replace("Z", "+00:00")
    dt = datetime.fromisoformat(s)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _parse_symbols(raw: str, start_dt: datetime, top_n: int = 100) -> list[str]:
    if raw.strip().lower() == "universe":
        try:
            from universe.config import config as uni_cfg
            from universe.snapshot_repository import SnapshotRepository
            repo = SnapshotRepository(uni_cfg)
            files = repo.list_snapshot_files()
            if not files:
                logger.error("No universe snapshots found.")
                sys.exit(1)
            
            # Find the snapshot active on or immediately before start_dt
            target_date = start_dt.date()
            target_file = None
            for f in reversed(files): # Assuming list_snapshot_files returns sorted ascending
                f_date_str = f.stem.split("_")[-1] # snapshot_YYYYMMDD
                f_date = datetime.strptime(f_date_str, "%Y%m%d").date()
                if f_date <= target_date:
                    target_file = f
                    break
            
            if not target_file:
                logger.warning("No snapshot found <= %s. Falling back to earliest available.", target_date.isoformat())
                target_file = files[0]
                
            logger.info("Using universe snapshot %s for historical generation at %s", target_file.name, start_dt.isoformat())
            records = repo.load_records(target_file)
            symbols = [
                r["symbol"] for r in records
                if r.get("record_type") == "DATA" and r.get("universe_status") == "ACTIVE_TOP_100"
            ]
            symbols = symbols[:top_n]
            return symbols
        except Exception as e:
            logger.error("Failed to load universe symbols: %s", e)
            sys.exit(1)
    return [s.strip().upper() for s in raw.split(",") if s.strip()]


def cmd_generate(args: argparse.Namespace) -> int:
    start = _parse_datetime(args.start)
    end = _parse_datetime(args.end)
    interval = args.interval
    symbols = _parse_symbols(args.symbols, start, getattr(args, "top_n", 100))

    logger.info(
        "Generating features for %d symbols from %s to %s (interval=%dm)",
        len(symbols), start.isoformat(), end.isoformat(), interval
    )

    engine = FeatureEngine()
    store = FeatureStore()
    validator = FeatureQualityValidator()

    total_rows_created = 0
    total_rows_skipped = 0
    total_violations = 0
    total_missing = 0

    for sym in symbols:
        logger.info("Processing %s...", sym)
        rows = engine.generate_features(sym, start, end, interval)
        if not rows:
            logger.warning("No features generated for %s", sym)
            continue
            
        validation_result = validator.validate(rows)
        total_missing += validation_result.missing_data_count
        
        if not validation_result.is_valid:
            for v in validation_result.violations:
                logger.error("Validation error for %s: %s", sym, v)
            total_violations += len(validation_result.violations)
            
        written, skipped = store.save(rows)
        total_rows_created += written
        total_rows_skipped += skipped
        
    print("\n============================================================")
    print("RESEARCH FEATURE GENERATION REPORT")
    print(f"\nSymbols requested    : {len(symbols)}")
    print(f"Feature rows created : {total_rows_created}")
    print(f"Feature rows skipped : {total_rows_skipped}")
    print(f"Missing data points  : {total_missing}")
    print(f"Validation violations: {total_violations}")
    
    if total_violations > 0:
        print("\nOverall: NEEDS INVESTIGATION")
        return 1
    else:
        print("\nOverall: SUCCESS")
        return 0


def main() -> None:
    parser = argparse.ArgumentParser(description="Research Feature Layer V1")
    sub = parser.add_subparsers(dest="command", required=True)
    
    gen_parser = sub.add_parser("generate", help="Generate and store features")
    gen_parser.add_argument("--symbols", required=True, help="Comma-separated symbols or 'universe'")
    gen_parser.add_argument("--start", required=True, help="Start datetime (ISO-8601 UTC)")
    gen_parser.add_argument("--end", required=True, help="End datetime (ISO-8601 UTC)")
    gen_parser.add_argument("--interval", type=int, default=1, help="Interval in minutes (default: 1)")
    gen_parser.add_argument("--top-n", type=int, default=100, help="Max universe symbols to take")
    
    args = parser.parse_args()
    
    if args.command == "generate":
        sys.exit(cmd_generate(args))


if __name__ == "__main__":
    main()
