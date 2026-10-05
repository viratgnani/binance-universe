"""
market_data/trades_store.py

Append-only JSONL persistence for aggregate trade data.

Storage layout
--------------
  data/trades/{SYMBOL}/{YYYYMMDD}.jsonl

One AggTrade JSON object per line.  The date in the filename is the UTC date
of the trade's timestamp field (exchange event time, not collection_time).

Deduplication
-------------
Every write checks the existing file for the agg_trade_id key.
Already-stored trades are skipped; only new records are appended.
Saves are idempotent — safe to rerun a collection for an overlapping range.

Reads
-----
load() returns all trades in the requested range sorted by timestamp + agg_trade_id.

get_latest_id() returns the highest stored agg_trade_id — used for pagination
continuation when backfilling by fromId.
"""

from __future__ import annotations

import json
import logging
from datetime import date, datetime, timezone
from pathlib import Path

from market_data.config import MarketDataConfig, config as default_config
from market_data.models import AggTrade

logger = logging.getLogger(__name__)


class TradesStore:
    """
    Append-only JSONL store for aggregate trades.

    Parameters
    ----------
    cfg:
        Configuration providing TRADES_DIR.
    """

    def __init__(self, cfg: MarketDataConfig = default_config) -> None:
        self._cfg = cfg

    # ------------------------------------------------------------------ #
    #  Paths
    # ------------------------------------------------------------------ #

    def _symbol_dir(self, symbol: str) -> Path:
        return Path(self._cfg.TRADES_DIR) / symbol

    def _file_path(self, symbol: str, d: date) -> Path:
        return self._symbol_dir(symbol) / f"{d.strftime('%Y%m%d')}.jsonl"

    # ------------------------------------------------------------------ #
    #  Write
    # ------------------------------------------------------------------ #

    def save(self, trades: list[AggTrade]) -> tuple[int, int]:
        """
        Append new trades to disk, skipping duplicates by agg_trade_id.

        Parameters
        ----------
        trades:
            List of AggTrade objects (may span multiple dates).

        Returns
        -------
        (written, skipped) counts.
        """
        if not trades:
            return 0, 0

        symbol = trades[0].symbol

        # Group by UTC date of trade timestamp
        by_date: dict[date, list[AggTrade]] = {}
        for t in trades:
            d = t.timestamp.astimezone(timezone.utc).date()
            by_date.setdefault(d, []).append(t)

        total_written = 0
        total_skipped = 0

        for d, day_trades in sorted(by_date.items()):
            filepath = self._file_path(symbol, d)
            filepath.parent.mkdir(parents=True, exist_ok=True)

            existing_ids = self._load_ids(filepath)

            new_trades = [t for t in day_trades if t.agg_trade_id not in existing_ids]
            skipped = len(day_trades) - len(new_trades)
            total_skipped += skipped

            if new_trades:
                new_trades.sort(key=lambda t: (t.timestamp, t.agg_trade_id))
                with filepath.open("a", encoding="utf-8") as fh:
                    for t in new_trades:
                        fh.write(t.model_dump_json() + "\n")
                total_written += len(new_trades)
                logger.debug(
                    "TradesStore.save: %s %s → +%d trades (%d skipped)",
                    symbol, d, len(new_trades), skipped,
                )

        return total_written, total_skipped

    # ------------------------------------------------------------------ #
    #  Read
    # ------------------------------------------------------------------ #

    def load(
        self,
        symbol: str,
        start: datetime,
        end: datetime,
    ) -> list[AggTrade]:
        """
        Load all trades for *symbol* with timestamp in [start, end].

        Returns trades sorted by (timestamp, agg_trade_id) ascending.
        """
        start_utc = start.astimezone(timezone.utc)
        end_utc   = end.astimezone(timezone.utc)
        start_date = start_utc.date()
        end_date   = end_utc.date()

        trades: list[AggTrade] = []
        sym_dir = self._symbol_dir(symbol)

        if not sym_dir.exists():
            return []

        for filepath in sorted(sym_dir.glob("????????.jsonl")):
            try:
                file_date = datetime.strptime(filepath.stem, "%Y%m%d").date()
            except ValueError:
                continue
            if file_date < start_date or file_date > end_date:
                continue
            for t in self._read_file(filepath):
                if start_utc <= t.timestamp <= end_utc:
                    trades.append(t)

        trades.sort(key=lambda t: (t.timestamp, t.agg_trade_id))
        return trades

    def get_latest_id(self, symbol: str) -> int | None:
        """
        Return the highest agg_trade_id stored for *symbol*.

        Used as the fromId cursor for pagination continuation.
        Returns None if no trades are stored.
        """
        sym_dir = self._symbol_dir(symbol)
        if not sym_dir.exists():
            return None

        max_id: int | None = None
        for filepath in sorted(sym_dir.glob("????????.jsonl"), reverse=True):
            trades = self._read_file(filepath)
            if trades:
                file_max = max(t.agg_trade_id for t in trades)
                if max_id is None or file_max > max_id:
                    max_id = file_max
                # Since files are date-ordered descending, the first non-empty file
                # is likely to have the latest trade; but scan all to be safe.
        return max_id

    def get_latest_trade(self, symbol: str) -> AggTrade | None:
        """Return the most recent trade stored for *symbol*, or None."""
        sym_dir = self._symbol_dir(symbol)
        if not sym_dir.exists():
            return None

        for filepath in sorted(sym_dir.glob("????????.jsonl"), reverse=True):
            trades = self._read_file(filepath)
            if trades:
                return max(trades, key=lambda t: (t.timestamp, t.agg_trade_id))
        return None

    def count_stored(
        self,
        symbol: str,
        start: datetime,
        end: datetime,
    ) -> int:
        """Return count of trades stored in [start, end]."""
        return len(self.load(symbol, start, end))

    def list_symbols(self) -> list[str]:
        """Return all symbols with stored trade data."""
        base = Path(self._cfg.TRADES_DIR)
        if not base.exists():
            return []
        return [p.name for p in sorted(base.iterdir()) if p.is_dir()]

    # ------------------------------------------------------------------ #
    #  Internal helpers
    # ------------------------------------------------------------------ #

    def _read_file(self, filepath: Path) -> list[AggTrade]:
        """Read all AggTrade objects from a single JSONL file."""
        trades: list[AggTrade] = []
        if not filepath.exists():
            return trades
        with filepath.open("r", encoding="utf-8") as fh:
            for lineno, line in enumerate(fh, start=1):
                line = line.strip()
                if not line:
                    continue
                try:
                    trades.append(AggTrade.model_validate_json(line))
                except Exception as exc:
                    logger.warning(
                        "TradesStore: parse error in %s line %d — %s",
                        filepath, lineno, exc,
                    )
        return trades

    def _load_ids(self, filepath: Path) -> set[int]:
        """Return the set of agg_trade_ids already stored in *filepath*."""
        return {t.agg_trade_id for t in self._read_file(filepath)}
