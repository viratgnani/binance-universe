"""
tests/test_ranking_engine.py

Unit tests for normalization.py and ranking_engine.py.

All tests use in-memory constructed MarketMetrics objects.
No API calls.
"""

from __future__ import annotations

import pytest

from universe.config import UniverseConfig
from universe.models import MarketMetrics, NormalizedMetrics
from universe.normalization import normalize_metrics
from universe.ranking_engine import RankingEngine


# --------------------------------------------------------------------------- #
#  Helpers
# --------------------------------------------------------------------------- #


def make_metrics(
    symbol: str,
    volume: float = 1_000_000.0,
    oi: float = 500_000.0,
    spread: float = 1.0,
    failed: bool = False,
) -> MarketMetrics:
    """Build a MarketMetrics object with sensible defaults for testing."""
    if failed:
        return MarketMetrics(symbol=symbol, metrics_failed=True, failure_reason="test")
    return MarketMetrics(
        symbol=symbol,
        volume_24h_quote=volume,
        volume_24h_base=volume / 50_000,
        last_price=50_000.0,
        bid_price=49_999.0,
        ask_price=50_001.0,
        spread_bps=spread,
        open_interest=oi,
    )


def make_normalized(symbol: str, vol: float, oi: float, spread: float) -> NormalizedMetrics:
    return NormalizedMetrics(symbol=symbol, norm_volume=vol, norm_oi=oi, norm_spread=spread)


# --------------------------------------------------------------------------- #
#  Normalization tests
# --------------------------------------------------------------------------- #


class TestNormalization:
    def test_highest_volume_gets_norm_1(self):
        metrics = [
            make_metrics("HIGH", volume=1_000_000),
            make_metrics("MID", volume=500_000),
            make_metrics("LOW", volume=100_000),
        ]
        normalized, skipped = normalize_metrics(metrics)
        by_sym = {n.symbol: n for n in normalized}
        assert by_sym["HIGH"].norm_volume > by_sym["MID"].norm_volume > by_sym["LOW"].norm_volume
        # Highest should be very close to 1.0
        assert by_sym["HIGH"].norm_volume > 0.999

    def test_tightest_spread_gets_highest_norm_spread(self):
        """Lower spread_bps should produce higher norm_spread (already inverted)."""
        metrics = [
            make_metrics("TIGHT", spread=0.5),
            make_metrics("WIDE", spread=10.0),
        ]
        normalized, _ = normalize_metrics(metrics)
        by_sym = {n.symbol: n for n in normalized}
        assert by_sym["TIGHT"].norm_spread > by_sym["WIDE"].norm_spread

    def test_failed_metrics_excluded_from_normalization(self):
        metrics = [
            make_metrics("GOOD_A", volume=1_000_000),
            make_metrics("GOOD_B", volume=500_000),
            make_metrics("BAD", failed=True),
        ]
        normalized, skipped = normalize_metrics(metrics)
        norm_symbols = {n.symbol for n in normalized}
        assert "BAD" not in norm_symbols
        assert "BAD" in skipped
        assert "GOOD_A" in norm_symbols
        assert "GOOD_B" in norm_symbols

    def test_none_volume_excluded(self):
        m = MarketMetrics(symbol="NOVOLUME", volume_24h_quote=None, open_interest=100, spread_bps=1.0)
        normalized, skipped = normalize_metrics([m, make_metrics("GOOD")])
        assert "NOVOLUME" in skipped
        assert "GOOD" in {n.symbol for n in normalized}

    def test_none_oi_excluded(self):
        m = MarketMetrics(symbol="NOOI", volume_24h_quote=1_000_000, open_interest=None, spread_bps=1.0)
        _, skipped = normalize_metrics([m, make_metrics("GOOD")])
        assert "NOOI" in skipped

    def test_none_spread_gets_neutral_score(self):
        """
        Contract with no spread_bps should get norm_spread=0.5 (neutral) and still
        be ranked — not excluded. This handles contracts where bid/ask is unavailable.
        """
        m = MarketMetrics(symbol="NOSPREAD", volume_24h_quote=1_000_000, open_interest=100, spread_bps=None)
        normalized, skipped = normalize_metrics([m, make_metrics("GOOD")])
        assert "NOSPREAD" not in skipped
        nospread = next(n for n in normalized if n.symbol == "NOSPREAD")
        assert abs(nospread.norm_spread - 0.5) < 1e-6

    def test_identical_values_no_division_by_zero(self):
        """When all values are identical, epsilon prevents ZeroDivisionError."""
        metrics = [make_metrics("A", volume=100, oi=50, spread=1.0) for _ in range(3)]
        for i, m in enumerate(metrics):
            m.symbol = f"SYM{i}"
        normalized, _ = normalize_metrics(metrics)
        assert len(normalized) == 3
        # All norms should be 0 (since max - min = 0, value - min = 0)
        for n in normalized:
            assert abs(n.norm_volume) < 1e-6

    def test_single_contract_normalizes_safely(self):
        metrics = [make_metrics("ONLY")]
        normalized, skipped = normalize_metrics(metrics)
        assert len(normalized) == 1
        assert skipped == []
        # With a single element, min==max, so value normalizes to ~0 (epsilon protects)
        assert normalized[0].norm_volume >= 0.0

    def test_empty_input(self):
        normalized, skipped = normalize_metrics([])
        assert normalized == []
        assert skipped == []

    def test_all_failed_input(self):
        metrics = [make_metrics(f"BAD{i}", failed=True) for i in range(5)]
        normalized, skipped = normalize_metrics(metrics)
        assert normalized == []
        assert len(skipped) == 5


