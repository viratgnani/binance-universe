import pytest
from unittest import mock
from datetime import datetime, timezone
from pathlib import Path
from research_features.__main__ import _parse_symbols


def _dt(s: str) -> datetime:
    return datetime.fromisoformat(s.replace("Z", "+00:00"))


@mock.patch("universe.snapshot_repository.SnapshotRepository.list_snapshot_files")
@mock.patch("universe.snapshot_repository.SnapshotRepository.load_records")
def test_historical_survivorship_bias_fix(mock_load, mock_list):
    """
    Verify that `--symbols universe` dynamically loads the snapshot that was active
    on or immediately preceding the requested historical date, avoiding survivorship bias.
    """
    
    # We construct two snapshots
    # Snapshot A: 2025-01-01 (historical)
    file_a = Path("/data/snapshot_20250101.jsonl")
    records_a = [
        {"symbol": "SYMBOL_A", "record_type": "DATA", "universe_status": "ACTIVE_TOP_100"},
        {"symbol": "SYMBOL_B", "record_type": "DATA", "universe_status": "ELIGIBLE"} # Not active top 100
    ]
    
    # Snapshot B: 2026-08-31 (current)
    file_b = Path("/data/snapshot_20260831.jsonl")
    records_b = [
        {"symbol": "SYMBOL_B", "record_type": "DATA", "universe_status": "ACTIVE_TOP_100"},
        {"symbol": "SYMBOL_A", "record_type": "DATA", "universe_status": "DELISTED"} # Delisted
    ]
    
    mock_list.return_value = [file_a, file_b]
    
    def side_effect_load(f):
        if f == file_a: return records_a
        if f == file_b: return records_b
        return []
        
    mock_load.side_effect = side_effect_load
    
    # 1. Generate for historical period A (2025-01-15)
    # The engine should select Snapshot A because 20250101 <= 20250115, but 20260831 > 20250115.
    symbols_hist = _parse_symbols("universe", _dt("2025-01-15T00:00:00Z"))
    
    assert "SYMBOL_A" in symbols_hist, "Historical symbol missing!"
    assert "SYMBOL_B" not in symbols_hist, "Survivorship bias detected! Selected future winner."
    assert symbols_hist == ["SYMBOL_A"]
    
    # 2. Generate for current period (2026-09-01)
    symbols_curr = _parse_symbols("universe", _dt("2026-09-01T00:00:00Z"))
    assert symbols_curr == ["SYMBOL_B"], "Failed to select current snapshot"
    
    # 3. Generate for way in the past (before any snapshot)
    # The CLI falls back to the earliest snapshot
    symbols_past = _parse_symbols("universe", _dt("2024-01-01T00:00:00Z"))
    assert symbols_past == ["SYMBOL_A"]
    
    # 4. Explicit symbols bypass the lookup
    symbols_explicit = _parse_symbols("BTCUSDT,ETHUSDT", _dt("2025-01-15T00:00:00Z"))
    assert symbols_explicit == ["BTCUSDT", "ETHUSDT"]
