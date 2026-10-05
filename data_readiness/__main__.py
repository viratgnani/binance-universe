"""
data_readiness/__main__.py

CLI entry point for the Historical Data Readiness Layer.

Commands
--------
audit      — Inspect currently stored OHLCV data and classify readiness.
             Makes NO API calls.

acquire    — Download historical 1m OHLCV for specified symbols via the
             frozen backfill_ohlcv function. Supports --dry-run.

report     — Generate the full data_readiness_report.md and data_readiness.json.

Usage Examples
--------------
# Audit what is currently on disk
python -m data_readiness audit

# Audit specific symbols
python -m data_readiness audit --symbols XRPUSDT,BNBUSDT,ADAUSDT

# Show what would be acquired (no API calls)
python -m data_readiness acquire --symbols XRPUSDT,BNBUSDT --start 2024-01-01 --end 2024-02-01 --dry-run

# Actually download data (calls frozen backfill_ohlcv)
python -m data_readiness acquire --symbols XRPUSDT,BNBUSDT --start 2024-01-01 --end 2024-02-01

# Use full eligible alt universe (reads snapshot, excludes BTC/ETH/SOL)
python -m data_readiness acquire --symbols eligible_alts --start 2024-09-01 --end 2025-09-01

# Generate the full readiness report after acquisition
python -m data_readiness report --symbols eligible_alts

Architecture Note
-----------------
This CLI is a thin orchestration layer. It never imports from frozen layers
except to CALL their public APIs as black-box dependencies:
  - market_data.backfill.backfill_ohlcv  (acquisition)
  - market_data.ohlcv_store.OHLCVStore   (read-only access)
  - market_data.readiness.*              (readiness classification)

No frozen module is modified.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import sys
from datetime import datetime, timezone
from pathlib import Path

from market_data.readiness import (
    ExperimentReadinessSpec,
    ReadinessClassifier,
    ReadinessStatus,
    SymbolReadiness,
    load_eligible_alt_symbols,
    load_universe_snapshot_status,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(name)s  %(message)s",
    datefmt="%Y-%m-%dT%H:%M:%SZ",
)
logger = logging.getLogger("data_readiness")


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_DEFAULT_SPEC = ExperimentReadinessSpec()
_RESULTS_DIR  = Path("research_results")
_REPORT_MD    = _RESULTS_DIR / "data_readiness_report.md"
_REPORT_JSON  = _RESULTS_DIR / "data_readiness.json"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _parse_datetime(s: str) -> datetime:
    s = s.strip()
    if len(s) == 10:
        s += "T00:00:00Z"
    s = s.replace("Z", "+00:00")
    dt = datetime.fromisoformat(s)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _parse_symbols(raw: str, spec: ExperimentReadinessSpec) -> list[str]:
    """
    Parse symbol list. Expands 'eligible_alts' to the full universe list.
    Never silently uses BTC/ETH/SOL for the alt experiment.
    """
    if raw.strip().lower() == "eligible_alts":
        syms = load_eligible_alt_symbols(exclude=spec.exclude_symbols)
        if not syms:
            logger.error(
                "No eligible alt symbols found in snapshot. "
                "Run 'python -m universe refresh' first or specify --symbols explicitly."
            )
            sys.exit(1)
        logger.info("Loaded %d eligible alt symbols from snapshot.", len(syms))
        return syms

    return [s.strip().upper() for s in raw.split(",") if s.strip()]


def _status_icon(status: ReadinessStatus) -> str:
    return {
        ReadinessStatus.READY:      "READY     ",
        ReadinessStatus.INCOMPLETE: "INCOMPLETE",
        ReadinessStatus.INVALID:    "INVALID   ",
        ReadinessStatus.MISSING:    "MISSING   ",
        ReadinessStatus.EXCLUDED:   "EXCLUDED  ",
    }.get(status, status.value)


def _print_readiness_table(results: list[SymbolReadiness]) -> None:
    """Print a human-readable readiness table to stdout."""
    sep = "=" * 110
    print(f"\n{sep}")
    print(
        f"{'Symbol':<20} {'Status':<12} {'Candles':>9} {'Duration(d)':>11} "
        f"{'Gaps':>5} {'MaxGap(m)':>10} {'Dupes':>6} {'Invalid':>8} {'Cover%':>7}"
    )
    print("-" * 110)
    for r in results:
        print(
            f"{r.symbol:<20} {_status_icon(r.status):<12} {r.candle_count:>9,} "
            f"{r.duration_days:>11.1f} {r.gaps:>5} {r.max_gap_minutes:>10} "
            f"{r.duplicate_candles:>6} {r.invalid_candles:>8} {r.coverage_pct:>7.1f}%"
        )
    print(sep)


# ---------------------------------------------------------------------------
# Subcommands
# ---------------------------------------------------------------------------

def _cmd_audit(args: argparse.Namespace) -> int:
    """Audit currently stored data. No API calls."""
    spec = _DEFAULT_SPEC

    # Determine symbols to audit
    if hasattr(args, "symbols") and args.symbols:
        symbols = _parse_symbols(args.symbols, spec)
    else:
        # Default: all symbols with any OHLCV stored
        from market_data.ohlcv_store import OHLCVStore
        stored = OHLCVStore().list_symbols()
        if not stored:
            print("\nNo OHLCV data found on disk. Run 'acquire' first.\n")
            return 0
        symbols = stored
        logger.info("Auditing all %d stored symbols.", len(symbols))

    print("\n" + "=" * 60)
    print("DATA READINESS AUDIT")
    print("=" * 60)
    print(f"Interval         : {spec.interval}")
    print(f"RSI period       : {spec.rsi_period}")
    print(f"Min candles (RSI): {spec.rsi_min_candles}")
    print(f"Preferred history: {spec.preferred_history_days} days")
    print(f"Excluded symbols : {', '.join(sorted(spec.exclude_symbols))}")
    print(f"Symbols to audit : {len(symbols)}")
    print("-" * 60)

    classifier = ReadinessClassifier()
    start = _parse_datetime(args.start) if hasattr(args, "start") and args.start else None
    end   = _parse_datetime(args.end)   if hasattr(args, "end")   and args.end   else None

    summary = classifier.classify_all(symbols, spec, start=start, end=end)

    # Print table
    _print_readiness_table(summary.results)

    # Print aggregate
    print(f"\nAGGREGATE SUMMARY")
    print(f"  Symbols evaluated : {summary.symbols_evaluated}")
    print(f"  READY             : {summary.symbols_ready}")
    print(f"  INCOMPLETE        : {summary.symbols_incomplete}")
    print(f"  INVALID           : {summary.symbols_invalid}")
    print(f"  MISSING           : {summary.symbols_missing}")
    print(f"  EXCLUDED          : {summary.symbols_excluded}")
    print(f"  Total candles     : {summary.total_candles:,}")
    if summary.earliest_global:
        print(f"  Earliest candle   : {summary.earliest_global.isoformat()}")
        print(f"  Latest candle     : {summary.latest_global.isoformat()}")
    print(f"  Duration (min)    : {summary.duration_days_min:.1f} days")
    print(f"  Duration (median) : {summary.duration_days_median:.1f} days")
    print(f"  Duration (max)    : {summary.duration_days_max:.1f} days")

    # Universe snapshot status
    snap = load_universe_snapshot_status()
    print(f"\nUNIVERSE SNAPSHOT STATUS")
    print(f"  Snapshot found    : {snap['snapshot_found']}")
    if snap["snapshot_found"]:
        print(f"  Snapshot file     : {snap['snapshot_file']}")
        print(f"  Snapshot time     : {snap['snapshot_timestamp']}")
        print(f"  Total records     : {snap['total_records']}")
        print(f"  ACTIVE_TOP_100    : {snap['active_top_100_count']}")
        print(f"  WATCHLIST         : {snap['watchlist_count']}")
        print(f"  Ranked (non-None) : {snap['ranked_count']}")
        print(f"  Historical ranked : {snap['historical_ranked_available']}")
    if snap.get("limitation"):
        print(f"\n  LIMITATION: {snap['limitation']}")

    # Experiment readiness verdict
    print(f"\nEXPERIMENT READINESS VERDICT")
    if summary.symbols_ready == 0:
        verdict = "NOT READY"
        detail  = "Zero symbols have sufficient OHLCV history for the RSI(14) event study."
    elif summary.symbols_ready < 10:
        verdict = "MARGINALLY READY"
        detail  = (
            f"Only {summary.symbols_ready} symbol(s) are READY. "
            "A small sample limits the statistical value of the event study."
        )
    else:
        verdict = "READY"
        detail  = f"{summary.symbols_ready} symbol(s) are READY for the RSI(14) event study."

    print(f"  Verdict : {verdict}")
    print(f"  Detail  : {detail}")
    print()

    return 0 if summary.symbols_ready > 0 else 1


async def _cmd_acquire_async(args: argparse.Namespace) -> int:
    """Acquire historical 1m OHLCV via the frozen backfill_ohlcv function."""
    spec    = _DEFAULT_SPEC
    symbols = _parse_symbols(args.symbols, spec)
    start   = _parse_datetime(args.start)
    end     = _parse_datetime(args.end)
    interval = getattr(args, "interval", "1m")

    # Enforce: never acquire for excluded symbols silently
    excluded_requested = [s for s in symbols if s.upper() in spec.exclude_symbols]
    if excluded_requested:
        logger.warning(
            "The following symbols are excluded from the RSI experiment and will be "
            "SKIPPED from acquisition: %s", ", ".join(excluded_requested)
        )
        symbols = [s for s in symbols if s.upper() not in spec.exclude_symbols]
        if not symbols:
            print("All requested symbols are excluded. Nothing to acquire.")
            return 1

    print("\n" + "=" * 60)
    print("DATA ACQUISITION")
    print("=" * 60)
    print(f"Symbols       : {len(symbols)}")
    print(f"Interval      : {interval}")
    print(f"Start         : {start.isoformat()}")
    print(f"End           : {end.isoformat()}")
    print(f"Dry run       : {args.dry_run}")
    print("-" * 60)

    # Estimated candles (informational)
    delta_days = (end - start).total_seconds() / 86400
    est_candles = int(delta_days * 24 * 60)
    print(f"Estimated candles per symbol : ~{est_candles:,}")
    print(f"Estimated total candles      : ~{est_candles * len(symbols):,}")

    if args.dry_run:
        print("\nDRY RUN — No API calls will be made.")
        print("The following would be acquired:")
        for sym in symbols:
            line = f"  {sym}: {interval} from {start.date()} to {end.date()} (~{est_candles:,} candles)"
            sys.stdout.buffer.write((line + "\n").encode("utf-8", errors="replace"))
        print("\nRe-run without --dry-run to perform acquisition.")
        return 0

    # Delegate entirely to the frozen backfill_ohlcv function
    from market_data.backfill import backfill_ohlcv
    from market_data.config import config as md_config

    logger.info("Starting acquisition via frozen backfill_ohlcv...")
    summary = await backfill_ohlcv(
        symbols=symbols,
        interval=interval,
        start=start,
        end=end,
        cfg=md_config,
    )

    # Print summary
    print(f"\nACQUISITION COMPLETE")
    print(f"  Symbols requested : {summary.symbols_requested}")
    print(f"  Succeeded         : {summary.symbols_succeeded}")
    print(f"  Failed            : {summary.symbols_failed}")
    print(f"  Candles written   : {summary.total_records_written:,}")
    print(f"  Candles skipped   : {summary.total_records_skipped:,}")
    print(f"  Violations found  : {summary.total_violations}")

    if summary.symbols_failed > 0:
        print("\n  FAILED SYMBOLS:")
        for r in summary.results:
            if not r.success:
                err = r.error.error_message if r.error else "unknown error"
                print(f"    {r.symbol}: {err}")

    return 0 if summary.symbols_failed == 0 else 1


def _cmd_acquire(args: argparse.Namespace) -> int:
    return asyncio.run(_cmd_acquire_async(args))


def _cmd_report(args: argparse.Namespace) -> int:
    """Generate data_readiness_report.md and data_readiness.json."""
    spec = _DEFAULT_SPEC

    if hasattr(args, "symbols") and args.symbols:
        symbols = _parse_symbols(args.symbols, spec)
    else:
        from market_data.ohlcv_store import OHLCVStore
        symbols = OHLCVStore().list_symbols()
        if not symbols:
            print("No OHLCV data found. Run 'acquire' first.")
            return 1

    start = _parse_datetime(args.start) if hasattr(args, "start") and args.start else None
    end   = _parse_datetime(args.end)   if hasattr(args, "end")   and args.end   else None

    classifier = ReadinessClassifier()
    summary = classifier.classify_all(symbols, spec, start=start, end=end)
    snap    = load_universe_snapshot_status()

    _results_dir = _RESULTS_DIR
    _results_dir.mkdir(parents=True, exist_ok=True)

    # --- Write JSON ---
    json_payload = _build_json_report(summary, snap)
    _REPORT_JSON.write_text(json.dumps(json_payload, indent=2, default=str), encoding="utf-8")
    logger.info("JSON report written to %s", _REPORT_JSON)

    # --- Write Markdown ---
    md = _build_markdown_report(summary, snap)
    _REPORT_MD.write_text(md, encoding="utf-8")
    logger.info("Markdown report written to %s", _REPORT_MD)

    print(f"\nReports written:")
    print(f"  {_REPORT_MD}")
    print(f"  {_REPORT_JSON}")
    print(f"\nReadiness: {summary.symbols_ready} READY / {summary.symbols_evaluated} evaluated")

    return 0 if summary.symbols_ready > 0 else 1


# ---------------------------------------------------------------------------
# Report builders
# ---------------------------------------------------------------------------

def _build_json_report(summary, snap: dict) -> dict:
    return {
        "report_timestamp": datetime.now(timezone.utc).isoformat(),
        "spec": {
            "interval": summary.spec.interval,
            "rsi_period": summary.spec.rsi_period,
            "rsi_min_candles": summary.spec.rsi_min_candles,
            "preferred_history_days": summary.spec.preferred_history_days,
            "required_forward_minutes": summary.spec.required_forward_minutes,
            "exclude_symbols": sorted(summary.spec.exclude_symbols),
        },
        "aggregate": {
            "symbols_evaluated": summary.symbols_evaluated,
            "symbols_ready": summary.symbols_ready,
            "symbols_incomplete": summary.symbols_incomplete,
            "symbols_invalid": summary.symbols_invalid,
            "symbols_missing": summary.symbols_missing,
            "symbols_excluded": summary.symbols_excluded,
            "total_candles": summary.total_candles,
            "earliest_global": summary.earliest_global.isoformat() if summary.earliest_global else None,
            "latest_global": summary.latest_global.isoformat() if summary.latest_global else None,
            "duration_days_min": summary.duration_days_min,
            "duration_days_median": summary.duration_days_median,
            "duration_days_max": summary.duration_days_max,
        },
        "universe_snapshot": snap,
        "experiment_ready": summary.experiment_ready,
        "experiment_readiness_verdict": (
            "READY" if summary.symbols_ready >= 10
            else "MARGINALLY_READY" if summary.symbols_ready > 0
            else "NOT_READY"
        ),
        "symbols": [
            {
                "symbol": r.symbol,
                "status": r.status.value,
                "candle_count": r.candle_count,
                "earliest": r.earliest.isoformat() if r.earliest else None,
                "latest": r.latest.isoformat() if r.latest else None,
                "duration_days": r.duration_days,
                "gaps": r.gaps,
                "missing_candles": r.missing_candles,
                "max_gap_minutes": r.max_gap_minutes,
                "duplicate_candles": r.duplicate_candles,
                "invalid_candles": r.invalid_candles,
                "coverage_pct": r.coverage_pct,
                "has_rsi_init": r.has_rsi_init,
                "has_preferred_history": r.has_preferred_history,
                "reason": r.reason,
            }
            for r in summary.results
        ],
    }


def _build_markdown_report(summary, snap: dict) -> str:
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    verdict = (
        "READY" if summary.symbols_ready >= 10
        else "MARGINALLY READY" if summary.symbols_ready > 0
        else "NOT READY"
    )

    lines = [
        "# Data Readiness Report",
        f"\nGenerated: {now}",
        "",
        "## Experiment Readiness Specification",
        "",
        f"| Parameter | Value |",
        f"|---|---|",
        f"| Interval | {summary.spec.interval} |",
        f"| RSI Period | {summary.spec.rsi_period} |",
        f"| Min candles for RSI init | {summary.spec.rsi_min_candles} |",
        f"| Preferred history | {summary.spec.preferred_history_days} days |",
        f"| Max forward horizon | {summary.spec.required_forward_minutes} minutes |",
        f"| Excluded symbols | {', '.join(sorted(summary.spec.exclude_symbols))} |",
        "",
        "## Coverage Summary",
        "",
        f"| Metric | Value |",
        f"|---|---|",
        f"| Symbols evaluated | {summary.symbols_evaluated} |",
        f"| READY | {summary.symbols_ready} |",
        f"| INCOMPLETE | {summary.symbols_incomplete} |",
        f"| INVALID | {summary.symbols_invalid} |",
        f"| MISSING | {summary.symbols_missing} |",
        f"| EXCLUDED | {summary.symbols_excluded} |",
        f"| Total candles | {summary.total_candles:,} |",
        f"| Earliest candle | {summary.earliest_global.isoformat() if summary.earliest_global else 'N/A'} |",
        f"| Latest candle | {summary.latest_global.isoformat() if summary.latest_global else 'N/A'} |",
        f"| Duration min | {summary.duration_days_min:.1f} days |",
        f"| Duration median | {summary.duration_days_median:.1f} days |",
        f"| Duration max | {summary.duration_days_max:.1f} days |",
        "",
        "## Per-Symbol Coverage",
        "",
        "| Symbol | Status | Candles | Duration (days) | Gaps | Max Gap (min) | Dupes | Invalid | Coverage % |",
        "|---|---|---|---|---|---|---|---|---|",
    ]

    for r in summary.results:
        lines.append(
            f"| {r.symbol} | {r.status.value} | {r.candle_count:,} | "
            f"{r.duration_days:.1f} | {r.gaps} | {r.max_gap_minutes} | "
            f"{r.duplicate_candles} | {r.invalid_candles} | {r.coverage_pct:.1f}% |"
        )

    lines += [
        "",
        "## Universe Snapshot Status",
        "",
        f"| Field | Value |",
        f"|---|---|",
        f"| Snapshot found | {snap['snapshot_found']} |",
        f"| Snapshot file | {snap.get('snapshot_file', 'N/A')} |",
        f"| Snapshot timestamp | {snap.get('snapshot_timestamp', 'N/A')} |",
        f"| Total records | {snap.get('total_records', 0)} |",
        f"| ACTIVE_TOP_100 | {snap.get('active_top_100_count', 0)} |",
        f"| WATCHLIST | {snap.get('watchlist_count', 0)} |",
        f"| Ranked (non-None) | {snap.get('ranked_count', 0)} |",
        f"| Historical ranked available | {snap.get('historical_ranked_available', False)} |",
        "",
    ]

    if snap.get("limitation"):
        lines += [
            "> **UNIVERSE LIMITATION:** " + snap["limitation"],
            "",
        ]

    lines += [
        "## Experiment Readiness Verdict",
        "",
        f"**{verdict}**",
        "",
    ]

    if verdict == "NOT READY":
        lines += [
            "The dataset does not yet contain sufficient historical 1-minute OHLCV data ",
            "for any eligible altcoin symbol to run the RSI(14) > 90 event study.",
            "",
            "### Required Action",
            "",
            "Run the acquisition step:",
            "```bash",
            "python -m data_readiness acquire \\",
            "  --symbols eligible_alts \\",
            "  --start 2024-09-01 \\",
            "  --end 2025-09-01",
            "```",
            "Then re-run `python -m data_readiness report` to update this document.",
        ]
    elif verdict.startswith("MARGINALLY"):
        lines += [
            f"Only {summary.symbols_ready} symbol(s) have sufficient history. ",
            "Consider acquiring more symbol history before running the experiment.",
        ]
    else:
        lines += [
            f"{summary.symbols_ready} symbols are READY for the RSI(14) > 90 event study.",
            "",
            "Ready symbols:",
        ]
        for sym in sorted(summary.ready_symbols()):
            lines.append(f"- {sym}")

    return "\n".join(lines) + "\n"


# ---------------------------------------------------------------------------
# CLI parser
# ---------------------------------------------------------------------------

def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m data_readiness",
        description="Historical Data Readiness Layer for RSI(14) Event Study",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    # audit
    ap = sub.add_parser("audit", help="Inspect stored OHLCV data. No API calls.")
    ap.add_argument("--symbols", default=None,
                    help="Comma-separated symbols, or 'eligible_alts'. Default: all stored.")
    ap.add_argument("--start", default=None, help="Start date (ISO-8601 UTC)")
    ap.add_argument("--end",   default=None, help="End date (ISO-8601 UTC)")

    # acquire
    aqp = sub.add_parser("acquire", help="Download 1m OHLCV via frozen backfill_ohlcv.")
    aqp.add_argument("--symbols", required=True,
                     help="Comma-separated symbols or 'eligible_alts'")
    aqp.add_argument("--start",   required=True, help="Start date (ISO-8601 UTC)")
    aqp.add_argument("--end",     required=True, help="End date (ISO-8601 UTC)")
    aqp.add_argument("--interval", default="1m",
                     help="Candle interval [default: 1m]")
    aqp.add_argument("--dry-run", action="store_true",
                     help="Show what would be downloaded without making API calls")

    # report
    rp = sub.add_parser("report", help="Generate data_readiness_report.md and data_readiness.json")
    rp.add_argument("--symbols", default=None,
                    help="Comma-separated symbols or 'eligible_alts'. Default: all stored.")
    rp.add_argument("--start", default=None, help="Start date filter (ISO-8601 UTC)")
    rp.add_argument("--end",   default=None, help="End date filter (ISO-8601 UTC)")

    return parser


def main() -> None:
    parser = _build_parser()
    args   = parser.parse_args()

    handlers = {
        "audit":   _cmd_audit,
        "acquire": _cmd_acquire,
        "report":  _cmd_report,
    }

    handler = handlers.get(args.command)
    if handler is None:
        parser.print_help()
        sys.exit(1)

    sys.exit(handler(args))


if __name__ == "__main__":
    main()