# --------------------------------------------------------------------------- #
#  RankingEngine tests
# --------------------------------------------------------------------------- #


class TestRankingEngine:
    def _engine(self, **weight_overrides) -> RankingEngine:
        cfg = UniverseConfig()
        for k, v in weight_overrides.items():
            setattr(cfg, k, v)
        return RankingEngine(cfg)

    def test_higher_volume_ranks_higher_when_oi_spread_equal(self):
        engine = self._engine(VOLUME_WEIGHT=1.0, OI_WEIGHT=0.0, SPREAD_WEIGHT=0.0)
        normalized = [
            make_normalized("BTC", vol=1.0, oi=0.5, spread=0.5),
            make_normalized("ETH", vol=0.5, oi=0.5, spread=0.5),
            make_normalized("SOL", vol=0.2, oi=0.5, spread=0.5),
        ]
        results = engine.rank(normalized)
        by_sym = {r.symbol: r for r in results}
        assert by_sym["BTC"].rank < by_sym["ETH"].rank < by_sym["SOL"].rank

    def test_tighter_spread_ranks_higher_when_volume_oi_equal(self):
        engine = self._engine(VOLUME_WEIGHT=0.0, OI_WEIGHT=0.0, SPREAD_WEIGHT=1.0)
        normalized = [
            make_normalized("TIGHT", vol=0.5, oi=0.5, spread=1.0),  # already inverted
            make_normalized("WIDE", vol=0.5, oi=0.5, spread=0.0),
        ]
        results = engine.rank(normalized)
        by_sym = {r.symbol: r for r in results}
        assert by_sym["TIGHT"].rank < by_sym["WIDE"].rank

    def test_ranking_is_deterministic(self):
        """Running the same input twice produces identical output."""
        engine = self._engine()
        normalized = [
            make_normalized(f"SYM{i}", vol=i / 10, oi=i / 10, spread=i / 10)
            for i in range(20)
        ]
        results_a = engine.rank(normalized)
        results_b = engine.rank(normalized)
        assert [(r.symbol, r.rank) for r in results_a] == [(r.symbol, r.rank) for r in results_b]

    def test_tie_broken_alphabetically(self):
        """Identical scores → alphabetically earlier symbol gets lower rank number."""
        engine = self._engine()
        normalized = [
            make_normalized("ZEBRA", vol=0.5, oi=0.5, spread=0.5),
            make_normalized("APPLE", vol=0.5, oi=0.5, spread=0.5),
            make_normalized("MANGO", vol=0.5, oi=0.5, spread=0.5),
        ]
        results = engine.rank(normalized)
        by_sym = {r.symbol: r for r in results}
        assert by_sym["APPLE"].rank == 1
        assert by_sym["MANGO"].rank == 2
        assert by_sym["ZEBRA"].rank == 3

    def test_ranks_are_sequential_starting_at_one(self):
        engine = self._engine()
        normalized = [
            make_normalized(f"SYM{i}", vol=i / 5, oi=i / 5, spread=i / 5)
            for i in range(1, 11)
        ]
        results = engine.rank(normalized)
        ranks = sorted(r.rank for r in results)
        assert ranks == list(range(1, 11))

    def test_scores_are_in_unit_interval(self):
        engine = self._engine()
        normalized = [
            make_normalized(f"SYM{i}", vol=i / 10, oi=i / 10, spread=i / 10)
            for i in range(11)
        ]
        for r in engine.rank(normalized):
            assert 0.0 <= r.score <= 1.0, f"{r.symbol} score out of range: {r.score}"

    def test_empty_input_returns_empty(self):
        engine = self._engine()
        assert engine.rank([]) == []

    def test_single_contract_gets_rank_one(self):
        engine = self._engine()
        results = engine.rank([make_normalized("ONLY", vol=0.5, oi=0.5, spread=0.5)])
        assert len(results) == 1
        assert results[0].rank == 1

    def test_weight_validation_raises_on_bad_sum(self):
        cfg = UniverseConfig()
        cfg.VOLUME_WEIGHT = 0.5
        cfg.OI_WEIGHT = 0.5
        cfg.SPREAD_WEIGHT = 0.5   # sum = 1.5 → invalid
        with pytest.raises(ValueError, match="sum to 1.0"):
            RankingEngine(cfg)


