"""
tests/test_research_data_adapter.py

Tests for ResearchDataAdapter.
"""

import pytest
from datetime import datetime, timezone
from unittest import mock

from research.data_adapter import ResearchDataAdapter
from research_features.models import FeatureRow


def _utc(h: int, m: int = 0) -> datetime:
    return datetime(2026, 8, 31, h, m, tzinfo=timezone.utc)


def _make_row(h: int, m: int, return_1m: float | None = None, mid_price: float | None = None) -> FeatureRow:
    return FeatureRow(
        symbol="BTCUSDT",
        timestamp=_utc(h, m),
        feature_version="v1",
        return_1m=return_1m,
        mid_price=mid_price,
    )


@pytest.fixture
def adapter():
    """Adapter with a mocked FeatureStore."""
    with mock.patch("research.data_adapter.FeatureStore") as mock_store_cls:
        inst = ResearchDataAdapter()
        inst._store = mock_store_cls.return_value
        yield inst, mock_store_cls.return_value


class TestGetFeatureSeries:
    def test_returns_sorted_series(self, adapter):
        adp, mock_store = adapter
        rows = [
            _make_row(10, 2, return_1m=0.02),
            _make_row(10, 0, return_1m=0.00),
            _make_row(10, 1, return_1m=0.01),
        ]
        mock_store.load.return_value = sorted(rows, key=lambda r: r.timestamp)

        series = adp.get_feature_series("BTCUSDT", "return_1m", _utc(10), _utc(11))

        assert len(series) == 3
        timestamps = [ts for ts, _ in series]
        assert timestamps == sorted(timestamps)

    def test_preserves_none_values(self, adapter):
        adp, mock_store = adapter
        rows = [
            _make_row(10, 0, return_1m=None),
            _make_row(10, 1, return_1m=0.01),
        ]
        mock_store.load.return_value = rows

        series = adp.get_feature_series("BTCUSDT", "return_1m", _utc(10), _utc(11))
        assert series[0][1] is None
        assert series[1][1] == pytest.approx(0.01)

    def test_int_coerced_to_float(self, adapter):
        adp, mock_store = adapter
        row = FeatureRow(symbol="BTCUSDT", timestamp=_utc(10), feature_version="v1", trade_count=42)
        mock_store.load.return_value = [row]

        series = adp.get_feature_series("BTCUSDT", "trade_count", _utc(10), _utc(11))
        assert isinstance(series[0][1], float)
        assert series[0][1] == 42.0

    def test_no_api_calls_made(self, adapter):
        """The adapter must never call any live API."""
        adp, mock_store = adapter
        mock_store.load.return_value = []

        adp.get_feature_series("BTCUSDT", "return_1m", _utc(10), _utc(11))

        # Verify only store.load was called — no httpx or aiohttp imports/calls
        mock_store.load.assert_called_once()

    def test_empty_symbol_returns_empty(self, adapter):
        adp, mock_store = adapter
        mock_store.load.return_value = []

        series = adp.get_feature_series("NODATA", "return_1m", _utc(10), _utc(11))
        assert series == []

    def test_timestamps_preserved_exactly(self, adapter):
        adp, mock_store = adapter
        ts = datetime(2026, 8, 31, 10, 30, 15, tzinfo=timezone.utc)
        row = FeatureRow(symbol="BTCUSDT", timestamp=ts, feature_version="v1", return_1m=0.01)
        mock_store.load.return_value = [row]

        series = adp.get_feature_series("BTCUSDT", "return_1m", _utc(10), _utc(11))
        assert series[0][0] == ts


class TestGetPriceSeries:
    def test_equivalent_to_feature_series(self, adapter):
        adp, mock_store = adapter
        rows = [_make_row(10, 0, mid_price=100.0)]
        mock_store.load.return_value = rows

        ps = adp.get_price_series("BTCUSDT", "mid_price", _utc(10), _utc(11))
        assert ps[0][1] == pytest.approx(100.0)


class TestGetAvailableSymbols:
    def test_returns_symbols_with_data(self, adapter):
        adp, mock_store = adapter

        # Use Path-spec mocks; name is set as a property
        def _make_dir_mock(name):
            m = mock.MagicMock()
            m.is_dir.return_value = True
            m.name = name
            m.__lt__ = lambda self, other: self.name < other.name
            m.__gt__ = lambda self, other: self.name > other.name
            m.__le__ = lambda self, other: self.name <= other.name
            m.__ge__ = lambda self, other: self.name >= other.name
            m.__eq__ = lambda self, other: self.name == other.name
            return m

        sym_a = _make_dir_mock("BTCUSDT")
        sym_b = _make_dir_mock("NODATA")

        with mock.patch.object(adp, "_features_dir") as mock_dir:
            mock_dir.exists.return_value = True
            mock_dir.iterdir.return_value = [sym_a, sym_b]

            def load_side(sym, start, end):
                if sym == "BTCUSDT":
                    return [_make_row(10, 0, return_1m=0.01)]
                return []

            adp._store.load.side_effect = load_side
            symbols = adp.get_available_symbols(_utc(10), _utc(11))
            assert "BTCUSDT" in symbols
            assert "NODATA" not in symbols
