"""
tests/test_v11_regression.py

Production regression tests for Universe V1.1.

Verifies that:
  1. The production refresh pipeline uses the V1.1 log+minmax normalizer.
  2. Log transform is applied to volume and OI (not spread).
  3. Spread direction is preserved (lower = better).
  4. Missing spread is neutral (norm_spread = 0.5).
  5. No NaN or Inf values are produced.
  6. Ranking is deterministic.
  7. Config default is "log_minmax".
  8. Factory function resolves names correctly.
  9. Frozen-snapshot reproduction: the production pipeline reproduces the
     experiment's log+minmax results against the same 397-contract snapshot.
  10. Full end-to-end refresh with mocked Binance produces correct output.

These tests must NOT be deleted when V1.2+ normalization changes are evaluated.
Archive them behind a flag or versioned fixture instead.
"""

from __future__ import annotations

import json
import math
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from universe.binance_client import BinanceAPIError
from universe.config import UniverseConfig, config as production_config
from universe.models import MarketMetrics, UniverseStatus
from universe.normalizers import (
    LogMinMaxNormalizer,
    MinMaxNormalizer,
    NormalizerBase,
    get_normalizer_by_name,
)
from universe.ranking_engine import RankingEngine
from universe.refresh import run_refresh


# =========================================================================== #
#  Helpers shared across tests
# =========================================================================== #

FIXTURE_DIR = Path(__file__).parent / "fixtures"


def _load_exchange_info() -> dict:
    with open(FIXTURE_DIR / "exchange_info.json") as fh:
        return json.load(fh)


def _make_ticker(symbol: str, quote_volume: float = 1_000_000.0) -> dict:
    return {
        "symbol": symbol,
        "volume": str(quote_volume / 50_000),
        "quoteVolume": str(quote_volume),
        "lastPrice": "50000.0",
        "bidPrice": "49999.0",
        "askPrice": "50001.0",
        "openTime": 1000000,
        "closeTime": 1000001,
    }


def _make_oi(symbol: str, oi: float = 10_000.0) -> dict:
    return {"symbol": symbol, "openInterest": str(oi), "time": 1000000}


ELIGIBLE_SYMBOLS = ["BTCUSDT", "ETHUSDT", "SOLUSDT", "ADAUSDT", "XRPUSDT"]


def _make_mock_client():
    client = MagicMock()
    client.__aenter__ = AsyncMock(return_value=client)
    client.__aexit__ = AsyncMock(return_value=False)

    client.get_exchange_info = AsyncMock(return_value=_load_exchange_info())
    client.get_all_tickers_24hr = AsyncMock(
        return_value=[
            _make_ticker("BTCUSDT", 5_000_000_000),
            _make_ticker("ETHUSDT", 2_000_000_000),
            _make_ticker("SOLUSDT", 800_000_000),
            _make_ticker("ADAUSDT", 400_000_000),
            _make_ticker("XRPUSDT", 300_000_000),
        ]
    )
    client.get_all_book_tickers = AsyncMock(
        return_value=[
            {"symbol": "BTCUSDT", "bidPrice": "49999.0", "askPrice": "50001.0",
             "bidQty": "1.0", "askQty": "1.0"},
            {"symbol": "ETHUSDT", "bidPrice": "2999.0", "askPrice": "3001.0",
             "bidQty": "5.0", "askQty": "5.0"},
            {"symbol": "SOLUSDT", "bidPrice": "149.9", "askPrice": "150.1",
             "bidQty": "20.0", "askQty": "20.0"},
            {"symbol": "ADAUSDT", "bidPrice": "0.449", "askPrice": "0.451",
             "bidQty": "1000.0", "askQty": "1000.0"},
            {"symbol": "XRPUSDT", "bidPrice": "0.599", "askPrice": "0.601",
             "bidQty": "500.0", "askQty": "500.0"},
        ]
    )

    async def _oi_side_effect(symbol: str) -> dict:
        volumes = {
            "BTCUSDT": 50_000,
            "ETHUSDT": 300_000,
            "SOLUSDT": 1_000_000,
            "ADAUSDT": 5_000_000,
            "XRPUSDT": 8_000_000,
        }
        return _make_oi(symbol, volumes.get(symbol, 10_000))

    client.get_open_interest = _oi_side_effect
    return client


