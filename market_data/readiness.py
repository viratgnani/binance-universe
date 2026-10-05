"""
market_data/readiness.py

Data Readiness Layer — classifies stored OHLCV data for research experiment readiness.

Purpose
-------
Reads from the frozen OHLCVStore and classifies each symbol as READY, INCOMPLETE,
INVALID, or MISSING relative to a defined ExperimentReadinessSpec.

This module is STRICTLY READ-ONLY with respect to the frozen data stores.
It NEVER modifies candles, fills gaps, interpolates prices, or creates synthetic data.

Readiness Classification
------------------------
READY       — Sufficient candles, preferred history, no integrity failures.
INCOMPLETE  — Candles exist, but count < rsi_min_candles OR duration < preferred_days.
INVALID     — Candles exist but have integrity violations (invalid OHLC, negative vol, etc.)
MISSING     — No candles stored at all for this symbol/interval.

RSI Note
--------
RSI(14) requires exactly 15 sequential valid close observations to initialize
(14 changes for the first simple average). A symbol with exactly 15 candles
is technically initializable but NOT research-ready. The preferred_history_days
threshold (default 30 days = 43,200 1-minute candles) governs actual readiness.

Forward Outcome Note
--------------------
For a T+10m outcome, the dataset must contain a candle at exactly T+10 minutes.
This is guaranteed if coverage is continuous. Gaps in the [T, T+10] window
will cause outcome status = INSUFFICIENT_FUTURE_DATA in the research engine.
This readiness layer reports max_gap_minutes to surface that risk.

Universe Safety
---------------
This module does NOT infer universe membership from ranking. It reports the
symbols provided to it and their data status. Universe selection is the
caller's responsibility.
"""

from __future__ import annotations

import logging
import math
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from enum import Enum
from pathlib import Path
from typing import Sequence

from market_data.config import MarketDataConfig, config as default_config
from market_data.integrity import run_all_candle_checks
from market_data.models import IntegrityViolation, ViolationType
from market_data.ohlcv_store import OHLCVStore

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Readiness Specification
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class ExperimentReadinessSpec:
    """
    Immutable specification describing what data the future RSI experiment needs.

    Parameters
    ----------
    interval : str
        Candle interval.  Must be "1m" for the RSI(14) event study.
    rsi_period : int
        RSI lookback period.  Default 14.
    rsi_min_candles : int
        Minimum sequential observations to initialize RSI.
        = rsi_period + 1.  Default 15 (= 14 + 1).
    preferred_history_days : int
        Preferred minimum coverage in calendar days.  Default 30.
        A symbol with less is INCOMPLETE, not READY.
    required_forward_minutes : int
        Maximum forward horizon in the experiment.  Default 10.
        The readiness layer flags symbols whose maximum gap exceeds this.
    exclude_symbols : frozenset[str]
        Symbols explicitly excluded from the experiment.
        These are reported but never classified as READY.
    """
    interval: str = "1m"
    rsi_period: int = 14
    rsi_min_candles: int = 15        # rsi_period + 1
    preferred_history_days: int = 30
    required_forward_minutes: int = 10
    exclude_symbols: frozenset[str] = field(
        default_factory=lambda: frozenset({"BTCUSDT", "ETHUSDT", "SOLUSDT"})
    )

    def __post_init__(self) -> None:
        if self.rsi_min_candles < self.rsi_period + 1:
            raise ValueError(
                f"rsi_min_candles ({self.rsi_min_candles}) must be >= "
                f"rsi_period + 1 ({self.rsi_period + 1})"
            )


# ---------------------------------------------------------------------------
# Readiness Status
# ---------------------------------------------------------------------------

class ReadinessStatus(str, Enum):
    READY      = "READY"
    INCOMPLETE = "INCOMPLETE"
    INVALID    = "INVALID"
    MISSING    = "MISSING"
    EXCLUDED   = "EXCLUDED"


# ---------------------------------------------------------------------------
# Per-symbol result
# ---------------------------------------------------------------------------

