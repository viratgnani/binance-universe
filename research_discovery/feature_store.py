"""
research_discovery/feature_store.py

Append-only JSONL persistence for DiscoveryFeatureRow objects.

Storage layout:
  data/discovery_features/{symbol}/{YYYYMMDD}.jsonl

Idempotency is based on (symbol, timestamp, feature_version).
"""

from __future__ import annotations

import logging
from datetime import date, datetime, timezone
from pathlib import Path

from market_data.config import MarketDataConfig, config as default_config
from research_discovery.models import DiscoveryFeatureRow

logger = logging.getLogger(__name__)


class DiscoveryFeatureStore:
    """
    Append-only JSONL store for discovery features.
    Sits completely independently of the frozen FeatureStore.
    """

    def __init__(self, cfg: MarketDataConfig = default_config) -> None:
        # e.g. "data/discovery_features" alongside "data/ohlcv"
        self.data_dir = Path(cfg.OHLCV_DIR).parent / "discovery_features"

    def _symbol_dir(self, symbol: str) -> Path:
        return self.data_dir / symbol

    def _file_path(self, symbol: str, d: date) -> Path:
        return self._symbol_dir(symbol) / f"{d.strftime('%Y%m%d')}.jsonl"

    def save(self, rows: list[DiscoveryFeatureRow]) -> tuple[int, int]:
        """
        Persist rows to disk, skipping duplicates based on logical key.
        Returns (written, skipped) counts.
        """
        if not rows:
            return 0, 0

        symbol = rows[0].symbol

        by_date: dict[date, list[DiscoveryFeatureRow]] = {}
        for r in rows:
            d = r.timestamp.astimezone(timezone.utc).date()
            by_date.setdefault(d, []).append(r)

        total_written = 0
        total_skipped = 0

        for d, day_rows in sorted(by_date.items()):
            filepath = self._file_path(symbol, d)
            filepath.parent.mkdir(parents=True, exist_ok=True)

            existing_keys = self._load_keys(filepath)

            def get_key(row: DiscoveryFeatureRow) -> tuple:
                return (row.symbol, row.timestamp, row.feature_version)

            new_rows = [r for r in day_rows if get_key(r) not in existing_keys]
            skipped = len(day_rows) - len(new_rows)
            total_skipped += skipped

            if new_rows:
                # Sort exactly by chronological ordering to maintain clean appending
                new_rows.sort(key=lambda r: r.timestamp)
                with filepath.open("a", encoding="utf-8") as fh:
                    for r in new_rows:
                        fh.write(r.model_dump_json(exclude_none=True) + "\n")
                total_written += len(new_rows)
                logger.debug(
                    "DiscoveryFeatureStore.save: %s %s → +%d rows (%d skipped)",
                    symbol, d, len(new_rows), skipped,
                )

        return total_written, total_skipped

    def load(
        self,
        symbol: str,
        start: datetime,
        end: datetime,
    ) -> list[DiscoveryFeatureRow]:
        """
        Load all feature rows for *symbol* with timestamp in [start, end].
        Returns objects sorted ascending by timestamp.
        """
        start_utc = start.astimezone(timezone.utc)
        end_utc   = end.astimezone(timezone.utc)
        start_date = start_utc.date()
        end_date   = end_utc.date()

        sym_dir = self._symbol_dir(symbol)
        if not sym_dir.exists():
            return []

        results: list[DiscoveryFeatureRow] = []
        for filepath in sorted(sym_dir.glob("????????.jsonl")):
            try:
                file_date = datetime.strptime(filepath.stem, "%Y%m%d").date()
            except ValueError:
                continue
            if file_date < start_date or file_date > end_date:
                continue
            for r in self._read_file(filepath):
                if start_utc <= r.timestamp <= end_utc:
                    results.append(r)

        results.sort(key=lambda r: r.timestamp)
        return results

    def _read_file(self, filepath: Path) -> list[DiscoveryFeatureRow]:
        rows: list[DiscoveryFeatureRow] = []
        if not filepath.exists():
            return rows
        with filepath.open("r", encoding="utf-8") as fh:
            for lineno, line in enumerate(fh, start=1):
                line = line.strip()
                if not line:
                    continue
                try:
                    rows.append(DiscoveryFeatureRow.model_validate_json(line))
                except Exception as exc:
                    logger.warning(
                        "DiscoveryFeatureStore: parse error in %s line %d — %s",
                        filepath, lineno, exc,
                    )
        return rows

    def _load_keys(self, filepath: Path) -> set[tuple]:
        return {(r.symbol, r.timestamp, r.feature_version) for r in self._read_file(filepath)}
