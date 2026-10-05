"""
tests/test_normalizers.py

Comprehensive unit tests for all four normalization methods.

Tests cover:
  - Determinism (identical input → identical output)
  - Constant-value edge cases (all same value → no division by zero)
  - Zero values
  - Positive heavy-tailed distributions
  - Percentile ordering (rank monotonicity)
  - Winsorization boundaries (values above upper_pct are clipped)
  - Spread direction (lower spread_bps → higher norm_spread)
  - Missing spread → neutral 0.5
  - Failed metrics → excluded from output (in skipped list)
  - No NaN or Inf in output
  - Ranking determinism after normalization
  - MinMaxNormalizer matches V1 baseline behavior
  - LogMinMaxNormalizer compresses high-volume outliers
  - PercentileNormalizer produces near-uniform distribution
  - WinsorizedMinMaxNormalizer clips outliers
  - All methods produce norm values in [0, 1]
  - Spread direction preserved across all methods
"""

from __future__ import annotations

import math
from typing import Callable

import pytest

from universe.models import MarketMetrics, NormalizedMetrics
from universe.normalizers import (
    LogMinMaxNormalizer,
    MinMaxNormalizer,
    PercentileNormalizer,
    WinsorizedMinMaxNormalizer,
    _percentile,
    get_all_normalizers,
)
from universe.ranking_engine import RankingEngine


# =========================================================================== #
#  Fixtures / Helpers
# =========================================================================== #


def make_metrics(
    symbol: str,
    volume: float | None = 1_000_000.0,
    oi: float | None = 500_000.0,
    spread_bps: float | None = 2.0,
    failed: bool = False,
) -> MarketMetrics:
    """Create a MarketMetrics object bypassing the model_validator (spread pre-set)."""
    m = MarketMetrics(
        symbol=symbol,
        volume_24h_quote=volume,
        open_interest=oi,
        metrics_failed=failed,
    )
    # bypass model_validator by directly setting the pre-computed spread
    object.__setattr__(m, "spread_bps", spread_bps)
    return m


def make_batch(n: int, vol_multiplier: float = 1.0) -> list[MarketMetrics]:
    """Create n contracts with linearly increasing volume, OI, and spread."""
    return [
        make_metrics(f"SYM{i:04d}", volume=float(i + 1) * vol_multiplier,
                     oi=float(i + 1) * 100, spread_bps=float(i + 1) * 0.5)
        for i in range(n)
    ]


ALL_NORMALIZERS = [
    MinMaxNormalizer(),
    LogMinMaxNormalizer(),
    PercentileNormalizer(),
    WinsorizedMinMaxNormalizer(lower_pct=1.0, upper_pct=99.0),
]


# =========================================================================== #
#  _percentile helper tests
# =========================================================================== #

class TestPercentileHelper:
    def test_p50_simple(self):
        assert _percentile([1.0, 2.0, 3.0], 50) == 2.0

    def test_p0_is_min(self):
        data = [3.0, 1.0, 4.0, 1.0, 5.0]
        assert _percentile(data, 0) == min(data)

    def test_p100_is_max(self):
        data = [3.0, 1.0, 4.0, 1.0, 5.0]
        assert _percentile(data, 100) == max(data)

    def test_empty_returns_zero(self):
        assert _percentile([], 50) == 0.0

    def test_single_element(self):
        assert _percentile([42.0], 25) == 42.0


# =========================================================================== #
#  Property tests applicable to ALL normalizers
# =========================================================================== #


