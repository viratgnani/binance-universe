"""
market_data/quality.py

Data-quality reporting for stored OHLCV and trade data.

This module reads stored data and applies integrity checks to produce
a comprehensive QualityReport.  It never modifies data.

Reports include:
  - Expected vs actual candle counts
  - Gap count and locations
  - Duplicate count
  - Invalid record count
  - Out-of-order records
  - Coverage percentage
  - Per-symbol summary

Missing candles are reported but NOT filled.  If the exchange had no
activity in an interval, the gap is a real fact to preserve.
"""

from __future__ import annotations

import logging
import math
from datetime import datetime, timezone

from market_data.config import MarketDataConfig, config as default_config
from market_data.integrity import (
    run_all_candle_checks,
    run_all_trade_checks,
)
from market_data.models import (
    Dataset,
    IntervalCoverage,
    IntegrityViolation,
    QualityReport,
    TradesCoverage,
    ViolationType,
)
from market_data.ohlcv_store import OHLCVStore
from market_data.trades_store import TradesStore

logger = logging.getLogger(__name__)


def _count_violations(
    violations: list[IntegrityViolation],
    vtype: ViolationType,
) -> int:
    return sum(1 for v in violations if v.violation_type == vtype)


def _expected_candle_count(
    start: datetime,
    end: datetime,
    interval: str,
    cfg: MarketDataConfig,
) -> int:
    """
    Calculate the expected number of candles in [start, end] for *interval*.

    Uses integer arithmetic on millisecond timestamps to avoid floating-point
    rounding errors.
    """
    step_ms = cfg.INTERVAL_MS.get(interval, 0)
    if step_ms == 0:
        return 0
    start_ms = int(start.astimezone(timezone.utc).timestamp() * 1000)
    end_ms   = int(end.astimezone(timezone.utc).timestamp()   * 1000)
    # Align start_ms to interval boundary (floor)
    start_aligned = (start_ms // step_ms) * step_ms
    return max(0, (end_ms - start_aligned) // step_ms + 1)


def generate_ohlcv_report(
    symbols: list[str],
    interval: str,
    start: datetime,
    end: datetime,
    cfg: MarketDataConfig = default_config,
) -> QualityReport:
    """
    Generate a data-quality report for stored OHLCV data.

    Parameters
    ----------
    symbols:
        Symbols to audit.
    interval:
        Candle interval, e.g. "1m".
    start, end:
        UTC-aware datetime range.
    cfg:
        Configuration.

    Returns
    -------
    :class:`QualityReport` with per-symbol coverage and all violations.
    """
    start_utc = start.astimezone(timezone.utc)
    end_utc   = end.astimezone(timezone.utc)
    store     = OHLCVStore(cfg)

    symbols_with_data: list[str] = []
    symbols_missing:   list[str] = []
    coverage_list: list[IntervalCoverage] = []
    all_violations: list[IntegrityViolation] = []

    expected_per_symbol = _expected_candle_count(start_utc, end_utc, interval, cfg)

    for symbol in symbols:
        candles = store.load(symbol, interval, start_utc, end_utc)

        if not candles:
            symbols_missing.append(symbol)
            logger.warning(
                "quality: no OHLCV data for %s %s in [%s, %s]",
                symbol, interval, start_utc.isoformat(), end_utc.isoformat(),
            )
            coverage_list.append(
                IntervalCoverage(
                    symbol=symbol,
                    interval=interval,
                    start=start_utc,
                    end=end_utc,
                    expected_candles=expected_per_symbol,
                    actual_candles=0,
                    missing_candles=expected_per_symbol,
                    duplicate_candles=0,
                    invalid_ohlc=0,
                    out_of_order=0,
                    coverage_pct=0.0,
                )
            )
            continue

        symbols_with_data.append(symbol)
        violations = run_all_candle_checks(candles, interval)
        all_violations.extend(violations)

        n_actual     = len(candles)
        n_duplicates = _count_violations(violations, ViolationType.DUPLICATE_CANDLE)
        n_missing    = _count_violations(violations, ViolationType.MISSING_CANDLE)
        # Each MISSING_CANDLE violation reports N missing; parse the count
        n_missing_total = _compute_missing_total(violations)
        n_invalid_ohlc  = _count_violations(violations, ViolationType.INVALID_OHLC)
        n_out_of_order  = _count_violations(violations, ViolationType.OUT_OF_ORDER)
        coverage_pct    = (
            min(100.0, n_actual / expected_per_symbol * 100)
            if expected_per_symbol > 0 else 0.0
        )

        coverage_list.append(
            IntervalCoverage(
                symbol=symbol,
                interval=interval,
                start=start_utc,
                end=end_utc,
                expected_candles=expected_per_symbol,
                actual_candles=n_actual,
                missing_candles=n_missing_total,
                duplicate_candles=n_duplicates,
                invalid_ohlc=n_invalid_ohlc,
                out_of_order=n_out_of_order,
                coverage_pct=round(coverage_pct, 2),
            )
        )

        if violations:
            logger.warning(
                "quality: %s %s — %d violation(s) in %d candles",
                symbol, interval, len(violations), n_actual,
            )

    return QualityReport(
        dataset=Dataset.OHLCV,
        interval=interval,
        start=start_utc,
        end=end_utc,
        symbols_requested=symbols,
        symbols_with_data=symbols_with_data,
        symbols_missing=symbols_missing,
        ohlcv_coverage=coverage_list,
        total_violations=len(all_violations),
        all_violations=all_violations,
    )


def generate_trades_report(
    symbols: list[str],
    start: datetime,
    end: datetime,
    cfg: MarketDataConfig = default_config,
) -> QualityReport:
    """
    Generate a data-quality report for stored aggregate trades.
    """
    start_utc = start.astimezone(timezone.utc)
    end_utc   = end.astimezone(timezone.utc)
    store     = TradesStore(cfg)

    symbols_with_data: list[str] = []
    symbols_missing:   list[str] = []
    coverage_list: list[TradesCoverage] = []
    all_violations: list[IntegrityViolation] = []

    for symbol in symbols:
        trades = store.load(symbol, start_utc, end_utc)

        if not trades:
            symbols_missing.append(symbol)
            coverage_list.append(
                TradesCoverage(
                    symbol=symbol,
                    start=start_utc,
                    end=end_utc,
                    actual_trades=0,
                    duplicate_trades=0,
                    invalid_trades=0,
                )
            )
            continue

        symbols_with_data.append(symbol)
        violations = run_all_trade_checks(trades)
        all_violations.extend(violations)

        n_duplicates = _count_violations(violations, ViolationType.DUPLICATE_TRADE)
        n_invalid    = (
            _count_violations(violations, ViolationType.INVALID_TRADE_PRICE)
            + _count_violations(violations, ViolationType.INVALID_TRADE_QTY)
        )

        coverage_list.append(
            TradesCoverage(
                symbol=symbol,
                start=start_utc,
                end=end_utc,
                actual_trades=len(trades),
                duplicate_trades=n_duplicates,
                invalid_trades=n_invalid,
            )
        )

    return QualityReport(
        dataset=Dataset.TRADES,
        start=start_utc,
        end=end_utc,
        symbols_requested=symbols,
        symbols_with_data=symbols_with_data,
        symbols_missing=symbols_missing,
        trades_coverage=coverage_list,
        total_violations=len(all_violations),
        all_violations=all_violations,
    )


def print_ohlcv_report(report: QualityReport) -> None:
    """Print a human-readable OHLCV quality report to stdout."""
    sep = "=" * 70
    print(f"\n{sep}")
    print(f"OHLCV Quality Report - {report.interval}")
    print(f"Range : {report.start.isoformat()} -> {report.end.isoformat()}")
    print(f"Symbols requested : {len(report.symbols_requested)}")
    print(f"Symbols with data : {len(report.symbols_with_data)}")
    print(f"Symbols missing   : {len(report.symbols_missing)}")
    print(f"Total violations  : {report.total_violations}")
    print(sep)
    print(
        f"{'Symbol':<18} {'Expected':>10} {'Actual':>8} "
        f"{'Missing':>8} {'Dupes':>6} {'Invalid':>8} {'Order':>6} {'Cover%':>7}"
    )
    print("-" * 70)
    for c in report.ohlcv_coverage:
        print(
            f"{c.symbol:<18} {c.expected_candles:>10} {c.actual_candles:>8} "
            f"{c.missing_candles:>8} {c.duplicate_candles:>6} {c.invalid_ohlc:>8} "
            f"{c.out_of_order:>6} {c.coverage_pct:>7.1f}%"
        )
    print(sep)


def print_trades_report(report: QualityReport) -> None:
    """Print a human-readable trades quality report to stdout."""
    sep = "=" * 70
    print(f"\n{sep}")
    print("Trades Quality Report")
    print(f"Range  : {report.start.isoformat()} -> {report.end.isoformat()}")
    print(f"Symbols: {len(report.symbols_requested)} requested, "
          f"{len(report.symbols_with_data)} with data, "
          f"{len(report.symbols_missing)} missing")
    print(f"Total violations: {report.total_violations}")
    print(sep)
    print(f"{'Symbol':<18} {'Trades':>10} {'Dupes':>8} {'Invalid':>10}")
    print("-" * 70)
    for c in report.trades_coverage:
        print(
            f"{c.symbol:<18} {c.actual_trades:>10} "
            f"{c.duplicate_trades:>8} {c.invalid_trades:>10}"
        )
    print(sep)


# --------------------------------------------------------------------------- #
#  Internal helpers
# --------------------------------------------------------------------------- #


def _compute_missing_total(violations: list[IntegrityViolation]) -> int:
    """
    Sum actual missing candle counts from violation detail strings.

    The detail format is: "N missing candle(s) starting at ..."
    """
    total = 0
    for v in violations:
        if v.violation_type == ViolationType.MISSING_CANDLE:
            try:
                # Parse "N missing candle(s)..."
                n_str = v.detail.split()[0]
                total += int(n_str)
            except (IndexError, ValueError):
                total += 1  # conservative: count as at least 1
    return total