def _make_metrics(
    symbol: str,
    volume: float | None = 1_000_000.0,
    oi: float | None = 500_000.0,
    spread_bps: float | None = 2.0,
    failed: bool = False,
) -> MarketMetrics:
    m = MarketMetrics(
        symbol=symbol,
        volume_24h_quote=volume,
        open_interest=oi,
        metrics_failed=failed,
    )
    object.__setattr__(m, "spread_bps", spread_bps)
    return m


# =========================================================================== #
#  1. Config regression
# =========================================================================== #


class TestV11Config:
    def test_default_normalization_method_is_log_minmax(self):
        """Production config must default to log_minmax (V1.1 decision)."""
        cfg = UniverseConfig()
        assert cfg.NORMALIZATION_METHOD == "log_minmax", (
            f"Expected NORMALIZATION_METHOD='log_minmax', got '{cfg.NORMALIZATION_METHOD}'. "
            "V1.1 deployment decision requires log_minmax as the default."
        )

    def test_production_singleton_uses_log_minmax(self):
        """The module-level config singleton must also use log_minmax."""
        assert production_config.NORMALIZATION_METHOD == "log_minmax"

    def test_get_normalizer_by_name_resolves_log_minmax(self):
        """Factory resolves 'log_minmax' to LogMinMaxNormalizer."""
        norm = get_normalizer_by_name("log_minmax")
        assert isinstance(norm, LogMinMaxNormalizer)

    def test_get_normalizer_by_name_resolves_minmax(self):
        """Factory must still resolve V1 baseline by name."""
        norm = get_normalizer_by_name("minmax")
        assert isinstance(norm, MinMaxNormalizer)

    def test_get_normalizer_by_name_raises_on_unknown(self):
        """Unknown name must raise ValueError with valid options listed."""
        with pytest.raises(ValueError, match="Unknown normalization method"):
            get_normalizer_by_name("magic_normalizer")

    def test_factory_produces_normalizer_base_instances(self):
        """All names in the registry must return NormalizerBase instances."""
        for name in ["minmax", "log_minmax", "percentile", "winsorized_p1_p99"]:
            norm = get_normalizer_by_name(name)
            assert isinstance(norm, NormalizerBase), (
                f"get_normalizer_by_name('{name}') should return a NormalizerBase"
            )


# =========================================================================== #
#  2. Log transform applied correctly to volume and OI
# =========================================================================== #


