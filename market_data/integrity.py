"""
market_data/integrity.py

Pure data-integrity checking functions for OHLCV candles and aggregate trades.

Design:
  - All functions are pure (no I/O, no side-effects).
  - Input lists may be unsorted; functions sort internally where needed.
  - Functions DETECT and REPORT problems; they never silently repair data.
  - Each function returns a (possibly empty) list of IntegrityViolation objects.

OHLCV checks
------------
  check_candle_duplicates   — same symbol + interval + open_time
  check_candle_gaps         — missing expected timestamps given the interval
  check_candle_sort_order   — out-of-order open_times
  check_ohlc_validity       — impossible OHLC relationships, negative volume
  check_timestamp_alignment — open_time not on expected interval boundary

Trade checks
------------
  check_trade_duplicates    — same symbol + agg_trade_id
  check_trade_validity      — price ≤ 0, quantity ≤ 0, timestamp obviously wrong
  check_trade_sort_order    — out-of-order timestamps / IDs

All checks
----------
  run_all_candle_checks     — convenience wrapper for all OHLCV checks
  run_all_trade_checks      — convenience wrapper for all trade checks
"""

from __future__ import annotations

from datetime import datetime, timezone, timedelta

from market_data.models import (
    AggTrade,
    Candle,
    Dataset,
    IntegrityViolation,
    ViolationType,
)


# --------------------------------------------------------------------------- #
#  Interval helpers
# --------------------------------------------------------------------------- #

_INTERVAL_MS: dict[str, int] = {
    "1m":  60_000,
    "5m":  300_000,
    "15m": 900_000,
    "1h":  3_600_000,
    "4h":  14_400_000,
    "1d":  86_400_000,
}


def _interval_ms(interval: str) -> int:
    ms = _INTERVAL_MS.get(interval)
    if ms is None:
        raise ValueError(f"Unknown interval: {interval!r}")
    return ms


def _to_ms(dt: datetime) -> int:
    """Convert UTC-aware datetime to integer milliseconds epoch."""
    return int(dt.timestamp() * 1000)


# --------------------------------------------------------------------------- #
#  OHLCV integrity checks
# --------------------------------------------------------------------------- #


def check_candle_duplicates(
    candles: list[Candle],
) -> list[IntegrityViolation]:
    """
    Detect duplicate candles (same symbol + interval + open_time).

    Returns one violation per duplicate open_time beyond the first occurrence.
    """
    if not candles:
        return []

    symbol   = candles[0].symbol
    interval = candles[0].interval
    seen: set[datetime] = set()
    violations: list[IntegrityViolation] = []

    for c in candles:
        key = c.open_time
        if key in seen:
            violations.append(
                IntegrityViolation(
                    symbol=symbol,
                    dataset=Dataset.OHLCV,
                    interval=interval,
                    violation_type=ViolationType.DUPLICATE_CANDLE,
                    detail=f"Duplicate open_time: {c.open_time.isoformat()}",
                )
            )
        else:
            seen.add(key)

    return violations


def check_candle_gaps(
    candles: list[Candle],
    interval: str,
) -> list[IntegrityViolation]:
    """
    Detect gaps in the candle sequence.

    Assumes candles belong to the same symbol and interval.
    Sorts by open_time before checking.

    A gap is any open_time that is absent when the expected sequence is
    open_time[i] + interval_ms = open_time[i+1].
    """
    if len(candles) < 2:
        return []

    symbol = candles[0].symbol
    step_ms = _interval_ms(interval)
    sorted_candles = sorted(candles, key=lambda c: c.open_time)
    violations: list[IntegrityViolation] = []

    for i in range(len(sorted_candles) - 1):
        t_curr = _to_ms(sorted_candles[i].open_time)
        t_next = _to_ms(sorted_candles[i + 1].open_time)
        expected_next = t_curr + step_ms

        if t_next > expected_next:
            n_missing = (t_next - expected_next) // step_ms
            first_missing = datetime.fromtimestamp(
                expected_next / 1000.0, tz=timezone.utc
            )
            violations.append(
                IntegrityViolation(
                    symbol=symbol,
                    dataset=Dataset.OHLCV,
                    interval=interval,
                    violation_type=ViolationType.MISSING_CANDLE,
                    detail=(
                        f"{n_missing} missing candle(s) starting at "
                        f"{first_missing.isoformat()} "
                        f"(gap between {sorted_candles[i].open_time.isoformat()} "
                        f"and {sorted_candles[i + 1].open_time.isoformat()})"
                    ),
                )
            )

    return violations


