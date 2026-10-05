"""
research_features/store.py

Append-only JSONL persistence for FeatureRows.

Storage layout
--------------
  data/features/{SYMBOL}/{YYYYMMDD}.jsonl

One FeatureRow JSON object per line. The date in the filename is the UTC date
of the feature timestamp.

Deduplication
-------------
Every write checks the existing file for the (symbol, timestamp, feature_version)
key. Rows already on disk are skipped; only genuinely new rows are appended.
"""

from __future__ import annotations

import logging
from datetime import date, datetime, timezone
from pathlib import Path

from market_data.config import MarketDataConfig, config as default_config
from research_features.models import FeatureRow

logger = logging.getLogger(__name__)


class FeatureStore:
    """
    Append-only JSONL store for FeatureRows.
    """

    def __init__(self, cfg: MarketDataConfig = default_config) -> None:
        self.data_dir = Path(cfg.OHLCV_DIR).parent / "features"

    def _symbol_dir(self, symbol: str) -> Path:
        return self.data_dir / symbol

    def _file_path(self, symbol: str, d: date) -> Path:
        return self._symbol_dir(symbol) / f"{d.strftime('%Y%m%d')}.jsonl"

    def save(self, rows: list[FeatureRow]) -> tuple[int, int]:
        """
        Append new FeatureRows to disk, skipping duplicates by (timestamp, feature_version).

        Returns:
            (written, skipped) counts.
        """
        if not rows:
            return 0, 0

        symbol = rows[0].symbol

        # Group by UTC date of timestamp
        by_date: dict[date, list[FeatureRow]] = {}
        for r in rows:
            d = r.timestamp.astimezone(timezone.utc).date()
            by_date.setdefault(d, []).append(r)

        total_written = 0
        total_skipped = 0

        for d, day_rows in sorted(by_date.items()):
            filepath = self._file_path(symbol, d)
            filepath.parent.mkdir(parents=True, exist_ok=True)

            existing_keys = self._load_keys(filepath)

            new_rows = [
                r for r in day_rows 
                if (r.timestamp, r.feature_version) not in existing_keys
            ]
            skipped = len(day_rows) - len(new_rows)
            total_skipped += skipped

            if new_rows:
                new_rows.sort(key=lambda r: (r.timestamp, r.feature_version))
                with filepath.open("a", encoding="utf-8") as fh:
                    for r in new_rows:
                        fh.write(r.model_dump_json() + "\n")
                total_written += len(new_rows)
                logger.debug(
                    "FeatureStore.save: %s %s → +%d features (%d skipped)",
                    symbol, d, len(new_rows), skipped,
                )

        return total_written, total_skipped

    def load(
        self,
        symbol: str,
        start: datetime,
        end: datetime,
    ) -> list[FeatureRow]:
        """
        Load all features for *symbol* with timestamp in [start, end].
        Returns features sorted by timestamp ascending.
        """
        start_utc = start.astimezone(timezone.utc)
        end_utc   = end.astimezone(timezone.utc)
        start_date = start_utc.date()
        end_date   = end_utc.date()

        features: list[FeatureRow] = []
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
            for r in self._read_file(filepath):
                if start_utc <= r.timestamp <= end_utc:
                    features.append(r)

        features.sort(key=lambda r: (r.timestamp, r.feature_version))
        return features

    def _read_file(self, filepath: Path) -> list[FeatureRow]:
        """Read all FeatureRow objects from a single JSONL file."""
        rows: list[FeatureRow] = []
        if not filepath.exists():
            return rows
        with filepath.open("r", encoding="utf-8") as fh:
            for lineno, line in enumerate(fh, start=1):
                line = line.strip()
                if not line:
                    continue
                try:
                    rows.append(FeatureRow.model_validate_json(line))
                except Exception as exc:
                    logger.warning(
                        "FeatureStore: parse error in %s line %d — %s",
                        filepath, lineno, exc,
                    )
        return rows

    def _load_keys(self, filepath: Path) -> set[tuple[datetime, str]]:
        """Return the set of (timestamp, feature_version) already stored in *filepath*."""
        return {(r.timestamp, r.feature_version) for r in self._read_file(filepath)}
