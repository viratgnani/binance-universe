"""
research/result_store.py

ResearchResultStore — append-only JSONL persistence for research outcomes.

Storage layout
--------------
  data/research/{research_id}/{symbol}/{YYYYMMDD}.jsonl

One EventOutcome JSON object per line (UTC date from event_timestamp).

Idempotency
-----------
The logical identity of an outcome row is:
  (research_id, symbol, event_timestamp, event_definition_hash, outcome_name)

Rows already on disk are skipped; only genuinely new rows are appended.
Historical results are never silently overwritten.
"""

from __future__ import annotations

import logging
from datetime import date, datetime, timezone
from pathlib import Path

from research.models import EventOutcome, StatisticsResult

logger = logging.getLogger(__name__)


class ResearchResultStore:
    """
    Append-only JSONL store for EventOutcome objects.
    """

    def __init__(self, base_dir: Path | None = None) -> None:
        self.data_dir = base_dir or Path("data/research")

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def save(
        self,
        research_id: str,
        symbol: str,
        outcomes: list[EventOutcome],
    ) -> tuple[int, int]:
        """
        Persist outcomes to disk, skipping duplicates.

        Returns
        -------
        (written, skipped) counts.
        """
        if not outcomes:
            return 0, 0

        by_date: dict[date, list[EventOutcome]] = {}
        for o in outcomes:
            d = o.event_timestamp.astimezone(timezone.utc).date()
            by_date.setdefault(d, []).append(o)

        total_written = 0
        total_skipped = 0

        for d, day_rows in sorted(by_date.items()):
            filepath = self._file_path(research_id, symbol, d)
            filepath.parent.mkdir(parents=True, exist_ok=True)

            existing_keys = self._load_keys(filepath)

            new_rows = [o for o in day_rows if o.logical_key() not in existing_keys]
            skipped = len(day_rows) - len(new_rows)
            total_skipped += skipped

            if new_rows:
                new_rows.sort(key=lambda o: (o.event_timestamp, o.outcome_name))
                with filepath.open("a", encoding="utf-8") as fh:
                    for o in new_rows:
                        fh.write(o.model_dump_json() + "\n")
                total_written += len(new_rows)
                logger.debug(
                    "ResearchResultStore.save: %s/%s %s → +%d rows (%d skipped)",
                    research_id, symbol, d, len(new_rows), skipped,
                )

        return total_written, total_skipped

    def load(
        self,
        research_id: str,
        symbol: str,
        start: datetime,
        end: datetime,
    ) -> list[EventOutcome]:
        """
        Load all outcomes for *research_id*/*symbol* with event_timestamp in [start, end].
        Returns outcomes sorted by (event_timestamp, outcome_name).
        """
        start_utc = start.astimezone(timezone.utc)
        end_utc   = end.astimezone(timezone.utc)
        start_date = start_utc.date()
        end_date   = end_utc.date()

        sym_dir = self._symbol_dir(research_id, symbol)
        if not sym_dir.exists():
            return []

        outcomes: list[EventOutcome] = []
        for filepath in sorted(sym_dir.glob("????????.jsonl")):
            try:
                file_date = datetime.strptime(filepath.stem, "%Y%m%d").date()
            except ValueError:
                continue
            if file_date < start_date or file_date > end_date:
                continue
            for o in self._read_file(filepath):
                if start_utc <= o.event_timestamp <= end_utc:
                    outcomes.append(o)

        outcomes.sort(key=lambda o: (o.event_timestamp, o.outcome_name))
        return outcomes

    def save_statistics(
        self,
        research_id: str,
        stats: list[StatisticsResult],
    ) -> tuple[int, int]:
        """
        Persist statistics to disk, skipping duplicates.
        File layout: data/research/{research_id}/statistics/statistics.jsonl
        """
        if not stats:
            return 0, 0

        filepath = self.data_dir / research_id / "statistics" / "statistics.jsonl"
        filepath.parent.mkdir(parents=True, exist_ok=True)

        existing_keys = set()
        if filepath.exists():
            with filepath.open("r", encoding="utf-8") as fh:
                for line in fh:
                    if line.strip():
                        try:
                            s = StatisticsResult.model_validate_json(line)
                            existing_keys.add(s.logical_key())
                        except Exception:
                            pass

        new_stats = [s for s in stats if s.logical_key() not in existing_keys]
        skipped = len(stats) - len(new_stats)
        
        if new_stats:
            with filepath.open("a", encoding="utf-8") as fh:
                for s in new_stats:
                    fh.write(s.model_dump_json() + "\n")

        return len(new_stats), skipped

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _symbol_dir(self, research_id: str, symbol: str) -> Path:
        return self.data_dir / research_id / symbol

    def _file_path(self, research_id: str, symbol: str, d: date) -> Path:
        return self._symbol_dir(research_id, symbol) / f"{d.strftime('%Y%m%d')}.jsonl"

    def _read_file(self, filepath: Path) -> list[EventOutcome]:
        rows: list[EventOutcome] = []
        if not filepath.exists():
            return rows
        with filepath.open("r", encoding="utf-8") as fh:
            for lineno, line in enumerate(fh, start=1):
                line = line.strip()
                if not line:
                    continue
                try:
                    rows.append(EventOutcome.model_validate_json(line))
                except Exception as exc:
                    logger.warning(
                        "ResearchResultStore: parse error in %s line %d — %s",
                        filepath, lineno, exc,
                    )
        return rows

    def _load_keys(self, filepath: Path) -> set[tuple]:
        return {o.logical_key() for o in self._read_file(filepath)}