@dataclass
class SymbolReadiness:
    """
    Complete readiness report for one symbol.

    All counts and durations reflect the data actually stored on disk.
    No data is filled, interpolated, or synthesized.
    """
    symbol: str
    interval: str
    candle_count: int
    earliest: datetime | None
    latest: datetime | None
    duration_days: float            # (latest - earliest) in calendar days; 0 if < 2 candles
    gaps: int                       # count of gap events (sequences of missing candles)
    missing_candles: int            # total count of missing 1m slots
    max_gap_minutes: int            # longest contiguous gap in minutes (0 = no gaps)
    duplicate_candles: int
    invalid_candles: int            # OHLC validity failures + timestamp alignment failures
    coverage_pct: float             # actual / expected * 100, capped at 100
    has_rsi_init: bool              # candle_count >= spec.rsi_min_candles
    has_preferred_history: bool     # duration_days >= spec.preferred_history_days
    status: ReadinessStatus
    reason: str                     # human-readable explanation for the classification
    violations: list[IntegrityViolation] = field(default_factory=list, repr=False)


# ---------------------------------------------------------------------------
# Aggregate summary
# ---------------------------------------------------------------------------

@dataclass
class ReadinessSummary:
    """Aggregate statistics over all evaluated symbols."""
    spec: ExperimentReadinessSpec
    symbols_evaluated: int
    symbols_ready: int
    symbols_incomplete: int
    symbols_invalid: int
    symbols_missing: int
    symbols_excluded: int
    total_candles: int
    earliest_global: datetime | None
    latest_global: datetime | None
    duration_days_min: float
    duration_days_median: float
    duration_days_max: float
    results: list[SymbolReadiness]
    audit_timestamp: datetime = field(
        default_factory=lambda: datetime.now(timezone.utc)
    )

    @property
    def experiment_ready(self) -> bool:
        """
        True only if at least one non-excluded symbol is READY.
        Does NOT mean the entire requested universe is ready.
        Check symbols_ready vs symbols_evaluated for full picture.
        """
        return self.symbols_ready > 0

    def ready_symbols(self) -> list[str]:
        return [r.symbol for r in self.results if r.status == ReadinessStatus.READY]

    def incomplete_symbols(self) -> list[str]:
        return [r.symbol for r in self.results if r.status == ReadinessStatus.INCOMPLETE]

    def missing_symbols(self) -> list[str]:
        return [r.symbol for r in self.results if r.status == ReadinessStatus.MISSING]

    def invalid_symbols(self) -> list[str]:
        return [r.symbol for r in self.results if r.status == ReadinessStatus.INVALID]


# ---------------------------------------------------------------------------
# Core readiness classifier
# ---------------------------------------------------------------------------