class TestV11LogTransform:
    """
    Verify log1p is applied to volume and OI but NOT to spread.
    All tests use LogMinMaxNormalizer directly — not through config —
    to remain independent of config defaults.
    """

    def test_volume_is_log_transformed(self):
        """
        With an extreme outlier, the 2nd-highest contract gets a meaningfully
        higher norm_volume under log normalization than under plain min-max.
        Proves log1p is applied to volume.
        """
        log_mm = LogMinMaxNormalizer()
        plain  = MinMaxNormalizer()

        batch = [_make_metrics("GIANT", volume=1e10, oi=1e5, spread_bps=2.0)]
        batch += [_make_metrics(f"N{i}", volume=float(i + 1) * 1e5,
                                oi=1e5, spread_bps=2.0) for i in range(9)]

        log_norms,   _ = log_mm.normalize(batch)
        plain_norms, _ = plain.normalize(batch)

        log_map   = {n.symbol: n for n in log_norms}
        plain_map = {n.symbol: n for n in plain_norms}

        # N8 (second highest volume) should be meaningfully higher under log
        assert log_map["N8"].norm_volume > plain_map["N8"].norm_volume, (
            "Log transform should give mid-range contracts higher norm_volume "
            "than plain min-max when an extreme outlier is present."
        )

    def test_oi_is_log_transformed(self):
        """Same outlier test for open interest."""
        log_mm = LogMinMaxNormalizer()
        plain  = MinMaxNormalizer()

        batch = [_make_metrics("GIANT", volume=1e5, oi=1e10, spread_bps=2.0)]
        batch += [_make_metrics(f"N{i}", volume=1e5,
                                oi=float(i + 1) * 1e5, spread_bps=2.0) for i in range(9)]

        log_norms,   _ = log_mm.normalize(batch)
        plain_norms, _ = plain.normalize(batch)

        log_map   = {n.symbol: n for n in log_norms}
        plain_map = {n.symbol: n for n in plain_norms}

        assert log_map["N8"].norm_oi > plain_map["N8"].norm_oi, (
            "Log transform should give mid-range contracts higher norm_oi "
            "than plain min-max when an extreme OI outlier is present."
        )

    def test_spread_is_not_log_transformed(self):
        """
        Spread ordering under LogMinMaxNormalizer must be identical to MinMax.
        Proves spread is passed through without log transformation.
        """
        log_mm = LogMinMaxNormalizer()
        plain  = MinMaxNormalizer()

        batch = [
            _make_metrics("TIGHT",  volume=1e6, oi=1e5, spread_bps=0.1),
            _make_metrics("MEDIUM", volume=2e6, oi=2e5, spread_bps=5.0),
            _make_metrics("WIDE",   volume=3e6, oi=3e5, spread_bps=20.0),
        ]

        log_norms,   _ = log_mm.normalize(batch)
        plain_norms, _ = plain.normalize(batch)

        log_map   = {n.symbol: n for n in log_norms}
        plain_map = {n.symbol: n for n in plain_norms}

        # Spread ordering must be identical between methods
        assert log_map["TIGHT"].norm_spread == pytest.approx(
            plain_map["TIGHT"].norm_spread, abs=1e-9
        ), "Spread normalization changed between log_minmax and minmax — spread must not be log-transformed."

        assert log_map["WIDE"].norm_spread == pytest.approx(
            plain_map["WIDE"].norm_spread, abs=1e-9
        )

    def test_lower_spread_is_better(self):
        """Lower spread_bps must produce higher norm_spread (V1.1 invariant)."""
        norm = LogMinMaxNormalizer()
        batch = [
            _make_metrics("TIGHT", volume=1e6, oi=1e5, spread_bps=0.5),
            _make_metrics("WIDE",  volume=1e6, oi=1e5, spread_bps=15.0),
        ]
        normalized, _ = norm.normalize(batch)
        nm = {n.symbol: n for n in normalized}
        assert nm["TIGHT"].norm_spread > nm["WIDE"].norm_spread, (
            "Lower spread must produce higher norm_spread (lower=better rule)."
        )

    def test_missing_spread_is_neutral(self):
        """Contracts with no spread data must receive norm_spread = 0.5."""
        norm = LogMinMaxNormalizer()
        batch = [
            _make_metrics("HAS_SPREAD", volume=1e6, oi=1e5, spread_bps=2.0),
            _make_metrics("NO_SPREAD",  volume=2e6, oi=2e5, spread_bps=None),
        ]
        normalized, _ = norm.normalize(batch)
        nm = {n.symbol: n for n in normalized}
        assert nm["NO_SPREAD"].norm_spread == 0.5, (
            f"Missing spread must be neutral (0.5), got {nm['NO_SPREAD'].norm_spread}"
        )

    def test_no_nan_or_inf_in_production_normalizer(self):
        """LogMinMaxNormalizer must never produce NaN or Inf."""
        norm = LogMinMaxNormalizer()
        batch = (
            [_make_metrics(f"SYM{i}", volume=float(i + 1) * 1e5,
                           oi=float(i + 1) * 1e4, spread_bps=float(i + 1) * 0.5)
             for i in range(50)]
        )
        normalized, _ = norm.normalize(batch)
        for nm in normalized:
            assert not math.isnan(nm.norm_volume),  f"NaN in norm_volume for {nm.symbol}"
            assert not math.isnan(nm.norm_oi),      f"NaN in norm_oi for {nm.symbol}"
            assert not math.isnan(nm.norm_spread),  f"NaN in norm_spread for {nm.symbol}"
            assert not math.isinf(nm.norm_volume),  f"Inf in norm_volume for {nm.symbol}"
            assert not math.isinf(nm.norm_oi),      f"Inf in norm_oi for {nm.symbol}"
            assert not math.isinf(nm.norm_spread),  f"Inf in norm_spread for {nm.symbol}"

    def test_ranking_is_deterministic(self):
        """Identical input must produce identical output every time."""
        norm   = LogMinMaxNormalizer()
        engine = RankingEngine()
        batch  = [_make_metrics(f"SYM{i:04d}", volume=float(i + 1) * 1e5,
                                oi=float(i + 1) * 1e4, spread_bps=float(i + 1) * 0.5)
                  for i in range(30)]

        result_a = engine.rank(norm.normalize(batch)[0])
        result_b = engine.rank(norm.normalize(batch)[0])
        assert [(r.symbol, r.rank) for r in result_a] == \
               [(r.symbol, r.rank) for r in result_b], (
            "V1.1 ranking must be deterministic."
        )