def check_candle_sort_order(
    candles: list[Candle],
) -> list[IntegrityViolation]:
    """
    Detect out-of-order candles (open_time[i] > open_time[i+1]).

    Returns violations for each inversion.
    """
    if len(candles) < 2:
        return []

    symbol   = candles[0].symbol
    interval = candles[0].interval
    violations: list[IntegrityViolation] = []

    for i in range(len(candles) - 1):
        if candles[i].open_time > candles[i + 1].open_time:
            violations.append(
                IntegrityViolation(
                    symbol=symbol,
                    dataset=Dataset.OHLCV,
                    interval=interval,
                    violation_type=ViolationType.OUT_OF_ORDER,
                    detail=(
                        f"Candle at index {i} ({candles[i].open_time.isoformat()}) "
                        f"> index {i+1} ({candles[i+1].open_time.isoformat()})"
                    ),
                )
            )

    return violations


def check_ohlc_validity(
    candles: list[Candle],
) -> list[IntegrityViolation]:
    """
    Detect impossible OHLC relationships and non-positive volume.

    Invalid conditions:
      high < low
      high < open
      high < close
      low  > open
      low  > close
      volume < 0
      quote_volume < 0
    """
    if not candles:
        return []

    symbol   = candles[0].symbol
    interval = candles[0].interval
    violations: list[IntegrityViolation] = []

    for c in candles:
        ts = c.open_time.isoformat()
        problems: list[str] = []

        if c.high < c.low:
            problems.append(f"high({c.high}) < low({c.low})")
        if c.high < c.open:
            problems.append(f"high({c.high}) < open({c.open})")
        if c.high < c.close:
            problems.append(f"high({c.high}) < close({c.close})")
        if c.low > c.open:
            problems.append(f"low({c.low}) > open({c.open})")
        if c.low > c.close:
            problems.append(f"low({c.low}) > close({c.close})")
        if c.volume < 0:
            problems.append(f"volume({c.volume}) < 0")
        if c.quote_volume < 0:
            problems.append(f"quote_volume({c.quote_volume}) < 0")

        if problems:
            vtype = (
                ViolationType.INVALID_OHLC
                if any("volume" not in p for p in problems)
                else ViolationType.INVALID_VOLUME
            )
            violations.append(
                IntegrityViolation(
                    symbol=symbol,
                    dataset=Dataset.OHLCV,
                    interval=interval,
                    violation_type=vtype,
                    detail=f"open_time={ts}: {'; '.join(problems)}",
                )
            )

    return violations


def check_timestamp_alignment(
    candles: list[Candle],
    interval: str,
) -> list[IntegrityViolation]:
    """
    Verify that every candle's open_time falls exactly on an interval boundary.

    For example, a 1m candle must have open_time with seconds=0, microseconds=0.
    A 1h candle must have minutes=0, seconds=0, microseconds=0.

    Uses modulo arithmetic on millisecond epoch timestamps.
    """
    if not candles:
        return []

    symbol   = candles[0].symbol
    step_ms  = _interval_ms(interval)
    violations: list[IntegrityViolation] = []

    for c in candles:
        t_ms = _to_ms(c.open_time)
        if t_ms % step_ms != 0:
            violations.append(
                IntegrityViolation(
                    symbol=symbol,
                    dataset=Dataset.OHLCV,
                    interval=interval,
                    violation_type=ViolationType.TIMESTAMP_MISALIGN,
                    detail=(
                        f"open_time {c.open_time.isoformat()} "
                        f"({t_ms} ms) is not aligned to {interval} "
                        f"({step_ms} ms boundary)"
                    ),
                )
            )

    return violations


def run_all_candle_checks(
    candles: list[Candle],
    interval: str,
) -> list[IntegrityViolation]:
    """Run all OHLCV integrity checks and return the combined violation list."""
    if not candles:
        return []
    violations: list[IntegrityViolation] = []
    violations += check_candle_sort_order(candles)
    violations += check_candle_duplicates(candles)
    violations += check_candle_gaps(candles, interval)
    violations += check_ohlc_validity(candles)
    violations += check_timestamp_alignment(candles, interval)
    return violations