# --------------------------------------------------------------------------- #
#  Top-100 selection tests
# --------------------------------------------------------------------------- #


class TestTopNSelection:
    def test_top_100_exact_when_100_or_more_eligible(self):
        from universe.top_n_selector import TopNSelector
        from universe.models import RankResult

        cfg = UniverseConfig()
        cfg.TOP_N = 100
        selector = TopNSelector(cfg)

        ranked = [
            RankResult(symbol=f"SYM{i:03d}", score=1.0 - i / 200, rank=i + 1)
            for i in range(150)
        ]
        results = selector.select(ranked)

        from universe.models import UniverseStatus
        active = [r for r in results if r.universe_status == UniverseStatus.ACTIVE_TOP_100]
        watchlist = [r for r in results if r.universe_status == UniverseStatus.WATCHLIST]

        assert len(active) == 100
        assert len(watchlist) == 50

    def test_all_active_when_fewer_than_top_n(self):
        from universe.top_n_selector import TopNSelector
        from universe.models import RankResult, UniverseStatus

        cfg = UniverseConfig()
        cfg.TOP_N = 100
        selector = TopNSelector(cfg)

        ranked = [
            RankResult(symbol=f"SYM{i}", score=0.9, rank=i + 1)
            for i in range(50)
        ]
        results = selector.select(ranked)
        active = [r for r in results if r.universe_status == UniverseStatus.ACTIVE_TOP_100]
        assert len(active) == 50

    def test_rank_1_is_always_active(self):
        from universe.top_n_selector import TopNSelector
        from universe.models import RankResult, UniverseStatus

        cfg = UniverseConfig()
        selector = TopNSelector(cfg)
        ranked = [RankResult(symbol="BTCUSDT", score=0.99, rank=1)]
        results = selector.select(ranked)
        assert results[0].universe_status == UniverseStatus.ACTIVE_TOP_100

    def test_configurable_top_n(self):
        from universe.top_n_selector import TopNSelector
        from universe.models import RankResult, UniverseStatus

        cfg = UniverseConfig()
        cfg.TOP_N = 10
        selector = TopNSelector(cfg)

        ranked = [
            RankResult(symbol=f"SYM{i}", score=1.0 - i / 50, rank=i + 1)
            for i in range(30)
        ]
        results = selector.select(ranked)
        active = [r for r in results if r.universe_status == UniverseStatus.ACTIVE_TOP_100]
        assert len(active) == 10