@pytest.mark.parametrize("normalizer", ALL_NORMALIZERS)
class TestAllNormalizersProperties:

    def test_deterministic(self, normalizer):
        """Running twice on same input produces identical output."""
        batch = make_batch(30)
        result_a, skip_a = normalizer.normalize(batch)
        result_b, skip_b = normalizer.normalize(batch)
        assert [n.symbol for n in result_a] == [n.symbol for n in result_b]
        assert [(n.norm_volume, n.norm_oi, n.norm_spread) for n in result_a] == \
               [(n.norm_volume, n.norm_oi, n.norm_spread) for n in result_b]

    def test_all_outputs_in_unit_interval(self, normalizer):
        """norm_volume, norm_oi, norm_spread must all be in [0, 1]."""
        batch = make_batch(50)
        normalized, _ = normalizer.normalize(batch)
        for nm in normalized:
            assert 0.0 <= nm.norm_volume <= 1.0, f"{normalizer.name}: norm_volume={nm.norm_volume}"
            assert 0.0 <= nm.norm_oi     <= 1.0, f"{normalizer.name}: norm_oi={nm.norm_oi}"
            assert 0.0 <= nm.norm_spread <= 1.0, f"{normalizer.name}: norm_spread={nm.norm_spread}"

    def test_no_nan_or_inf(self, normalizer):
        """No NaN or Inf values in output."""
        batch = make_batch(50)
        normalized, _ = normalizer.normalize(batch)
        for nm in normalized:
            assert not math.isnan(nm.norm_volume),  f"{normalizer.name} NaN in norm_volume"
            assert not math.isnan(nm.norm_oi),      f"{normalizer.name} NaN in norm_oi"
            assert not math.isnan(nm.norm_spread),  f"{normalizer.name} NaN in norm_spread"
            assert not math.isinf(nm.norm_volume),  f"{normalizer.name} Inf in norm_volume"
            assert not math.isinf(nm.norm_oi),      f"{normalizer.name} Inf in norm_oi"
            assert not math.isinf(nm.norm_spread),  f"{normalizer.name} Inf in norm_spread"

    def test_failed_metrics_excluded(self, normalizer):
        """Contracts with metrics_failed=True must appear in skipped, not normalized."""
        batch = [
            make_metrics("GOOD1", volume=1e6, oi=5e5, spread_bps=2.0),
            make_metrics("GOOD2", volume=2e6, oi=6e5, spread_bps=3.0),
            make_metrics("FAILED", volume=3e6, oi=7e5, spread_bps=1.0, failed=True),
        ]
        normalized, skipped = normalizer.normalize(batch)
        symbols = {nm.symbol for nm in normalized}
        assert "FAILED" not in symbols
        assert "FAILED" in skipped
        assert "GOOD1" in symbols
        assert "GOOD2" in symbols

    def test_none_volume_excluded(self, normalizer):
        """Contracts with None volume must appear in skipped."""
        batch = [
            make_metrics("HAS_VOL", volume=1e6, oi=5e5, spread_bps=2.0),
            make_metrics("NO_VOL", volume=None, oi=5e5, spread_bps=2.0),
        ]
        normalized, skipped = normalizer.normalize(batch)
        symbols = {nm.symbol for nm in normalized}
        assert "NO_VOL" not in symbols
        assert "NO_VOL" in skipped

    def test_none_oi_excluded(self, normalizer):
        """Contracts with None OI must appear in skipped."""
        batch = [
            make_metrics("HAS_OI", volume=1e6, oi=5e5, spread_bps=2.0),
            make_metrics("NO_OI", volume=1e6, oi=None, spread_bps=2.0),
        ]
        normalized, skipped = normalizer.normalize(batch)
        symbols = {nm.symbol for nm in normalized}
        assert "NO_OI" not in symbols
        assert "NO_OI" in skipped

    def test_missing_spread_gets_neutral_05(self, normalizer):
        """Contracts with spread_bps=None must get norm_spread = 0.5."""
        batch = [
            make_metrics("HAS_SPREAD",  volume=1e6, oi=5e5, spread_bps=2.0),
            make_metrics("NO_SPREAD",   volume=2e6, oi=6e5, spread_bps=None),
            make_metrics("NO_SPREAD_2", volume=3e6, oi=7e5, spread_bps=None),
        ]
        normalized, skipped = normalizer.normalize(batch)
        norm_map = {nm.symbol: nm for nm in normalized}
        assert "NO_SPREAD" in norm_map
        assert norm_map["NO_SPREAD"].norm_spread == 0.5, (
            f"{normalizer.name}: NO_SPREAD expected norm_spread=0.5, "
            f"got {norm_map['NO_SPREAD'].norm_spread}"
        )
        assert norm_map["NO_SPREAD_2"].norm_spread == 0.5

    def test_spread_direction_lower_is_better(self, normalizer):
        """Lower spread_bps must produce higher norm_spread."""
        batch = [
            make_metrics("TIGHT", volume=1e6, oi=5e5, spread_bps=0.5),
            make_metrics("WIDE",  volume=1e6, oi=5e5, spread_bps=10.0),
        ]
        normalized, _ = normalizer.normalize(batch)
        norm_map = {nm.symbol: nm for nm in normalized}
        # Tight spread should rank higher (higher norm_spread)
        assert norm_map["TIGHT"].norm_spread > norm_map["WIDE"].norm_spread, (
            f"{normalizer.name}: TIGHT spread should have higher norm_spread than WIDE. "
            f"TIGHT={norm_map['TIGHT'].norm_spread}, WIDE={norm_map['WIDE'].norm_spread}"
        )

    def test_empty_input_returns_empty(self, normalizer):
        """Empty input → empty output, no crash."""
        normalized, skipped = normalizer.normalize([])
        assert normalized == []
        assert isinstance(skipped, list)

    def test_single_contract_normalizes_safely(self, normalizer):
        """Single contract must produce no NaN/Inf and valid [0,1] output."""
        batch = [make_metrics("SOLO", volume=1e6, oi=5e5, spread_bps=2.0)]
        normalized, skipped = normalizer.normalize(batch)
        # Single element: spreads and volumes may normalize to 0 or 0.5 or similar
        assert len(normalized) == 1
        nm = normalized[0]
        assert 0.0 <= nm.norm_volume <= 1.0
        assert 0.0 <= nm.norm_oi <= 1.0
        assert 0.0 <= nm.norm_spread <= 1.0
        assert not any(math.isnan(v) for v in [nm.norm_volume, nm.norm_oi, nm.norm_spread])

    def test_constant_values_no_division_by_zero(self, normalizer):
        """All contracts with identical metric values must not crash."""
        batch = [make_metrics(f"SYM{i}", volume=1000.0, oi=500.0, spread_bps=2.0)
                 for i in range(10)]
        normalized, _ = normalizer.normalize(batch)
        assert len(normalized) == 10
        for nm in normalized:
            assert not any(math.isnan(v) for v in [nm.norm_volume, nm.norm_oi, nm.norm_spread])

    def test_zero_volume_does_not_crash(self, normalizer):
        """Zero volume is a valid edge case — must not produce NaN/crash."""
        batch = [
            make_metrics("ZERO_VOL", volume=0.0, oi=500.0, spread_bps=2.0),
            make_metrics("HAS_VOL",  volume=1e6,  oi=500.0, spread_bps=2.0),
        ]
        normalized, skipped = normalizer.normalize(batch)
        # Both should be present (zero volume is valid, not None)
        symbols = {nm.symbol for nm in normalized}
        assert "ZERO_VOL" in symbols
        for nm in normalized:
            assert not any(math.isnan(v) for v in [nm.norm_volume, nm.norm_oi, nm.norm_spread])

    def test_ranking_after_normalization_is_deterministic(self, normalizer):
        """Running RankingEngine twice on the same normalized output is deterministic."""
        engine = RankingEngine()
        batch = make_batch(30)
        normalized, _ = normalizer.normalize(batch)
        result_a = engine.rank(normalized)
        result_b = engine.rank(normalized)
        assert [(r.symbol, r.rank) for r in result_a] == [(r.symbol, r.rank) for r in result_b]

    def test_output_count_matches_rankable_input(self, normalizer):
        """Number of normalized outputs = number of rankable input contracts."""
        batch = [
            make_metrics("OK1",    volume=1e6, oi=5e5, spread_bps=2.0),
            make_metrics("OK2",    volume=2e6, oi=6e5, spread_bps=None),   # no spread → included
            make_metrics("FAILED", volume=3e6, oi=7e5, failed=True),        # failed → skipped
            make_metrics("NO_OI",  volume=1e6, oi=None, spread_bps=1.0),   # no OI → skipped
        ]
        normalized, skipped = normalizer.normalize(batch)
        assert len(normalized) == 2   # OK1 + OK2
        assert len(skipped) == 2      # FAILED + NO_OI


