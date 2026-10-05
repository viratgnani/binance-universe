"""
tests/test_research_store.py

Tests for ResearchResultStore — persistence, reload, idempotency.
"""

import pytest
import tempfile
from datetime import datetime, timezone, timedelta
from pathlib import Path

from research.models import EventOutcome, OutcomeStatus
from research.result_store import ResearchResultStore


def _utc(h: int, m: int = 0) -> datetime:
    return datetime(2026, 8, 31, h, m, tzinfo=timezone.utc)


def _make_outcome(
    event_ts: datetime,
    outcome_name: str = "fwd_1m",
    status: OutcomeStatus = OutcomeStatus.VALID,
    outcome_value: float | None = 0.01,
    outcome_ts: datetime | None = None,
    rid: str = "test_r1",
    sym: str = "BTCUSDT",
) -> EventOutcome:
    return EventOutcome(
        research_id=rid,
        symbol=sym,
        event_timestamp=event_ts,
        event_definition_hash="abc123",
        outcome_name=outcome_name,
        horizon_minutes=1,
        outcome_value=outcome_value,
        outcome_timestamp=outcome_ts or (event_ts + timedelta(minutes=1)),
        status=status,
    )


@pytest.fixture
def store(tmp_path):
    return ResearchResultStore(base_dir=tmp_path / "research")


class TestSaveAndLoad:
    def test_save_returns_counts(self, store):
        outcomes = [_make_outcome(_utc(10))]
        written, skipped = store.save("test_r1", "BTCUSDT", outcomes)
        assert written == 1
        assert skipped == 0

    def test_load_returns_saved_outcomes(self, store):
        o = _make_outcome(_utc(10))
        store.save("test_r1", "BTCUSDT", [o])

        loaded = store.load("test_r1", "BTCUSDT", _utc(10), _utc(11))
        assert len(loaded) == 1
        assert loaded[0].outcome_name == "fwd_1m"
        assert loaded[0].outcome_value == pytest.approx(0.01)

    def test_load_sorted_by_timestamp(self, store):
        outcomes = [
            _make_outcome(_utc(10, 2)),
            _make_outcome(_utc(10, 0)),
            _make_outcome(_utc(10, 1)),
        ]
        store.save("test_r1", "BTCUSDT", outcomes)

        loaded = store.load("test_r1", "BTCUSDT", _utc(10), _utc(11))
        tss = [o.event_timestamp for o in loaded]
        assert tss == sorted(tss)

    def test_load_empty_on_no_data(self, store):
        loaded = store.load("nonexistent", "BTCUSDT", _utc(10), _utc(11))
        assert loaded == []


class TestIdempotency:
    def test_duplicate_save_skipped(self, store):
        o = _make_outcome(_utc(10))
        store.save("test_r1", "BTCUSDT", [o])
        written, skipped = store.save("test_r1", "BTCUSDT", [o])
        assert written == 0
        assert skipped == 1

    def test_three_runs_no_duplicates(self, store):
        o = _make_outcome(_utc(10))
        for _ in range(3):
            store.save("test_r1", "BTCUSDT", [o])

        loaded = store.load("test_r1", "BTCUSDT", _utc(10), _utc(11))
        assert len(loaded) == 1

    def test_different_outcome_name_not_duplicate(self, store):
        o1 = _make_outcome(_utc(10), outcome_name="fwd_1m")
        o2 = _make_outcome(_utc(10), outcome_name="fwd_3m")
        store.save("test_r1", "BTCUSDT", [o1, o2])

        loaded = store.load("test_r1", "BTCUSDT", _utc(10), _utc(11))
        assert len(loaded) == 2


class TestResearchIdIsolation:
    def test_different_research_ids_are_isolated(self, store):
        o1 = _make_outcome(_utc(10), rid="study_A")
        o2 = _make_outcome(_utc(10), rid="study_B")
        store.save("study_A", "BTCUSDT", [o1])
        store.save("study_B", "BTCUSDT", [o2])

        a_loaded = store.load("study_A", "BTCUSDT", _utc(10), _utc(11))
        b_loaded = store.load("study_B", "BTCUSDT", _utc(10), _utc(11))
        assert len(a_loaded) == 1
        assert len(b_loaded) == 1

    def test_time_range_filter(self, store):
        outcomes = [
            _make_outcome(_utc(10), outcome_name="o1"),
            _make_outcome(_utc(12), outcome_name="o2"),
        ]
        store.save("test_r1", "BTCUSDT", outcomes)

        loaded = store.load("test_r1", "BTCUSDT", _utc(10), _utc(11))
        assert len(loaded) == 1
        assert loaded[0].outcome_name == "o1"


class TestNullOutcomesPersisted:
    def test_missing_price_status_persisted(self, store):
        o = _make_outcome(_utc(10), status=OutcomeStatus.MISSING_PRICE, outcome_value=None, outcome_ts=None)
        store.save("test_r1", "BTCUSDT", [o])
        loaded = store.load("test_r1", "BTCUSDT", _utc(10), _utc(11))
        assert loaded[0].status == OutcomeStatus.MISSING_PRICE
        assert loaded[0].outcome_value is None

    def test_insufficient_data_status_persisted(self, store):
        o = _make_outcome(_utc(10), status=OutcomeStatus.INSUFFICIENT_FUTURE_DATA, outcome_value=None, outcome_ts=None)
        store.save("test_r1", "BTCUSDT", [o])
        loaded = store.load("test_r1", "BTCUSDT", _utc(10), _utc(11))
        assert loaded[0].status == OutcomeStatus.INSUFFICIENT_FUTURE_DATA
