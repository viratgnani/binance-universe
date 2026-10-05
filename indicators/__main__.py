"""
indicators/__main__.py

CLI entry point for the Research Indicator Engine.

Usage
-----
python -m indicators generate \\
  --symbols BTCUSDT,ETHUSDT \\
  --indicator rsi \\
  --period 14 \\
  --start 2026-08-31T00:00:00Z \\
  --end 2026-08-31T01:00:00Z
"""

from __future__ import annotations

import argparse
import logging
import sys
from datetime import datetime, timezone

from indicators.models import IndicatorDefinition
from indicators.registry import registry
from indicators.store import IndicatorStore
from research_features.store import FeatureStore

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(name)s  %(message)s",
    datefmt="%Y-%m-%dT%H:%M:%SZ",
)
logger = logging.getLogger("indicators")


def _parse_datetime(s: str) -> datetime:
    s = s.strip().replace("Z", "+00:00")
    dt = datetime.fromisoformat(s)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _parse_symbols(raw: str) -> list[str]:
    return [s.strip().upper() for s in raw.split(",") if s.strip()]


def cmd_generate(args: argparse.Namespace) -> int:
    symbols = _parse_symbols(args.symbols)
    start   = _parse_datetime(args.start)
    end     = _parse_datetime(args.end)
    ind_name = args.indicator.lower()

    try:
        calculator = registry.get_calculator(ind_name)
    except KeyError:
        logger.error(
            "Unknown indicator: %s. Available: %s",
            ind_name, ", ".join(registry.list_available())
        )
        return 1

    # In V1, RSI needs 'period'. Other indicators might need other things.
    # We pass all unknown args matching --param=val (or rely on specific ones).
    # For now, we explicitly handle --period for RSI.
    parameters = {}
    if hasattr(args, "period") and args.period is not None:
        parameters["period"] = args.period

    definition = IndicatorDefinition(
        indicator_name=ind_name,
        indicator_version=calculator.version,
        input_feature=args.input_feature,
        parameters=parameters,
    )

    feature_store = FeatureStore()
    indicator_store = IndicatorStore()

    total_valid = 0
    total_warmup = 0
    total_written = 0
    total_skipped = 0

    print("=" * 62)
    print("RESEARCH INDICATOR ENGINE V1")
    print("=" * 62)
    print(f"Indicator        : {calculator.name.upper()} ({calculator.version})")
    print(f"Parameters       : {parameters}")
    print(f"Input Feature    : {definition.input_feature}")
    print(f"Symbols          : {', '.join(symbols)}")
    print(f"Window           : {start.isoformat()} -> {end.isoformat()}")
    print("-" * 62)

    for sym in symbols:
        # Load from frozen Feature Layer
        features = feature_store.load(sym, start, end)
        if not features:
            logger.warning("No features found for %s in window.", sym)
            continue

        # Extract the required price series
        price_series: list[tuple[datetime, float | None]] = []
        for row in features:
            val = getattr(row, definition.input_feature, None)
            price_series.append((row.timestamp, val))

        # Calculate
        try:
            series = calculator.calculate(sym, price_series, definition)
        except Exception as e:
            logger.error("Failed to calculate %s for %s: %s", ind_name, sym, e)
            continue

        # Persist
        written, skipped = indicator_store.save(series.values)

        total_valid += series.valid_count
        total_warmup += series.warmup_count
        total_written += written
        total_skipped += skipped

        logger.info(
            "[%s] Inputs: %d | Valid %s: %d | Warmup/Missing: %d | Written: %d",
            sym, len(price_series), ind_name.upper(), series.valid_count, series.warmup_count, written
        )

    print("-" * 62)
    print("SUMMARY")
    print("-" * 62)
    print(f"Valid indicator values : {total_valid}")
    print(f"Warmup / Missing inputs: {total_warmup}")
    print(f"New rows persisted     : {total_written}")
    print(f"Rows skipped (dup)     : {total_skipped}")
    print(f"Output directory       : {indicator_store.data_dir}/")
    print("=" * 62)
    print()

    return 0


def main() -> None:
    parser = argparse.ArgumentParser(description="Research Indicator Engine V1")
    sub = parser.add_subparsers(dest="command", required=True)

    gen_p = sub.add_parser("generate", help="Generate indicators from features")
    gen_p.add_argument("--symbols",       required=True, help="Comma-separated symbols")
    gen_p.add_argument("--indicator",     required=True, help="Registered indicator name (e.g. rsi)")
    gen_p.add_argument("--input-feature", default="mid_price", help="FeatureRow field to use as input")
    gen_p.add_argument("--start",         required=True, help="ISO-8601 UTC start datetime")
    gen_p.add_argument("--end",           required=True, help="ISO-8601 UTC end datetime")
    
    # Indicator specific
    gen_p.add_argument("--period",        type=int, help="Lookback period (used by RSI)")

    args = parser.parse_args()
    if args.command == "generate":
        sys.exit(cmd_generate(args))


if __name__ == "__main__":
    main()