# --------------------------------------------------------------------------- #
#  Trade integrity checks
# --------------------------------------------------------------------------- #


def check_trade_duplicates(
    trades: list[AggTrade],
) -> list[IntegrityViolation]:
    """
    Detect duplicate aggregate trades (same symbol + agg_trade_id).
    """
    if not trades:
        return []

    symbol = trades[0].symbol
    seen: set[int] = set()
    violations: list[IntegrityViolation] = []

    for t in trades:
        if t.agg_trade_id in seen:
            violations.append(
                IntegrityViolation(
                    symbol=symbol,
                    dataset=Dataset.TRADES,
                    violation_type=ViolationType.DUPLICATE_TRADE,
                    detail=f"Duplicate agg_trade_id: {t.agg_trade_id}",
                )
            )
        else:
            seen.add(t.agg_trade_id)

    return violations


def check_trade_validity(
    trades: list[AggTrade],
) -> list[IntegrityViolation]:
    """
    Detect invalid trade records.

    Invalid conditions:
      price <= 0
      quantity <= 0
      timestamp < 2019-01-01 (Binance Futures launched Jan 2019)
      timestamp > now + 1 minute (clock skew guard)
    """
    if not trades:
        return []

    symbol = trades[0].symbol
    earliest_allowed = datetime(2019, 1, 1, tzinfo=timezone.utc)
    latest_allowed   = datetime.now(tz=timezone.utc) + timedelta(minutes=1)
    violations: list[IntegrityViolation] = []

    for t in trades:
        problems: list[str] = []

        if t.price <= 0:
            problems.append(f"price({t.price}) <= 0")
        if t.quantity <= 0:
            problems.append(f"quantity({t.quantity}) <= 0")
        if t.timestamp < earliest_allowed:
            problems.append(
                f"timestamp({t.timestamp.isoformat()}) before Binance Futures launch"
            )
        if t.timestamp > latest_allowed:
            problems.append(
                f"timestamp({t.timestamp.isoformat()}) in the future"
            )

        if problems:
            vtype = (
                ViolationType.INVALID_TRADE_PRICE
                if "price" in problems[0]
                else ViolationType.INVALID_TRADE_QTY
            )
            violations.append(
                IntegrityViolation(
                    symbol=symbol,
                    dataset=Dataset.TRADES,
                    violation_type=vtype,
                    detail=f"agg_trade_id={t.agg_trade_id}: {'; '.join(problems)}",
                )
            )

    return violations


def check_trade_sort_order(
    trades: list[AggTrade],
) -> list[IntegrityViolation]:
    """
    Detect out-of-order trades (timestamp[i] > timestamp[i+1]).

    Uses agg_trade_id as secondary key for exact ties.
    """
    if len(trades) < 2:
        return []

    symbol = trades[0].symbol
    violations: list[IntegrityViolation] = []

    for i in range(len(trades) - 1):
        curr = trades[i]
        nxt  = trades[i + 1]
        if curr.timestamp > nxt.timestamp or (
            curr.timestamp == nxt.timestamp
            and curr.agg_trade_id > nxt.agg_trade_id
        ):
            violations.append(
                IntegrityViolation(
                    symbol=symbol,
                    dataset=Dataset.TRADES,
                    violation_type=ViolationType.OUT_OF_ORDER,
                    detail=(
                        f"Trade at index {i} (id={curr.agg_trade_id}, "
                        f"ts={curr.timestamp.isoformat()}) after "
                        f"index {i+1} (id={nxt.agg_trade_id}, "
                        f"ts={nxt.timestamp.isoformat()})"
                    ),
                )
            )

    return violations


def run_all_trade_checks(
    trades: list[AggTrade],
) -> list[IntegrityViolation]:
    """Run all trade integrity checks and return the combined violation list."""
    if not trades:
        return []
    violations: list[IntegrityViolation] = []
    violations += check_trade_sort_order(trades)
    violations += check_trade_duplicates(trades)
    violations += check_trade_validity(trades)
    return violations
