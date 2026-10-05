"""
research/__main__.py

CLI entry point for Research Engine V1.

Usage
-----
python -m research run \\
  --symbols BTCUSDT,ETHUSDT \\
  --feature return_1m \\
  --operator ">" \\
  --threshold 0.005 \\
  --event-mode crossing \\
  --crossing-direction cross_up \\
  --event-policy every_observation \\
  --horizons 1,3,5,10 \\
  --price-feature mid_price \\
  --start 2026-08-31T00:00:00Z \\
  --end 2026-08-31T01:00:00Z \\
  --research-id my_study_001
"""

from __future__ import annotations

import argparse
import hashlib
import json
import logging
import sys
from datetime import datetime, timezone

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(name)s  %(message)s",
    datefmt="%Y-%m-%dT%H:%M:%SZ",
)
logger = logging.getLogger("research")


def _parse_datetime(s: str) -> datetime:
    s = s.strip().replace("Z", "+00:00")
    dt = datetime.fromisoformat(s)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _parse_symbols(raw: str) -> list[str]:
    return [s.strip().upper() for s in raw.split(",") if s.strip()]


def _parse_horizons(raw: str) -> list[int]:
    horizons = []
    for h in raw.split(","):
        h = h.strip()
        try:
            horizons.append(int(h))
        except ValueError:
            logger.error("Invalid horizon value: %s (must be integer minutes)", h)
            sys.exit(1)
    return horizons


def _make_research_id(args: argparse.Namespace) -> str:
    if args.research_id:
        return args.research_id
    # Deterministic auto-ID from spec content
    payload = json.dumps({
        "symbols": sorted(_parse_symbols(args.symbols)),
        "feature": args.feature,
        "operator": args.operator,
        "threshold": args.threshold,
        "event_mode": args.event_mode,
        "crossing_direction": args.crossing_direction,
        "horizons": sorted(_parse_horizons(args.horizons)),
        "start": args.start,
        "end": args.end,
    }, sort_keys=True)
    return "auto_" + hashlib.sha256(payload.encode()).hexdigest()[:12]