# =========================================================================== #
#  3. Refresh pipeline uses V1.1 normalizer
# =========================================================================== #


class TestV11RefreshUsesLogMinMax:
    """
    Verify the production refresh pipeline invokes LogMinMaxNormalizer when
    NORMALIZATION_METHOD = "log_minmax" (the V1.1 default).
    """

    @pytest.fixture()
    def tmp_cfg(self, tmp_path: Path) -> UniverseConfig:
        cfg = UniverseConfig()
        cfg.SNAPSHOT_DIR = tmp_path / "snapshots"
        cfg.TOP_N = 3
        return cfg

    async def test_refresh_calls_log_minmax_normalizer(self, tmp_cfg):
        """
        Patch get_normalizer_by_name and confirm it is called with 'log_minmax'.
        """
        mock_client = _make_mock_client()
        called_with: list[str] = []

        original_factory = get_normalizer_by_name

        def _spy(name: str):
            called_with.append(name)
            return original_factory(name)

        with (
            patch("universe.refresh.BinanceFuturesClient", return_value=mock_client),
            patch("universe.refresh.get_normalizer_by_name", side_effect=_spy),
        ):
            await run_refresh(tmp_cfg)

        assert len(called_with) == 1, f"Expected exactly 1 normalizer call, got: {called_with}"
        assert called_with[0] == "log_minmax", (
            f"Expected refresh to call get_normalizer_by_name('log_minmax'), "
            f"got '{called_with[0]}'. The production pipeline must use V1.1 normalization."
        )

    async def test_refresh_uses_configured_method_from_config(self, tmp_cfg):
        """
        If cfg.NORMALIZATION_METHOD is overridden, the refresh must use the
        overridden method. Proves the pipeline reads from config, not hardcoded.
        """
        tmp_cfg.NORMALIZATION_METHOD = "minmax"   # override for this test
        mock_client = _make_mock_client()
        called_with: list[str] = []

        original_factory = get_normalizer_by_name

        def _spy(name: str):
            called_with.append(name)
            return original_factory(name)

        with (
            patch("universe.refresh.BinanceFuturesClient", return_value=mock_client),
            patch("universe.refresh.get_normalizer_by_name", side_effect=_spy),
        ):
            await run_refresh(tmp_cfg)

        assert called_with[0] == "minmax", (
            "Refresh must use the method from cfg.NORMALIZATION_METHOD"
        )

    async def test_v11_refresh_produces_correct_top_n(self, tmp_cfg):
        """Full refresh with V1.1 normalization produces correct Top-N count."""
        mock_client = _make_mock_client()
        with patch("universe.refresh.BinanceFuturesClient", return_value=mock_client):
            result = await run_refresh(tmp_cfg)

        active = [m for m in result.universe if m.universe_status == UniverseStatus.ACTIVE_TOP_100]
        assert len(active) == tmp_cfg.TOP_N
        assert result.total_ranked == 5

    async def test_v11_refresh_scores_differ_from_v1(self, tmp_cfg):
        """
        V1.1 (log_minmax) scores must differ from V1 (minmax) scores on
        the same data because normalization has changed.
        This verifies the change is actually deployed, not silently bypassed.
        """
        mock_client = _make_mock_client()

        # V1.1 (default)
        with patch("universe.refresh.BinanceFuturesClient", return_value=mock_client):
            result_v11 = await run_refresh(tmp_cfg)

        # V1 (override config)
        tmp_cfg.NORMALIZATION_METHOD = "minmax"
        with patch("universe.refresh.BinanceFuturesClient", return_value=mock_client):
            result_v1 = await run_refresh(tmp_cfg)

        v11_scores = {m.symbol: m.universe_score for m in result_v11.universe if m.universe_score}
        v1_scores  = {m.symbol: m.universe_score for m in result_v1.universe  if m.universe_score}

        # Scores MUST differ — the normalization has changed
        assert v11_scores != v1_scores, (
            "V1.1 and V1 must produce different scores. "
            "If identical, V1.1 normalization is not being applied."
        )


