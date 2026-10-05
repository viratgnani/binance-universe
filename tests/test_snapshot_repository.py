"""
tests/test_snapshot_repository.py

Unit tests for SnapshotRepository.

Uses a temporary directory for all file I/O so tests are isolated and clean.
No Binance API calls.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from universe.config import UniverseConfig
from universe.models import SnapshotHeader, SnapshotRecord, UniverseStatus
from universe.snapshot_repository import SnapshotRepository


# --------------------------------------------------------------------------- #
#  Fixtures
# --------------------------------------------------------------------------- #


@pytest.fixture()
def tmp_cfg(tmp_path: Path) -> UniverseConfig:
    """Config pointing at a temporary snapshot directory."""
    cfg = UniverseConfig()
    cfg.SNAPSHOT_DIR = tmp_path / "snapshots"
    return cfg


@pytest.fixture()
def repo(tmp_cfg: UniverseConfig) -> SnapshotRepository:
    return SnapshotRepository(tmp_cfg)


def _make_ts(offset_seconds: int = 0) -> datetime:
    base = datetime(2026, 8, 31, 12, 0, 0, tzinfo=timezone.utc)
    return base + timedelta(seconds=offset_seconds)


def _make_record(symbol: str, rank: int, score: float, ts: datetime, sid: str) -> SnapshotRecord:
    return SnapshotRecord(
        snapshot_timestamp=ts,
        snapshot_id=sid,
        symbol=symbol,
        rank=rank,
        score=score,
        universe_status=UniverseStatus.ACTIVE_TOP_100 if rank <= 100 else UniverseStatus.WATCHLIST,
        volume_24h_quote=1_000_000.0,
        open_interest=500_000.0,
        spread_bps=1.5,
    )


def _make_header(sid: str, ts: datetime, total: int = 5) -> SnapshotHeader:
    return SnapshotHeader(
        snapshot_id=sid,
        snapshot_timestamp=ts,
        total_eligible=total,
        total_ranked=total,
        total_failed=0,
        top_n=100,
    )


# --------------------------------------------------------------------------- #
#  Tests
# --------------------------------------------------------------------------- #


class TestSnapshotSave:
    def test_creates_snapshot_file(self, repo: SnapshotRepository, tmp_cfg: UniverseConfig):
        ts = _make_ts()
        sid = "20260831T120000Z"
        records = [_make_record("BTCUSDT", 1, 0.99, ts, sid)]
        header = _make_header(sid, ts)
        path = repo.save(sid, ts, records, header)
        assert path.exists()
        assert path.suffix == ".jsonl"

    def test_snapshot_file_named_by_date(self, repo: SnapshotRepository):
        ts = _make_ts()
        sid = "20260831T120000Z"
        path = repo.save(sid, ts, [], _make_header(sid, ts, total=0))
        assert "20260831" in path.name

    def test_snapshot_contains_header_and_data(self, repo: SnapshotRepository):
        ts = _make_ts()
        sid = "20260831T120000Z"
        records = [
            _make_record("BTCUSDT", 1, 0.99, ts, sid),
            _make_record("ETHUSDT", 2, 0.95, ts, sid),
        ]
        path = repo.save(sid, ts, records, _make_header(sid, ts, total=2))

        lines = [json.loads(l) for l in path.read_text().splitlines() if l.strip()]
        record_types = [l["record_type"] for l in lines]
        assert "HEADER" in record_types
        assert record_types.count("DATA") == 2

    def test_append_only_two_refreshes_same_day(self, repo: SnapshotRepository):
        """Two refreshes on the same day must both be present in the file."""
        ts1 = _make_ts(0)
        ts2 = _make_ts(3600)  # 1 hour later, same day
        sid1, sid2 = "20260831T120000Z", "20260831T130000Z"

        path1 = repo.save(sid1, ts1, [_make_record("BTCUSDT", 1, 0.99, ts1, sid1)], _make_header(sid1, ts1))
        path2 = repo.save(sid2, ts2, [_make_record("BTCUSDT", 1, 0.98, ts2, sid2)], _make_header(sid2, ts2))

        # Must write to the same file
        assert path1 == path2

        lines = [json.loads(l) for l in path1.read_text().splitlines() if l.strip()]
        headers = [l for l in lines if l["record_type"] == "HEADER"]
        assert len(headers) == 2, "Both refresh headers must be in the file"

        data_lines = [l for l in lines if l["record_type"] == "DATA"]
        assert len(data_lines) == 2, "Both BTCUSDT data records must be present"

    def test_different_days_different_files(self, repo: SnapshotRepository, tmp_cfg: UniverseConfig):
        ts1 = datetime(2026, 8, 31, 12, 0, 0, tzinfo=timezone.utc)
        ts2 = datetime(2026, 9, 1, 12, 0, 0, tzinfo=timezone.utc)
        sid1, sid2 = "20260831T120000Z", "20260901T120000Z"

        path1 = repo.save(sid1, ts1, [], _make_header(sid1, ts1, total=0))
        path2 = repo.save(sid2, ts2, [], _make_header(sid2, ts2, total=0))

        assert path1 != path2
        assert "20260831" in path1.name
        assert "20260901" in path2.name


class TestSnapshotRead:
    def test_get_snapshots_for_symbol(self, repo: SnapshotRepository):
        ts = _make_ts()
        sid = "20260831T120000Z"
        records = [
            _make_record("BTCUSDT", 1, 0.99, ts, sid),
            _make_record("ETHUSDT", 2, 0.95, ts, sid),
        ]
        repo.save(sid, ts, records, _make_header(sid, ts, total=2))

        btc_records = repo.get_snapshots_for_symbol("BTCUSDT")
        assert len(btc_records) == 1
        assert btc_records[0]["symbol"] == "BTCUSDT"

    def test_rank_change_representable(self, repo: SnapshotRepository):
        """
        After two refreshes, rank history for a symbol should show both ranks.
        """
        ts1 = _make_ts(0)
        ts2 = _make_ts(3600)
        sid1, sid2 = "20260831T120000Z", "20260831T130000Z"

        # BTC drops from rank 1 to rank 2
        repo.save(sid1, ts1, [_make_record("BTCUSDT", 1, 0.99, ts1, sid1)], _make_header(sid1, ts1))
        repo.save(sid2, ts2, [_make_record("BTCUSDT", 2, 0.94, ts2, sid2)], _make_header(sid2, ts2))

        history = repo.get_snapshots_for_symbol("BTCUSDT")
        assert len(history) == 2
        ranks = [h["rank"] for h in history]
        assert 1 in ranks
        assert 2 in ranks

    def test_list_snapshot_files_sorted(self, repo: SnapshotRepository):
        ts1 = datetime(2026, 8, 30, 12, 0, 0, tzinfo=timezone.utc)
        ts2 = datetime(2026, 8, 31, 12, 0, 0, tzinfo=timezone.utc)
        repo.save("sid1", ts1, [], _make_header("sid1", ts1, total=0))
        repo.save("sid2", ts2, [], _make_header("sid2", ts2, total=0))

        files = repo.list_snapshot_files()
        assert len(files) == 2
        assert "20260830" in files[0].name
        assert "20260831" in files[1].name

    def test_list_snapshot_files_empty_when_no_dir(self, tmp_path: Path):
        cfg = UniverseConfig()
        cfg.SNAPSHOT_DIR = tmp_path / "nonexistent"
        repo = SnapshotRepository(cfg)
        assert repo.list_snapshot_files() == []

    def test_get_snapshot_at(self, repo: SnapshotRepository):
        ts = _make_ts()
        sid = "20260831T120000Z"
        records = [
            _make_record("BTCUSDT", 1, 0.99, ts, sid),
            _make_record("ETHUSDT", 2, 0.95, ts, sid),
        ]
        repo.save(sid, ts, records, _make_header(sid, ts, total=2))

        result = repo.get_snapshot_at(ts)
        symbols = {r["symbol"] for r in result}
        assert "BTCUSDT" in symbols
        assert "ETHUSDT" in symbols
