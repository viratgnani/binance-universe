"""
universe/snapshot_repository.py

Append-only JSONL snapshot persistence for the master universe.

Storage format
--------------
One file per calendar day (UTC): snapshot_YYYYMMDD.jsonl

Each refresh appends:
  1. One HEADER line (SnapshotHeader) with aggregate stats.
  2. One DATA line per universe member (SnapshotRecord).

Files are never overwritten — each call to save() appends to the day's file,
so multiple refreshes per day accumulate cleanly.

Querying
--------
All reads scan the JSONL file(s).  For V1 volumes the files are small enough
that full scans are acceptable.  Future modules can build indexed views on top
of this append-only log without modifying this module.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path

from universe.config import UniverseConfig, config as default_config
from universe.models import SnapshotHeader, SnapshotRecord

logger = logging.getLogger(__name__)


class SnapshotRepository:
    """
    Append-only JSONL snapshot store.

    All timestamps are UTC.

    Parameters
    ----------
    cfg:
        Configuration providing SNAPSHOT_DIR.
    """

    def __init__(self, cfg: UniverseConfig = default_config) -> None:
        self._cfg = cfg

    # ------------------------------------------------------------------ #
    #  Write
    # ------------------------------------------------------------------ #

    def save(
        self,
        snapshot_id: str,
        snapshot_timestamp: datetime,
        records: list[SnapshotRecord],
        header: SnapshotHeader,
    ) -> Path:
        """
        Append a complete refresh snapshot to today's JSONL file.

        Parameters
        ----------
        snapshot_id:
            ISO-format string identifying the refresh run.
        snapshot_timestamp:
            UTC datetime of the refresh.
        records:
            One :class:`SnapshotRecord` per universe member.
        header:
            Aggregate stats for this refresh run.

        Returns
        -------
        Path to the file that was written to.
        """
        snapshot_dir = Path(self._cfg.SNAPSHOT_DIR)
        snapshot_dir.mkdir(parents=True, exist_ok=True)

        date_str = snapshot_timestamp.strftime("%Y%m%d")
        filepath = snapshot_dir / f"snapshot_{date_str}.jsonl"

        lines: list[str] = []

        # Header line
        header_dict = header.model_dump(mode="json")
        header_dict["record_type"] = "HEADER"
        lines.append(json.dumps(header_dict, default=str))

        # Data lines
        for record in records:
            data_dict = record.model_dump(mode="json")
            data_dict["record_type"] = "DATA"
            lines.append(json.dumps(data_dict, default=str))

        # Append to file (never overwrite)
        with filepath.open("a", encoding="utf-8") as fh:
            for line in lines:
                fh.write(line + "\n")

        logger.info(
            "Snapshot saved → %s  (%d records, id=%s)",
            filepath,
            len(records),
            snapshot_id,
        )
        return filepath

    # ------------------------------------------------------------------ #
    #  Read helpers
    # ------------------------------------------------------------------ #

    def list_snapshot_files(self) -> list[Path]:
        """Return all snapshot JSONL files sorted oldest-first."""
        snapshot_dir = Path(self._cfg.SNAPSHOT_DIR)
        if not snapshot_dir.exists():
            return []
        files = sorted(snapshot_dir.glob("snapshot_*.jsonl"))
        return files

    def load_records(self, filepath: Path) -> list[dict]:
        """
        Read all JSON lines from *filepath*, skipping malformed lines.

        Returns raw dicts so callers can decide which record_type they need.
        """
        records: list[dict] = []
        with filepath.open("r", encoding="utf-8") as fh:
            for lineno, line in enumerate(fh, start=1):
                line = line.strip()
                if not line:
                    continue
                try:
                    records.append(json.loads(line))
                except json.JSONDecodeError as exc:
                    logger.warning(
                        "%s line %d: JSON decode error — %s", filepath, lineno, exc
                    )
        return records

    def get_snapshots_for_symbol(self, symbol: str) -> list[dict]:
        """
        Return all DATA records for *symbol* across all snapshot files,
        sorted by snapshot_timestamp ascending.

        Useful for inspecting rank history of a single contract.
        """
        matching: list[dict] = []
        for filepath in self.list_snapshot_files():
            for record in self.load_records(filepath):
                if record.get("record_type") == "DATA" and record.get("symbol") == symbol:
                    matching.append(record)

        matching.sort(key=lambda r: r.get("snapshot_timestamp", ""))
        return matching

    def get_snapshot_at(self, timestamp: datetime) -> list[dict]:
        """
        Return the DATA records from the refresh run closest to *timestamp*.

        Scans all files for the HEADER whose snapshot_timestamp is nearest
        to *timestamp*, then returns all DATA records sharing that snapshot_id.
        """
        all_files = self.list_snapshot_files()
        if not all_files:
            return []

        # Collect all headers across all files
        headers_with_path: list[tuple[datetime, str, Path]] = []
        for filepath in all_files:
            for record in self.load_records(filepath):
                if record.get("record_type") == "HEADER":
                    try:
                        ts = datetime.fromisoformat(record["snapshot_timestamp"])
                        headers_with_path.append((ts, record["snapshot_id"], filepath))
                    except (KeyError, ValueError):
                        pass

        if not headers_with_path:
            return []

        # Find closest header by time delta
        target = timestamp.replace(tzinfo=timezone.utc) if timestamp.tzinfo is None else timestamp
        closest = min(
            headers_with_path,
            key=lambda h: abs((h[0].replace(tzinfo=timezone.utc) if h[0].tzinfo is None else h[0]) - target),
        )
        _, snapshot_id, filepath = closest

        # Return all DATA records for that snapshot_id
        return [
            r
            for r in self.load_records(filepath)
            if r.get("record_type") == "DATA" and r.get("snapshot_id") == snapshot_id
        ]