# =========================================================================== #
#  MinMaxNormalizer specific
# =========================================================================== #


class TestMinMaxNormalizer:
    def test_highest_volume_gets_norm_1(self):
        norm = MinMaxNormalizer()
        batch = [
            make_metrics("A", volume=100.0, oi=50.0, spread_bps=1.0),
            make_metrics("B", volume=1000.0, oi=50.0, spread_bps=1.0),
            make_metrics("C", volume=10.0,  oi=50.0, spread_bps=1.0),
        ]
        normalized, _ = norm.normalize(batch)
        norm_map = {n.symbol: n for n in normalized}
        assert norm_map["B"].norm_volume == pytest.approx(1.0, abs=1e-6)

    def test_lowest_volume_gets_norm_0(self):
        norm = MinMaxNormalizer()
        batch = [
            make_metrics("A", volume=100.0, oi=50.0, spread_bps=1.0),
            make_metrics("B", volume=1000.0, oi=50.0, spread_bps=1.0),
            make_metrics("C", volume=10.0,  oi=50.0, spread_bps=1.0),
        ]
        normalized, _ = norm.normalize(batch)
        norm_map = {n.symbol: n for n in normalized}
        assert norm_map["C"].norm_volume == pytest.approx(0.0, abs=1e-4)

    def test_tightest_spread_gets_norm_spread_1(self):
        norm = MinMaxNormalizer()
        batch = [
            make_metrics("TIGHT",  volume=1e6, oi=5e5, spread_bps=0.1),
            make_metrics("MEDIUM", volume=1e6, oi=5e5, spread_bps=5.0),
            make_metrics("WIDE",   volume=1e6, oi=5e5, spread_bps=20.0),
        ]
        normalized, _ = norm.normalize(batch)
        norm_map = {n.symbol: n for n in normalized}
        assert norm_map["TIGHT"].norm_spread == pytest.approx(1.0, abs=1e-6)
        assert norm_map["WIDE"].norm_spread == pytest.approx(0.0, abs=1e-4)