class ReadinessClassifier:
    """
    Reads from OHLCVStore and classifies per-symbol readiness.

    This class is READ-ONLY. It never writes, modifies, or creates candles.
    """

    def __init__(self, cfg: MarketDataConfig = default_config) -> None:
        self._store = OHLCVStore(cfg)
        self._cfg = cfg

    def classify_symbol(
        self,
        symbol: str,
        spec: ExperimentReadinessSpec,
        start: datetime | None = None,
        end: datetime | None = None,
    ) -> SymbolReadiness:
        """
        Classify one symbol's readiness.

        If start/end are provided, only candles in that range are evaluated.
        If not provided, all stored candles for the symbol/interval are evaluated.

        Parameters
        ----------
        symbol : str
        spec : ExperimentReadinessSpec
        start, end : datetime | None
            UTC-aware. If None, the full stored range is used.
        """
        # Fast-path: excluded symbols
        if symbol.upper() in spec.exclude_symbols:
            return SymbolReadiness(
                symbol=symbol,
                interval=spec.interval,
                candle_count=0,
                earliest=None,
                latest=None,
                duration_days=0.0,
                gaps=0,
                missing_candles=0,
                max_gap_minutes=0,
                duplicate_candles=0,
                invalid_candles=0,
                coverage_pct=0.0,
                has_rsi_init=False,
                has_preferred_history=False,
                status=ReadinessStatus.EXCLUDED,
                reason=f"Explicitly excluded from the experiment.",
            )

        # Determine effective window
        start_utc = start.astimezone(timezone.utc) if start else _epoch_start()
        end_utc   = end.astimezone(timezone.utc)   if end   else datetime.now(timezone.utc)

        candles = self._store.load(symbol, spec.interval, start_utc, end_utc)

        if not candles:
            return SymbolReadiness(
                symbol=symbol,
                interval=spec.interval,
                candle_count=0,
                earliest=None,
                latest=None,
                duration_days=0.0,
                gaps=0,
                missing_candles=0,
                max_gap_minutes=0,
                duplicate_candles=0,
                invalid_candles=0,
                coverage_pct=0.0,
                has_rsi_init=False,
                has_preferred_history=False,
                status=ReadinessStatus.MISSING,
                reason="No OHLCV candles stored for this symbol/interval.",
            )

        # Run all integrity checks (pure, no side effects)
        violations = run_all_candle_checks(candles, spec.interval)

        # Aggregate violation counts
        dup_count      = _count_vtype(violations, ViolationType.DUPLICATE_CANDLE)
        invalid_count  = (
            _count_vtype(violations, ViolationType.INVALID_OHLC)
            + _count_vtype(violations, ViolationType.TIMESTAMP_MISALIGN)
        )
        gap_events     = _count_vtype(violations, ViolationType.MISSING_CANDLE)
        missing_total  = _sum_missing_candles(violations)
        max_gap_min    = _compute_max_gap_minutes(violations, spec.interval)

        # Temporal bounds
        earliest = candles[0].open_time
        latest   = candles[-1].open_time
        duration_days = (
            (latest - earliest).total_seconds() / 86400
            if len(candles) >= 2 else 0.0
        )

        # Expected candles in the stored range
        step_ms = self._cfg.INTERVAL_MS.get(spec.interval, 60_000)
        start_ms = int(earliest.timestamp() * 1000)
        end_ms   = int(latest.timestamp()   * 1000)
        expected = max(1, (end_ms - start_ms) // step_ms + 1)
        coverage_pct = min(100.0, len(candles) / expected * 100)

        # Readiness flags
        has_rsi_init    = len(candles) >= spec.rsi_min_candles
        has_preferred   = duration_days >= spec.preferred_history_days

        # Classification (checked in priority order)
        if invalid_count > 0:
            status = ReadinessStatus.INVALID
            reason = (
                f"{invalid_count} invalid OHLC/timestamp candle(s) detected. "
                "Data must be re-acquired or the exchange source investigated."
            )
        elif not has_rsi_init:
            status = ReadinessStatus.INCOMPLETE
            reason = (
                f"Only {len(candles)} candles stored; need >= {spec.rsi_min_candles} "
                f"to initialize RSI({spec.rsi_period})."
            )
        elif not has_preferred:
            status = ReadinessStatus.INCOMPLETE
            reason = (
                f"Coverage is {duration_days:.1f} days; preferred minimum is "
                f"{spec.preferred_history_days} days for a meaningful event study."
            )
        else:
            status = ReadinessStatus.READY
            reason = (
                f"{len(candles):,} candles over {duration_days:.1f} days. "
                f"Coverage {coverage_pct:.1f}%, {gap_events} gap event(s), "
                f"max gap {max_gap_min}m."
            )

        return SymbolReadiness(
            symbol=symbol,
            interval=spec.interval,
            candle_count=len(candles),
            earliest=earliest,
            latest=latest,
            duration_days=round(duration_days, 2),
            gaps=gap_events,
            missing_candles=missing_total,
            max_gap_minutes=max_gap_min,
            duplicate_candles=dup_count,
            invalid_candles=invalid_count,
            coverage_pct=round(coverage_pct, 2),
            has_rsi_init=has_rsi_init,
            has_preferred_history=has_preferred,
            status=status,
            reason=reason,
            violations=violations,
        )

    def classify_all(
        self,
        symbols: Sequence[str],
        spec: ExperimentReadinessSpec,
        start: datetime | None = None,
        end: datetime | None = None,
    ) -> ReadinessSummary:
        """
        Classify readiness for a list of symbols and return an aggregate summary.
        """
        results: list[SymbolReadiness] = []
        for sym in symbols:
            r = self.classify_symbol(sym, spec, start, end)
            results.append(r)
            logger.debug("readiness: %s -> %s: %s", sym, r.status.value, r.reason)

        # Aggregate counts
        ready_cnt      = sum(1 for r in results if r.status == ReadinessStatus.READY)
        incomplete_cnt = sum(1 for r in results if r.status == ReadinessStatus.INCOMPLETE)
        invalid_cnt    = sum(1 for r in results if r.status == ReadinessStatus.INVALID)
        missing_cnt    = sum(1 for r in results if r.status == ReadinessStatus.MISSING)
        excluded_cnt   = sum(1 for r in results if r.status == ReadinessStatus.EXCLUDED)

        total_candles = sum(r.candle_count for r in results)

        # Global temporal bounds (non-missing only)
        dated = [r for r in results if r.earliest is not None]
        earliest_global = min(r.earliest for r in dated) if dated else None
        latest_global   = max(r.latest   for r in dated) if dated else None

        # Duration statistics (non-excluded, non-missing)
        durations = sorted(r.duration_days for r in results if r.earliest is not None)
        if durations:
            dur_min    = durations[0]
            dur_max    = durations[-1]
            dur_median = _median(durations)
        else:
            dur_min = dur_max = dur_median = 0.0

        return ReadinessSummary(
            spec=spec,
            symbols_evaluated=len(results),
            symbols_ready=ready_cnt,
            symbols_incomplete=incomplete_cnt,
            symbols_invalid=invalid_cnt,
            symbols_missing=missing_cnt,
            symbols_excluded=excluded_cnt,
            total_candles=total_candles,
            earliest_global=earliest_global,
            latest_global=latest_global,
            duration_days_min=round(dur_min, 2),
            duration_days_median=round(dur_median, 2),
            duration_days_max=round(dur_max, 2),
            results=results,
        )


# ---------------------------------------------------------------------------
# Universe snapshot helpers
# ---------------------------------------------------------------------------

def load_universe_snapshot_status() -> dict:
    """
    Inspect universe snapshot files and return a status dict.
    Never raises — missing snapshot is a documented limitation, not an error.

    Returns
    -------
    dict with keys:
        snapshot_found: bool
        snapshot_file: str | None
        snapshot_timestamp: str | None
        total_records: int
        active_top_100_count: int
        watchlist_count: int
        ineligible_count: int
        ranked_count: int            # records with rank != None
        historical_ranked_available: bool
        limitation: str | None       # human-readable limitation if any
    """
    try:
        snap_dir = Path("data/snapshots")
        if not snap_dir.exists():
            return _no_snapshot("data/snapshots directory does not exist.")

        files = sorted(snap_dir.glob("snapshot_*.jsonl"))
        if not files:
            return _no_snapshot("No snapshot files found in data/snapshots/.")

        import json
        latest_file = files[-1]
        records = []
        with latest_file.open(encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if line:
                    records.append(json.loads(line))

        data_records = [r for r in records if r.get("record_type") == "DATA"]
        header       = next((r for r in records if r.get("record_type") == "HEADER"), {})

        active_top_100 = [r for r in data_records if r.get("universe_status") == "ACTIVE_TOP_100"]
        watchlist      = [r for r in data_records if r.get("universe_status") == "WATCHLIST"]
        ineligible     = [r for r in data_records if r.get("universe_status") == "INELIGIBLE"]
        ranked         = [r for r in data_records if r.get("rank") is not None]

        limitation = None
        if not ranked:
            limitation = (
                "All symbol ranks are None in the available snapshot. "
                "The snapshot was fetched but the ranking step did not complete. "
                "Historical Top-100 membership cannot be confirmed. "
                "The experiment must use the full eligible USDT perpetual universe instead."
            )

        return {
            "snapshot_found": True,
            "snapshot_file": latest_file.name,
            "snapshot_timestamp": header.get("snapshot_timestamp"),
            "total_records": len(data_records),
            "active_top_100_count": len(active_top_100),
            "watchlist_count": len(watchlist),
            "ineligible_count": len(ineligible),
            "ranked_count": len(ranked),
            "historical_ranked_available": len(ranked) > 0,
            "limitation": limitation,
        }

    except Exception as exc:
        return _no_snapshot(f"Error reading snapshot: {exc}")


def load_eligible_alt_symbols(exclude: frozenset[str] | None = None) -> list[str]:
    """
    Return the list of eligible USDT perpetual alt symbols from the latest
    universe snapshot, excluding the explicitly excluded set.

    Eligibility: universe_status in ("ACTIVE_TOP_100", "WATCHLIST") AND
                 symbol ends with "USDT" AND
                 not in exclude set.

    Returns an empty list if no snapshot is available.
    Does NOT use ranking — only eligibility status.
    """
    if exclude is None:
        exclude = frozenset()

    try:
        snap_dir = Path("data/snapshots")
        files = sorted(snap_dir.glob("snapshot_*.jsonl"))
        if not files:
            return []

        import json
        eligible_symbols = []
        with files[-1].open(encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                r = json.loads(line)
                if r.get("record_type") != "DATA":
                    continue
                sym    = r.get("symbol", "")
                status = r.get("universe_status", "")
                if (
                    sym.endswith("USDT")
                    and sym.isascii()                             # exclude non-ASCII names
                    and sym.replace("USDT", "").isalnum()        # ticker portion must be alphanumeric
                    and status in ("ACTIVE_TOP_100", "WATCHLIST")
                    and sym.upper() not in exclude
                ):
                    eligible_symbols.append(sym)

        return sorted(set(eligible_symbols))

    except Exception as exc:
        logger.warning("Could not load eligible symbols: %s", exc)
        return []


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _epoch_start() -> datetime:
    return datetime(2000, 1, 1, tzinfo=timezone.utc)


def _count_vtype(violations: list[IntegrityViolation], vtype: ViolationType) -> int:
    return sum(1 for v in violations if v.violation_type == vtype)


def _sum_missing_candles(violations: list[IntegrityViolation]) -> int:
    """Parse 'N missing candle(s)...' from MISSING_CANDLE violation details."""
    total = 0
    for v in violations:
        if v.violation_type == ViolationType.MISSING_CANDLE:
            try:
                total += int(v.detail.split()[0])
            except (IndexError, ValueError):
                total += 1
    return total


def _compute_max_gap_minutes(
    violations: list[IntegrityViolation], interval: str
) -> int:
    """
    Find the largest contiguous gap (in minutes) from MISSING_CANDLE violations.
    The detail format is: 'N missing candle(s) starting at TIMESTAMP'.
    For 1m interval, 1 missing candle = 1 minute gap.
    """
    interval_minutes = {
        "1m": 1, "5m": 5, "15m": 15, "1h": 60, "4h": 240, "1d": 1440
    }
    step = interval_minutes.get(interval, 1)
    max_gap = 0
    for v in violations:
        if v.violation_type == ViolationType.MISSING_CANDLE:
            try:
                n = int(v.detail.split()[0])
                gap_min = n * step
                max_gap = max(max_gap, gap_min)
            except (IndexError, ValueError):
                pass
    return max_gap


def _median(values: list[float]) -> float:
    if not values:
        return 0.0
    s = sorted(values)
    n = len(s)
    mid = n // 2
    if n % 2 == 1:
        return s[mid]
    return (s[mid - 1] + s[mid]) / 2.0


def _no_snapshot(reason: str) -> dict:
    return {
        "snapshot_found": False,
        "snapshot_file": None,
        "snapshot_timestamp": None,
        "total_records": 0,
        "active_top_100_count": 0,
        "watchlist_count": 0,
        "ineligible_count": 0,
        "ranked_count": 0,
        "historical_ranked_available": False,
        "limitation": reason,
    }
