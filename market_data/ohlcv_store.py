"""
market_data/ohlcv_store.py

Append-only JSONL persistence for OHLCV candlestick data.

Storage layout
--------------
  data/ohlcv/{SYMBOL}/{interval}/{YYYYMMDD}.jsonl

One Candle JSON object per line.  The date in the filename is the UTC date
of the candle's open_time (not collection_time).

Deduplication
-------------
Every write checks the existing file for the (symbol, interval, open_time)
key.  Candles already on disk are skipped; only genuinely new candles are
appended.  This makes saves idempotent — rerunning a backfill for the same
range is safe.

Reads
-----
load() scans one or more date files and returns all candles in the
requested range, sorted by open_time ascending.

get_latest() returns the most recent stored candle — used by the
incremental updater to find the gap between stored data and now.
"""

from __future__ import annotations

import json
import logging
from datetime import date, datetime, timezone
from pathlib import Path

from market_data.config import MarketDataConfig, config as default_config
from market_data.models import Candle

logger = logging.getLogger(__name__)


class OHLCVStore:
    """
    Append-only JSONL store for OHLCV candles.

    Parameters
    ----------
    cfg:
        Configuration providing OHLCV_DIR.
    """

    def __init__(self, cfg: MarketDataConfig = default_config) -> None:
        self._cfg = cfg

    # ------------------------------------------------------------------ #
    #  Paths
    # ------------------------------------------------------------------ #

    def _symbol_dir(self, symbol: str, interval: str) -> Path:
        return Path(self._cfg.OHLCV_DIR) / symbol / interval

    def _file_path(self, symbol: str, interval: str, d: date) -> Path:
        return self._symbol_dir(symbol, interval) / f"{d.strftime('%Y%m%d')}.jsonl"

    # ------------------------------------------------------------------ #
    #  Write
    # ------------------------------------------------------------------ #

    def save(self, candles: list[Candle]) -> tuple[int, int]:
        """
        Append new candles to disk, skipping duplicates.

        Candles from multiple date-files are handled transparently —
        each candle is written to the file matching its UTC open_time date.

        Parameters
        ----------
        candles:
            List of Candle objects (may span multiple dates).

        Returns
        -------
        (written, skipped) counts.
        """
        if not candles:
            return 0, 0

        symbol   = candles[0].symbol
        interval = candles[0].interval

        # Group by UTC date of open_time
        by_date: dict[date, list[Candle]] = {}
        for c in candles:
            d = c.open_time.astimezone(timezone.utc).date()
            by_date.setdefault(d, []).append(c)

        total_written  = 0
        total_skipped  = 0

        for d, day_candles in sorted(by_date.items()):
            filepath = self._file_path(symbol, interval, d)
            filepath.parent.mkdir(parents=True, exist_ok=True)

            # Load existing open_times for this file to skip duplicates
            existing_times = self._load_open_times(filepath)

            new_candles = [
                c for c in day_candles if c.open_time not in existing_times
            ]
            skipped = len(day_candles) - len(new_candles)
            total_skipped += skipped

            if new_candles:
                # Sort before appending so the file stays ordered
                new_candles.sort(key=lambda c: c.open_time)
                with filepath.open("a", encoding="utf-8") as fh:
                    for c in new_candles:
                        fh.write(c.model_dump_json() + "\n")
                total_written += len(new_candles)
                logger.debug(
                    "OHLCVStore.save: %s %s %s → +%d candles (%d skipped)",
                    symbol, interval, d, len(new_candles), skipped,
                )

        return total_written, total_skipped

    # ------------------------------------------------------------------ #
    #  Read
    # ------------------------------------------------------------------ #

    def load(
        self,
        symbol: str,
        interval: str,
        start: datetime,
        end: datetime,
    ) -> list[Candle]:
        """
        Load all candles for *symbol*/*interval* with open_time in [start, end].

        Scans all date files whose date overlaps [start.date(), end.date()].
        Returns candles sorted by open_time ascending.

        Parameters
        ----------
        symbol, interval:
            Target series.
        start, end:
            UTC-aware datetime range (inclusive on both ends).
        """
        start_utc = start.astimezone(timezone.utc)
        end_utc   = end.astimezone(timezone.utc)

        # Date range to scan (be inclusive: one day before to handle timezone edge)
        start_date = start_utc.date()
        end_date   = end_utc.date()

        candles: list[Candle] = []
        sym_dir = self._symbol_dir(symbol, interval)

        if not sym_dir.exists():
            return []

        for filepath in sorted(sym_dir.glob("????????.jsonl")):
            # Extract date from filename
            try:
                file_date = datetime.strptime(filepath.stem, "%Y%m%d").date()
            except ValueError:
                continue
            if file_date < start_date or file_date > end_date:
                continue
            for c in self._read_file(filepath):
                if start_utc <= c.open_time <= end_utc:
                    candles.append(c)

        candles.sort(key=lambda c: c.open_time)
        return candles

    def get_latest(self, symbol: str, interval: str) -> Candle | None:
        """
        Return the most recent candle stored for (symbol, interval).

        Returns None if no data exists.
        """
        sym_dir = self._symbol_dir(symbol, interval)
        if not sym_dir.exists():
            return None

        files = sorted(sym_dir.glob("????????.jsonl"), reverse=True)
        for filepath in files:
            candles = self._read_file(filepath)
            if candles:
                return max(candles, key=lambda c: c.open_time)
        return None

    def count_stored(
        self,
        symbol: str,
        interval: str,
        start: datetime,
        end: datetime,
    ) -> int:
        """Return the count of candles stored in [start, end]."""
        return len(self.load(symbol, interval, start, end))

    def list_symbols(self) -> list[str]:
        """Return all symbols that have at least one OHLCV file."""
        base = Path(self._cfg.OHLCV_DIR)
        if not base.exists():
            return []
        return [p.name for p in sorted(base.iterdir()) if p.is_dir()]

    # ------------------------------------------------------------------ #
    #  Internal helpers
    # ------------------------------------------------------------------ #

    def _read_file(self, filepath: Path) -> list[Candle]:
        """Read all Candle objects from a single JSONL file."""
        candles: list[Candle] = []
        if not filepath.exists():
            return candles
        with filepath.open("r", encoding="utf-8") as fh:
            for lineno, line in enumerate(fh, start=1):
                line = line.strip()
                if not line:
                    continue
                try:
                    candles.append(Candle.model_validate_json(line))
                except Exception as exc:
                    logger.warning(
                        "OHLCVStore: parse error in %s line %d — %s",
                        filepath, lineno, exc,
                    )
        return candles

    def _load_open_times(self, filepath: Path) -> set[datetime]:
        """Return the set of open_times already stored in *filepath*."""
        return {c.open_time for c in self._read_file(filepath)}