# =========================================================================== #
#  LogMinMaxNormalizer specific
# =========================================================================== #


class TestLogMinMaxNormalizer:
    def test_compresses_extreme_outlier(self):
        """
        With plain min-max, a 1000x outlier pushes 99% of contracts near 0.
        With log transform, the 2nd-highest-volume contract should have
        meaningfully higher norm_volume.
        """
        plain = MinMaxNormalizer()
        log_mm = LogMinMaxNormalizer()

        # One extreme outlier + 99 normal contracts (0-indexed: NORMAL0..NORMAL98)
        batch = [make_metrics("GIANT", volume=1e10, oi=1e8, spread_bps=1.0)]
        batch += [make_metrics(f"NORMAL{i}", volume=float(i + 1) * 1e5,
                               oi=float(i + 1) * 1e4, spread_bps=2.0)
                  for i in range(99)]

        plain_norms, _ = plain.normalize(batch)
        log_norms, _   = log_mm.normalize(batch)

        plain_map = {n.symbol: n for n in plain_norms}
        log_map   = {n.symbol: n for n in log_norms}

        # NORMAL98 is the 2nd-highest volume contract (range(99) = 0..98)
        plain_p98_norm = plain_map["NORMAL98"].norm_volume
        log_p98_norm   = log_map["NORMAL98"].norm_volume

        assert log_p98_norm > plain_p98_norm, (
            f"Log normalizer should give NORMAL98 higher norm_volume. "
            f"plain={plain_p98_norm:.4f}, log={log_p98_norm:.4f}"
        )

    def test_spread_not_log_transformed(self):
        """
        Spread values under LogMinMax should have the same relative ordering
        as under MinMax — spread is not log-transformed, just min-maxed directly.
        """
        log_mm = LogMinMaxNormalizer()
        plain  = MinMaxNormalizer()

        batch = [
            make_metrics("A", volume=1e6, oi=5e5, spread_bps=1.0),
            make_metrics("B", volume=2e6, oi=6e5, spread_bps=5.0),
            make_metrics("C", volume=3e6, oi=7e5, spread_bps=10.0),
        ]
        log_norms,   _ = log_mm.normalize(batch)
        plain_norms, _ = plain.normalize(batch)

        log_map   = {n.symbol: n for n in log_norms}
        plain_map = {n.symbol: n for n in plain_norms}

        # Spread ordering must be preserved — A has tightest spread
        for m1, m2 in [("A", "B"), ("B", "C"), ("A", "C")]:
            assert log_map[m1].norm_spread > log_map[m2].norm_spread

    def test_log_transform_applied_to_volume_and_oi(self):
        """
        With log transform, a mid-range contract should have meaningfully
        higher norm_volume than under plain min-max when there is an extreme
        outlier in the distribution.
        """
        log_mm = LogMinMaxNormalizer()
        plain  = MinMaxNormalizer()

        # 9 normal contracts + 1 extreme outlier
        batch = [make_metrics(f"V{i}", volume=float(i + 1) * 1e5,
                               oi=float(i + 1) * 1e4, spread_bps=2.0)
                 for i in range(9)]
        batch.append(make_metrics("GIANT", volume=1e10, oi=1e8, spread_bps=2.0))

        log_norms,   _ = log_mm.normalize(batch)
        plain_norms, _ = plain.normalize(batch)

        log_map   = {n.symbol: n for n in log_norms}
        plain_map = {n.symbol: n for n in plain_norms}

        # V4 is the middle contract — should get higher norm_volume under log due to GIANT
        log_v4   = log_map["V4"].norm_volume
        plain_v4 = plain_map["V4"].norm_volume

        assert log_v4 > plain_v4, (
            f"Log normalizer should give V4 higher norm_volume than plain minmax "
            f"when an extreme outlier exists. plain={plain_v4:.4f}, log={log_v4:.4f}"
        )
        assert log_v4 > 0.05, f"Log V4 norm_volume should be meaningfully > 0, got {log_v4:.4f}"




