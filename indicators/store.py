"""
indicators/store.py

Append-only JSONL persistence for IndicatorValue objects.

Storage layout
--------------
  data/indicators/{symbol}/{YYYYMMDD}.jsonl

Idempotency
-----------
Rows are logically identified by:
  (symbol, timestamp, indicator_name, indicator_version, parameter_hash)
"""

from __future__ import annotations

import logging
from datetime import date, datetime, timezone
from pathlib import Path

from market_data.config import MarketDataConfig, config as default_config
from indicators.models import IndicatorValue

logger = logging.getLogger(__name__)


class IndicatorStore:
    """
    Append-only JSONL store for IndicatorValue objects.
    """

    def __init__(self, cfg: MarketDataConfig = default_config) -> None:
        # e.g. "data/indicators" alongside "data/ohlcv"
        self.data_dir = Path(cfg.OHLCV_DIR).parent / "indicators"

    def _symbol_dir(self, symbol: str) -> Path:
        return self.data_dir / symbol

    def _file_path(self, symbol: str, d: date) -> Path:
        return self._symbol_dir(symbol) / f"{d.strftime('%Y%m%d')}.jsonl"

    def save(self, values: list[IndicatorValue]) -> tuple[int, int]:
        """
        Persist values to disk, skipping duplicates based on the logical key.

        Returns
        -------
        (written, skipped) counts.
        """
        if not values:
            return 0, 0

        symbol = values[0].symbol

        by_date: dict[date, list[IndicatorValue]] = {}
        for v in values:
            d = v.timestamp.astimezone(timezone.utc).date()
            by_date.setdefault(d, []).append(v)

        total_written = 0
        total_skipped = 0

        for d, day_rows in sorted(by_date.items()):
            filepath = self._file_path(symbol, d)
            filepath.parent.mkdir(parents=True, exist_ok=True)

            existing_keys = self._load_keys(filepath)

            new_rows = [v for v in day_rows if v.logical_key() not in existing_keys]
            skipped = len(day_rows) - len(new_rows)
            total_skipped += skipped

            if new_rows:
                # Sort exactly by chronological ordering to maintain clean appending
                new_rows.sort(key=lambda v: (v.timestamp, v.indicator_name, v.parameter_hash))
                with filepath.open("a", encoding="utf-8") as fh:
                    for v in new_rows:
                        fh.write(v.model_dump_json() + "\n")
                total_written += len(new_rows)
                logger.debug(
                    "IndicatorStore.save: %s %s → +%d rows (%d skipped)",
                    symbol, d, len(new_rows), skipped,
                )

        return total_written, total_skipped

    def load(
        self,
        symbol: str,
        start: datetime,
        end: datetime,
    ) -> list[IndicatorValue]:
        """
        Load all indicator values for *symbol* with timestamp in [start, end].
        Returns objects sorted ascending by timestamp.
        """
        start_utc = start.astimezone(timezone.utc)
        end_utc   = end.astimezone(timezone.utc)
        start_date = start_utc.date()
        end_date   = end_utc.date()

        sym_dir = self._symbol_dir(symbol)
        if not sym_dir.exists():
            return []

        results: list[IndicatorValue] = []
        for filepath in sorted(sym_dir.glob("????????.jsonl")):
            try:
                file_date = datetime.strptime(filepath.stem, "%Y%m%d").date()
            except ValueError:
                continue
            if file_date < start_date or file_date > end_date:
                continue
            for v in self._read_file(filepath):
                if start_utc <= v.timestamp <= end_utc:
                    results.append(v)

        results.sort(key=lambda v: (v.timestamp, v.indicator_name, v.parameter_hash))
        return results

    def _read_file(self, filepath: Path) -> list[IndicatorValue]:
        rows: list[IndicatorValue] = []
        if not filepath.exists():
            return rows
        with filepath.open("r", encoding="utf-8") as fh:
            for lineno, line in enumerate(fh, start=1):
                line = line.strip()
                if not line:
                    continue
                try:
                    rows.append(IndicatorValue.model_validate_json(line))
                except Exception as exc:
                    logger.warning(
                        "IndicatorStore: parse error in %s line %d — %s",
                        filepath, lineno, exc,
                    )
        return rows

    def _load_keys(self, filepath: Path) -> set[tuple]:
        return {v.logical_key() for v in self._read_file(filepath)}