def cmd_run(args: argparse.Namespace) -> int:
    from research.models import (
        CrossingDirection,
        EventDefinition,
        EventMode,
        EventPolicy,
        Operator,
        OutcomeDefinition,
        ResearchSpec,
        ThresholdCondition,
    )
    from research.research_runner import ResearchRunner

    symbols  = _parse_symbols(args.symbols)
    start    = _parse_datetime(args.start)
    end      = _parse_datetime(args.end)
    horizons = _parse_horizons(args.horizons)
    rid      = _make_research_id(args)

    # Build spec
    try:
        condition = ThresholdCondition(
            feature_name=args.feature,
            operator=Operator(args.operator),
            threshold=args.threshold,
        )
    except ValueError as e:
        logger.error("Invalid operator '%s': %s", args.operator, e)
        sys.exit(1)

    try:
        event_def = EventDefinition(
            condition=condition,
            event_mode=EventMode(args.event_mode),
            event_policy=EventPolicy(args.event_policy),
            crossing_direction=CrossingDirection(args.crossing_direction),
        )
    except Exception as e:
        logger.error("Invalid event definition: %s", e)
        sys.exit(1)

    outcome_defs = [
        OutcomeDefinition(
            name=f"fwd_return_{h}m",
            horizon_minutes=h,
            price_feature=args.price_feature,
        )
        for h in horizons
    ]

    spec = ResearchSpec(
        research_id=rid,
        symbols=symbols,
        start_time=start,
        end_time=end,
        event_definition=event_def,
        outcome_definitions=outcome_defs,
    )

    logger.info("Research ID  : %s", rid)
    logger.info("Symbols      : %s", ", ".join(symbols))
    logger.info("Feature      : %s %s %s", args.feature, args.operator, args.threshold)
    logger.info("Event mode   : %s (%s)", args.event_mode, args.crossing_direction)
    logger.info("Horizons     : %s min", horizons)
    logger.info("Window       : %s → %s", start.isoformat(), end.isoformat())

    runner  = ResearchRunner()
    results, stats_results = runner.run(
        spec, 
        compute_statistics=args.statistics, 
        group_by=args.group_by
    )

    # Report
    total_events   = sum(len(r.events)   for r in results)
    total_outcomes = sum(len(r.outcomes) for r in results)

    from research.models import OutcomeStatus
    valid_out  = sum(1 for r in results for o in r.outcomes if o.status == OutcomeStatus.VALID)
    insuf_out  = sum(1 for r in results for o in r.outcomes if o.status == OutcomeStatus.INSUFFICIENT_FUTURE_DATA)
    miss_out   = sum(1 for r in results for o in r.outcomes if o.status == OutcomeStatus.MISSING_PRICE)
    total_new  = sum(r.metadata.get("written", 0) for r in results)
    total_skip = sum(r.metadata.get("skipped", 0) for r in results)

    print("\n" + "=" * 62)
    print("RESEARCH ENGINE V1 — PHASE 1 REPORT")
    print("=" * 62)
    print(f"\nResearch ID          : {rid}")
    print(f"Symbols              : {', '.join(symbols)}")
    print(f"Event definition     : {args.feature} {args.operator} {args.threshold} [{args.event_mode}/{args.crossing_direction}]")
    print(f"Horizons             : {horizons} min")
    print(f"\nEvents detected      : {total_events}")
    print(f"Outcomes computed    : {total_outcomes}")
    print(f"  [OK] valid            : {valid_out}")
    print(f"  [--] insufficient data: {insuf_out}")
    print(f"  [--] missing price    : {miss_out}")
    print(f"\nNew rows persisted   : {total_new}")
    print(f"Rows skipped (dup)   : {total_skip}")
    print(f"\nOutput directory     : data/research/{rid}/")

    if total_events == 0:
        print("\nNote: No events found — check feature data coverage and threshold.")

    if args.statistics and stats_results:
        print("\n" + "=" * 62)
        print("PHASE 2: DESCRIPTIVE STATISTICS")
        print("=" * 62)
        
        # Simple grouping/printing logic
        for grp_type in args.group_by:
            grp_stats = [s for s in stats_results if s.grouping_type == grp_type]
            if not grp_stats:
                continue
                
            print(f"\n--- Grouping: {grp_type.upper()} ---")
            
            # Print header
            print(f"{'Symbol':<10} {'Horizon':<8} {'Outcome':<14} {'N':<6} {'Mean':<10} {'Median':<10} {'Std':<10} {'WinRate':<8}")
            print("-" * 80)
            
            for s in grp_stats:
                sym_str = s.symbol or "ALL"
                hor_str = s.horizon or "ALL"
                n_str   = str(s.sample.N)
                
                mean_str = f"{s.descriptive.mean:.6f}" if s.descriptive.mean is not None else "null"
                med_str  = f"{s.descriptive.median:.6f}" if s.descriptive.median is not None else "null"
                std_str  = f"{s.descriptive.std:.6f}" if s.descriptive.std is not None else "null"
                
                win_str  = f"{s.returns.win_rate:.2%}" if (s.returns and s.returns.win_rate is not None) else "null"
                
                print(f"{sym_str:<10} {hor_str:<8} {s.outcome_name:<14} {n_str:<6} {mean_str:<10} {med_str:<10} {std_str:<10} {win_str:<8}")

    print()
    return 0


def main() -> None:
    parser = argparse.ArgumentParser(description="Research Engine V1")
    sub = parser.add_subparsers(dest="command", required=True)

    run_p = sub.add_parser("run", help="Execute a research study")
    run_p.add_argument("--symbols",            required=True,  help="Comma-separated symbols")
    run_p.add_argument("--feature",            required=True,  help="Feature name (FeatureRow field)")
    run_p.add_argument("--operator",           required=True,  help="> >= < <= == !=")
    run_p.add_argument("--threshold",          required=True,  type=float)
    run_p.add_argument("--event-mode",         default="crossing",          help="condition | crossing")
    run_p.add_argument("--crossing-direction", default="any",               help="cross_up | cross_down | any")
    run_p.add_argument("--event-policy",       default="every_observation", help="every_observation | first_entry")
    run_p.add_argument("--horizons",           required=True,  help="Comma-separated horizon minutes, e.g. 1,3,5,10")
    run_p.add_argument("--price-feature",      default="mid_price",         help="FeatureRow field to use as price")
    run_p.add_argument("--start",              required=True,  help="ISO-8601 UTC start datetime")
    run_p.add_argument("--end",                required=True,  help="ISO-8601 UTC end datetime")
    run_p.add_argument("--research-id",        default="",                  help="Optional explicit research ID")
    
    # Phase 2 args
    run_p.add_argument("--statistics",         action="store_true",         help="Compute descriptive statistics")
    run_p.add_argument("--group-by",           action="append",             help="overall, symbol, horizon, symbol_horizon (can be specified multiple times)")

    args = parser.parse_args()
    
    # Default group_by to overall and horizon if stats requested but not provided
    if args.command == "run" and args.statistics and not args.group_by:
        args.group_by = ["overall", "horizon"]
    if args.command == "run":
        sys.exit(cmd_run(args))


if __name__ == "__main__":
    main()