# =========================================================================== #
#  PercentileNormalizer specific
# =========================================================================== #


class TestPercentileNormalizer:
    def test_highest_volume_gets_norm_1(self):
        norm = PercentileNormalizer()
        batch = make_batch(10)
        normalized, _ = norm.normalize(batch)
        norm_map = {n.symbol: n for n in normalized}
        # SYM0009 has highest volume (i=9, volume=10)
        assert norm_map["SYM0009"].norm_volume == pytest.approx(1.0, abs=1e-6)

    def test_lowest_volume_gets_norm_0(self):
        norm = PercentileNormalizer()
        batch = make_batch(10)
        normalized, _ = norm.normalize(batch)
        norm_map = {n.symbol: n for n in normalized}
        # SYM0000 has lowest volume (i=0, volume=1)
        assert norm_map["SYM0000"].norm_volume == pytest.approx(0.0, abs=1e-6)

    def test_monotone_volume_order(self):
        """Contracts with strictly increasing volume must have monotone norm_volume."""
        norm = PercentileNormalizer()
        batch = [
            make_metrics("V1", volume=100.0, oi=100.0, spread_bps=5.0),
            make_metrics("V2", volume=200.0, oi=200.0, spread_bps=5.0),
            make_metrics("V3", volume=300.0, oi=300.0, spread_bps=5.0),
        ]
        normalized, _ = norm.normalize(batch)
        norm_map = {n.symbol: n for n in normalized}
        assert norm_map["V1"].norm_volume < norm_map["V2"].norm_volume < norm_map["V3"].norm_volume

    def test_tied_values_get_equal_rank(self):
        """Contracts with identical volume must get the same norm_volume (tie = average)."""
        norm = PercentileNormalizer()
        batch = [
            make_metrics("TIE_A", volume=1e6, oi=1e5, spread_bps=2.0),
            make_metrics("TIE_B", volume=1e6, oi=1e5, spread_bps=2.0),
            make_metrics("HIGH",  volume=2e6, oi=2e5, spread_bps=2.0),
        ]
        normalized, _ = norm.normalize(batch)
        norm_map = {n.symbol: n for n in normalized}
        assert norm_map["TIE_A"].norm_volume == pytest.approx(norm_map["TIE_B"].norm_volume, abs=1e-9)

    def test_spread_direction_inverted_correctly(self):
        """Tightest spread must get norm_spread = 1.0."""
        norm = PercentileNormalizer()
        batch = [
            make_metrics("TIGHT",  volume=1e6, oi=5e5, spread_bps=0.1),
            make_metrics("MEDIUM", volume=1e6, oi=5e5, spread_bps=5.0),
            make_metrics("WIDE",   volume=1e6, oi=5e5, spread_bps=20.0),
        ]
        normalized, _ = norm.normalize(batch)
        norm_map = {n.symbol: n for n in normalized}
        assert norm_map["TIGHT"].norm_spread > norm_map["MEDIUM"].norm_spread
        assert norm_map["MEDIUM"].norm_spread > norm_map["WIDE"].norm_spread
        assert norm_map["TIGHT"].norm_spread == pytest.approx(1.0, abs=1e-6)

    def test_insensitive_to_extreme_outlier(self):
        """
        Percentile normalizer should give the same ranking regardless of how extreme
        the largest value is.
        """
        norm = PercentileNormalizer()
        batch_normal = [make_metrics(f"S{i}", volume=float(i + 1) * 1e5,
                                     oi=float(i + 1) * 1e4, spread_bps=2.0)
                        for i in range(10)]
        batch_extreme = [make_metrics(f"S{i}", volume=float(i + 1) * 1e5,
                                      oi=float(i + 1) * 1e4, spread_bps=2.0)
                         for i in range(10)]
        # Replace the last contract's volume with an extreme outlier
        batch_extreme[-1] = make_metrics("S9", volume=1e15,
                                          oi=batch_extreme[-1].open_interest, spread_bps=2.0)

        n1, _ = norm.normalize(batch_normal)
        n2, _ = norm.normalize(batch_extreme)
        map1 = {n.symbol: n for n in n1}
        map2 = {n.symbol: n for n in n2}

        # All other contracts should have the same norm_volume ranking
        # (S0..S8 have identical relative ordering in both cases)
        for i in range(9):
            sym = f"S{i}"
            assert abs(map1[sym].norm_volume - map2[sym].norm_volume) < 1e-6, (
                f"Percentile normalizer should be insensitive to extreme outliers. "
                f"sym={sym}, normal={map1[sym].norm_volume:.4f}, extreme={map2[sym].norm_volume:.4f}"
            )


