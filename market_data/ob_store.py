"""
market_data/ob_store.py

Persistence layer for raw Order Book events and reconstructed checkpoints.
"""

from __future__ import annotations

import logging
from datetime import date, timezone
from pathlib import Path

from market_data.config import config as default_config
from market_data.ob_models import OrderBookCheckpoint, OrderBookEvent

logger = logging.getLogger(__name__)


class OrderBookStore:
    """
    Append-only JSONL store for raw Order Book events.
    """

    def __init__(self, data_dir: Path | None = None) -> None:
        self.data_dir = data_dir or Path(default_config.OHLCV_DIR).parent / "order_book" / "raw"

    def _file_path(self, symbol: str, d: date) -> Path:
        return self.data_dir / symbol / f"{d.strftime('%Y%m%d')}.jsonl"

    def save_events(self, events: list[OrderBookEvent]) -> int:
        if not events:
            return 0

        symbol = events[0].symbol
        by_date: dict[date, list[OrderBookEvent]] = {}
        
        for e in events:
            d = e.event_time.astimezone(timezone.utc).date()
            by_date.setdefault(d, []).append(e)

        total_written = 0
        for d, day_events in sorted(by_date.items()):
            filepath = self._file_path(symbol, d)
            filepath.parent.mkdir(parents=True, exist_ok=True)
            
            with filepath.open("a", encoding="utf-8") as fh:
                for e in day_events:
                    fh.write(e.model_dump_json() + "\n")
            total_written += len(day_events)
        return total_written

    def load_events(self, symbol: str, start: datetime, end: datetime) -> list[OrderBookEvent]:
        start_date = start.astimezone(timezone.utc).date()
        end_date = end.astimezone(timezone.utc).date()
        
        events = []
        sym_dir = self.data_dir / symbol
        if not sym_dir.exists():
            return events

        from datetime import datetime as dt_cls
        for filepath in sorted(sym_dir.glob("????????.jsonl")):
            try:
                file_date = dt_cls.strptime(filepath.stem, "%Y%m%d").date()
            except ValueError:
                continue
            if file_date < start_date or file_date > end_date:
                continue
            
            with filepath.open("r", encoding="utf-8") as fh:
                for line in fh:
                    line = line.strip()
                    if not line: continue
                    try:
                        e = OrderBookEvent.model_validate_json(line)
                        if start <= e.event_time <= end:
                            events.append(e)
                    except Exception:
                        pass
                        
        events.sort(key=lambda e: e.final_update_id)
        return events


class OrderBookCheckpointStore:
    """
    Append-only JSONL store for reconstructed Order Book checkpoints.
    """

    def __init__(self, data_dir: Path | None = None) -> None:
        self.data_dir = data_dir or Path(default_config.OHLCV_DIR).parent / "order_book" / "checkpoints"

    def _file_path(self, symbol: str, d: date) -> Path:
        return self.data_dir / symbol / f"{d.strftime('%Y%m%d')}.jsonl"

    def save_checkpoints(self, checkpoints: list[OrderBookCheckpoint]) -> int:
        if not checkpoints:
            return 0

        symbol = checkpoints[0].symbol
        by_date: dict[date, list[OrderBookCheckpoint]] = {}
        
        for c in checkpoints:
            d = c.exchange_event_time.astimezone(timezone.utc).date()
            by_date.setdefault(d, []).append(c)

        total_written = 0
        for d, day_checkpoints in sorted(by_date.items()):
            filepath = self._file_path(symbol, d)
            filepath.parent.mkdir(parents=True, exist_ok=True)
            
            with filepath.open("a", encoding="utf-8") as fh:
                for c in day_checkpoints:
                    fh.write(c.model_dump_json() + "\n")
            total_written += len(day_checkpoints)

        return total_written