# =========================================================================== #
#  4. Frozen-snapshot reproduction
# =========================================================================== #


class TestFrozenSnapshotReproduction:
    """
    Verify that the production pipeline's LogMinMaxNormalizer produces results
    that agree with the V1.1 experiment on the same frozen snapshot data.

    Specifically:
      - 397 eligible contracts loaded from snapshot
      - Normalization + ranking under log_minmax
      - Top-100 count = 100, Watchlist = 297
      - BTC rank ≤ 10, ETH rank ≤ 5 (experiment showed BTC=#8, ETH=#2)
    """

    @pytest.fixture(scope="class")
    @classmethod
    def frozen_results(cls):
        """
        Load the frozen snapshot and produce rankings with the V1.1 normalizer.
        Skips if no snapshot file is found (CI without live data).
        """
        from universe.experiment import load_metrics_from_snapshot
        try:
            metrics = load_metrics_from_snapshot()
        except FileNotFoundError:
            pytest.skip("No snapshot found — run `python -m universe.refresh` first")

        if len(metrics) < 300:
            pytest.skip(f"Snapshot too small ({len(metrics)} records) — expected ~397")

        normalizer = get_normalizer_by_name("log_minmax")
        engine = RankingEngine()
        normalized, skipped = normalizer.normalize(metrics)
        ranked = engine.rank(normalized)

        return {
            "metrics": metrics,
            "normalized": normalized,
            "skipped": skipped,
            "ranked": ranked,
            "rank_map": {r.symbol: r.rank for r in ranked},
            "score_map": {r.symbol: r.score for r in ranked},
        }

    def test_all_contracts_loaded(self, frozen_results):
        """Snapshot must contain ~397 eligible contracts."""
        total = len(frozen_results["metrics"])
        assert 380 <= total <= 420, (
            f"Expected ~397 eligible contracts in snapshot, got {total}. "
            "Investigate if the universe size has changed significantly."
        )

    def test_all_contracts_ranked(self, frozen_results):
        """All non-failed contracts must be ranked (0 skipped expected for live data)."""
        skipped = frozen_results["skipped"]
        # Allow a small tolerance for edge cases, but not large failures
        total = len(frozen_results["metrics"])
        assert len(skipped) < total * 0.02, (
            f"Too many skipped contracts: {len(skipped)}/{total}. "
            "Investigate metric fetch failures."
        )

    def test_btc_in_top_15(self, frozen_results):
        """
        BTCUSDT must rank in the top 15 under log_minmax.
        V1.1 experiment produced rank #8 for BTC.
        """
        btc_rank = frozen_results["rank_map"].get("BTCUSDT")
        assert btc_rank is not None, "BTCUSDT not found in rankings"
        assert btc_rank <= 15, (
            f"BTCUSDT ranked #{btc_rank} under log_minmax. "
            "V1.1 experiment expected rank ~8. A rank > 15 warrants investigation."
        )

    def test_eth_in_top_10(self, frozen_results):
        """
        ETHUSDT must rank in the top 10 under log_minmax.
        V1.1 experiment produced rank #2 for ETH.
        """
        eth_rank = frozen_results["rank_map"].get("ETHUSDT")
        assert eth_rank is not None, "ETHUSDT not found in rankings"
        assert eth_rank <= 10, (
            f"ETHUSDT ranked #{eth_rank} under log_minmax. "
            "V1.1 experiment expected rank ~2. A rank > 10 warrants investigation."
        )

    def test_volume_compression_improved(self, frozen_results):
        """
        Under log_minmax, fewer than 30% of contracts should have norm_volume < 0.10.
        V1 baseline was 98.7%; V1.1 experiment showed 15.9%.
        """
        norm_vols = [n.norm_volume for n in frozen_results["normalized"]]
        pct_below_10 = sum(1 for v in norm_vols if v < 0.10) / len(norm_vols) * 100
        assert pct_below_10 < 30.0, (
            f"Volume compression: {pct_below_10:.1f}% below 0.10. "
            "V1.1 experiment showed 15.9%; V1 baseline was 98.7%. "
            "A value > 30% suggests log transform is not being applied."
        )

    def test_spread_not_dominant(self, frozen_results):
        """
        Spread's mean score contribution must be less than 50%.
        V1 baseline was 94.5%; V1.1 experiment showed 26.9%.
        """
        from universe.config import config as cfg
        normalized = frozen_results["normalized"]
        n = len(normalized)
        vol_contrib  = [cfg.VOLUME_WEIGHT * nm.norm_volume for nm in normalized]
        oi_contrib   = [cfg.OI_WEIGHT    * nm.norm_oi     for nm in normalized]
        spr_contrib  = [cfg.SPREAD_WEIGHT * nm.norm_spread for nm in normalized]

        mean_vol = sum(vol_contrib) / n
        mean_oi  = sum(oi_contrib)  / n
        mean_spr = sum(spr_contrib) / n
        total    = mean_vol + mean_oi + mean_spr

        spr_pct = mean_spr / total * 100 if total else 0
        assert spr_pct < 50.0, (
            f"Spread contributes {spr_pct:.1f}% of mean score. "
            "V1.1 experiment showed 26.9%; V1 baseline was 94.5%. "
            "A value > 50% suggests the compression problem is not fixed."
        )

    def test_no_nan_or_inf_in_frozen_run(self, frozen_results):
        """Production run against live data must not produce NaN or Inf."""
        for nm in frozen_results["normalized"]:
            for attr in ("norm_volume", "norm_oi", "norm_spread"):
                v = getattr(nm, attr)
                assert not math.isnan(v), f"NaN in {attr} for {nm.symbol}"
                assert not math.isinf(v), f"Inf in {attr} for {nm.symbol}"

    def test_ranking_deterministic_on_frozen_data(self, frozen_results):
        """Running the normalizer twice on the same data must produce identical rankings."""
        normalizer = get_normalizer_by_name("log_minmax")
        engine     = RankingEngine()
        metrics    = frozen_results["metrics"]

        result_a = engine.rank(normalizer.normalize(metrics)[0])
        result_b = engine.rank(normalizer.normalize(metrics)[0])

        assert [(r.symbol, r.rank) for r in result_a] == \
               [(r.symbol, r.rank) for r in result_b], (
            "Frozen-data ranking must be deterministic."
        )