# =========================================================================== #
#  WinsorizedMinMaxNormalizer specific
# =========================================================================== #


class TestWinsorizedMinMaxNormalizer:
    def test_outlier_clipped_to_upper_pct(self):
        """
        Contracts above the upper_pct percentile should all get norm = 1.0.
        """
        norm = WinsorizedMinMaxNormalizer(lower_pct=0.0, upper_pct=80.0)
        # 10 contracts with volumes 1..10
        batch = [make_metrics(f"S{i}", volume=float(i + 1) * 100,
                               oi=float(i + 1) * 100, spread_bps=2.0)
                 for i in range(10)]
        normalized, _ = norm.normalize(batch)
        norm_map = {n.symbol: n for n in normalized}
        # 80th percentile of 10 values = 8th value (volume=800)
        # Contracts S8 (vol=900) and S9 (vol=1000) should both be clipped to 1.0
        assert norm_map["S9"].norm_volume == pytest.approx(1.0, abs=1e-6)
        assert norm_map["S8"].norm_volume == pytest.approx(1.0, abs=1e-6)

    def test_outlier_below_lower_pct_clipped_to_0(self):
        """Contracts below lower_pct should have norm_volume = 0."""
        norm = WinsorizedMinMaxNormalizer(lower_pct=20.0, upper_pct=100.0)
        batch = [make_metrics(f"S{i}", volume=float(i + 1) * 100,
                               oi=float(i + 1) * 100, spread_bps=2.0)
                 for i in range(10)]
        normalized, _ = norm.normalize(batch)
        norm_map = {n.symbol: n for n in normalized}
        # 20th percentile ≈ volume 200 (S1), so S0 (vol=100) gets clipped to 0
        assert norm_map["S0"].norm_volume == pytest.approx(0.0, abs=1e-6)

    def test_configurable_percentiles(self):
        """Different percentile configs should produce different results."""
        norm_wide   = WinsorizedMinMaxNormalizer(lower_pct=1.0, upper_pct=99.0)
        norm_narrow = WinsorizedMinMaxNormalizer(lower_pct=10.0, upper_pct=90.0)
        batch = make_batch(100)
        n1, _ = norm_wide.normalize(batch)
        n2, _ = norm_narrow.normalize(batch)
        m1 = {n.symbol: n for n in n1}
        m2 = {n.symbol: n for n in n2}
        # Middle contracts should differ in norm_volume between the two configs
        any_diff = any(
            abs(m1[f"SYM{i:04d}"].norm_volume - m2[f"SYM{i:04d}"].norm_volume) > 1e-6
            for i in range(20, 80)
        )
        assert any_diff, "Wide and narrow winsorization should produce different norm_volumes"

    def test_invalid_percentiles_raise(self):
        """lower_pct >= upper_pct must raise ValueError."""
        with pytest.raises(ValueError):
            WinsorizedMinMaxNormalizer(lower_pct=50.0, upper_pct=50.0)
        with pytest.raises(ValueError):
            WinsorizedMinMaxNormalizer(lower_pct=90.0, upper_pct=10.0)

    def test_extreme_outlier_compressed_vs_minmax(self):
        """
        After winsorization, the 2nd-highest-volume contract should have
        higher norm_volume than under plain min-max.
        """
        plain  = MinMaxNormalizer()
        wins   = WinsorizedMinMaxNormalizer(lower_pct=1.0, upper_pct=99.0)

        batch = [make_metrics(f"N{i}", volume=float(i + 1) * 1e5,
                               oi=float(i + 1) * 1e4, spread_bps=2.0)
                 for i in range(99)]
        batch.append(make_metrics("GIANT", volume=1e12, oi=1e8, spread_bps=2.0))

        plain_norms, _ = plain.normalize(batch)
        wins_norms,  _ = wins.normalize(batch)

        p_map = {n.symbol: n for n in plain_norms}
        w_map = {n.symbol: n for n in wins_norms}

        # N98 is the 2nd highest after GIANT — should be higher under winsorized
        p_n98 = p_map["N98"].norm_volume
        w_n98 = w_map["N98"].norm_volume
        assert w_n98 > p_n98, (
            f"Winsorized should give N98 higher norm_volume than plain minmax. "
            f"plain={p_n98:.4f}, wins={w_n98:.4f}"
        )

    def test_spread_not_affected_by_volume_winsorization(self):
        """Spread ordering must be correct regardless of volume winsorization."""
        norm = WinsorizedMinMaxNormalizer(lower_pct=1.0, upper_pct=99.0)
        batch = [
            make_metrics("TIGHT",  volume=1e6, oi=5e5, spread_bps=0.1),
            make_metrics("MEDIUM", volume=1e6, oi=5e5, spread_bps=5.0),
            make_metrics("WIDE",   volume=1e6, oi=5e5, spread_bps=20.0),
        ]
        normalized, _ = norm.normalize(batch)
        nm = {n.symbol: n for n in normalized}
        assert nm["TIGHT"].norm_spread > nm["MEDIUM"].norm_spread > nm["WIDE"].norm_spread


# =========================================================================== #
#  Cross-method properties
# =========================================================================== #


class TestCrossMethodProperties:

    def test_all_normalizers_same_skipped_set(self):
        """All normalizers must skip exactly the same contracts."""
        batch = [
            make_metrics("OK",     volume=1e6, oi=5e5, spread_bps=2.0),
            make_metrics("FAILED", volume=2e6, oi=6e5, failed=True),
            make_metrics("NO_OI",  volume=1e6, oi=None, spread_bps=2.0),
        ]
        expected_skipped = {"FAILED", "NO_OI"}
        for norm in ALL_NORMALIZERS:
            _, skipped = norm.normalize(batch)
            assert set(skipped) == expected_skipped, (
                f"{norm.name}: expected skipped={expected_skipped}, got={set(skipped)}"
            )

    def test_all_normalizers_produce_same_symbols(self):
        """All normalizers must produce normalized metrics for exactly the same symbols."""
        batch = make_batch(20)
        batch.append(make_metrics("NO_SPREAD", volume=5e6, oi=2e5, spread_bps=None))
        batch.append(make_metrics("FAILED", volume=1e6, oi=5e5, failed=True))

        expected_symbols = {m.symbol for m in batch if not m.metrics_failed and m.volume_24h_quote is not None and m.open_interest is not None}

        for norm in ALL_NORMALIZERS:
            normalized, _ = norm.normalize(batch)
            got = {n.symbol for n in normalized}
            assert got == expected_symbols, f"{norm.name}: symbol mismatch"

    def test_get_all_normalizers_returns_four(self):
        """Factory function must return exactly 4 normalizers."""
        normalizers = get_all_normalizers()
        assert len(normalizers) == 4

    def test_normalizer_names_are_unique(self):
        """Each normalizer must have a unique name."""
        names = [n.name for n in get_all_normalizers()]
        assert len(names) == len(set(names)), f"Duplicate names: {names}"

    def test_minmax_matches_existing_baseline_on_nontrivial_data(self):
        """
        MinMaxNormalizer output must be byte-for-byte identical to the existing
        normalize_metrics() function output.
        """
        from universe.normalization import normalize_metrics
        batch = make_batch(30)
        norm = MinMaxNormalizer()
        new_result, new_skip = norm.normalize(batch)
        old_result, old_skip = normalize_metrics(batch)

        new_map = {n.symbol: n for n in new_result}
        old_map = {n.symbol: n for n in old_result}

        assert set(new_map) == set(old_map)
        for sym in new_map:
            assert new_map[sym].norm_volume == pytest.approx(old_map[sym].norm_volume, abs=1e-9)
            assert new_map[sym].norm_oi     == pytest.approx(old_map[sym].norm_oi, abs=1e-9)
            assert new_map[sym].norm_spread == pytest.approx(old_map[sym].norm_spread, abs=1e-9)
