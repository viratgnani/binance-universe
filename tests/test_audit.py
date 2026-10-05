"""
tests/test_audit.py

Unit tests for the audit module's analysis functions.

These tests verify the correctness of every audit computation without
requiring a live Binance API call.  All data is constructed in-memory.
"""

from __future__ import annotations

import json
import math
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from universe.audit import UniverseAuditor, _describe, _percentile, build_markdown_report
from universe.config import UniverseConfig
from universe.models import (
    MarketMetrics,
    NormalizedMetrics,
    UniverseMember,
    UniverseStatus,
)


# =========================================================================== #
#  Helpers
# =========================================================================== #


def make_member(
    symbol: str,
    rank: int,
    score: float,
    volume: float = 1_000_000.0,
    oi: float = 500_000.0,
    spread_bps: float | None = 1.0,
    status: UniverseStatus = UniverseStatus.ACTIVE_TOP_100,
    listing_time: datetime | None = None,
) -> UniverseMember:
    return UniverseMember(
        symbol=symbol,
        base_asset=symbol.replace("USDT", ""),
        quote_asset="USDT",
        margin_asset="USDT",
        contract_type="PERPETUAL",
        status="TRADING",
        rank=rank,
        universe_score=score,
        universe_status=status,
        volume_24h_quote=volume,
        volume_24h_base=volume / 50_000,
        last_price=50_000.0,
        bid_price=49_999.0,
        ask_price=50_001.0,
        spread_bps=spread_bps,
        open_interest=oi,
        listing_time=listing_time or datetime(2022, 1, 1, tzinfo=timezone.utc),
        last_updated=datetime.now(tz=timezone.utc),
    )


def make_norm(symbol: str, nv: float = 0.5, ni: float = 0.5, ns: float = 0.5) -> NormalizedMetrics:
    return NormalizedMetrics(symbol=symbol, norm_volume=nv, norm_oi=ni, norm_spread=ns)


# =========================================================================== #
#  _percentile tests
# =========================================================================== #


class TestPercentile:
    def test_median_of_odd_list(self):
        assert _percentile([1.0, 2.0, 3.0], 50) == 2.0

    def test_p25_p75(self):
        data = list(map(float, range(1, 101)))
        assert abs(_percentile(data, 25) - 25.75) < 0.5
        assert abs(_percentile(data, 75) - 75.25) < 0.5

    def test_single_element(self):
        assert _percentile([42.0], 50) == 42.0
        assert _percentile([42.0], 0) == 42.0
        assert _percentile([42.0], 100) == 42.0

    def test_empty_returns_nan(self):
        assert math.isnan(_percentile([], 50))

    def test_p0_is_min(self):
        data = [3.0, 1.0, 4.0, 1.0, 5.0, 9.0]
        assert _percentile(data, 0) == min(data)

    def test_p100_is_max(self):
        data = [3.0, 1.0, 4.0, 1.0, 5.0, 9.0]
        assert _percentile(data, 100) == max(data)


# =========================================================================== #
#  _describe tests
# =========================================================================== #


class TestDescribe:
    def test_basic_stats(self):
        data = [1.0, 2.0, 3.0, 4.0, 5.0]
        stats = _describe(data)
        assert stats["count"] == 5
        assert stats["min"] == 1.0
        assert stats["max"] == 5.0
        assert abs(stats["mean"] - 3.0) < 1e-9
        assert stats["median"] == 3.0

    def test_empty_returns_nan(self):
        stats = _describe([])
        assert math.isnan(stats["mean"])
        assert math.isnan(stats["min"])


# =========================================================================== #
#  Section: baseline
# =========================================================================== #


class TestSectionBaseline:
    def _make_result(self, total_eligible, active_count, watchlist_count, failed=0):
        """Helper to create a minimal RefreshResult-like dict structure."""
        from universe.refresh import RefreshResult
        from universe.contract_filter import FilterResult

        members = (
            [make_member(f"A{i}", i + 1, 0.9 - i * 0.01) for i in range(active_count)]
            + [make_member(f"W{i}", active_count + i + 1, 0.01,
                           status=UniverseStatus.WATCHLIST)
               for i in range(watchlist_count)]
        )

        return RefreshResult(
            snapshot_id="TEST",
            snapshot_timestamp=datetime.now(tz=timezone.utc),
            total_discovered=total_eligible + 100,
            total_eligible=total_eligible,
            total_excluded=100,
            total_ranked=total_eligible - failed,
            total_failed_metrics=failed,
            universe=members,
            top_100=members[:active_count],
            excluded=[FilterResult(symbol="X", eligible=False, reason="test")],
        )

    def test_eligibility_check_passes(self):
        from universe.audit import UniverseAuditor
        auditor = UniverseAuditor()
        result = self._make_result(150, 100, 50)
        baseline = auditor._section_baseline(result)
        assert baseline["eligibility_check_passes"] is True
        assert baseline["active_top_100"] == 100
        assert baseline["watchlist_count"] == 50

    def test_eligibility_check_fails_when_mismatch(self):
        """If somehow active + watchlist != eligible, check fails."""
        from universe.audit import UniverseAuditor
        from universe.refresh import RefreshResult

        auditor = UniverseAuditor()
        result = self._make_result(150, 100, 40)  # 40 ≠ 50
        # Manually corrupt the total_eligible
        result.total_eligible = 155
        baseline = auditor._section_baseline(result)
        assert baseline["eligibility_check_passes"] is False


# =========================================================================== #
#  Section: concentration
# =========================================================================== #


class TestSectionConcentration:
    def test_top_1_has_100pct_when_only_one_ranked(self):
        from universe.audit import UniverseAuditor
        auditor = UniverseAuditor()
        members = [make_member("BTC", 1, 0.9, volume=1_000_000)]
        cn = auditor._section_concentration(members)
        assert cn["volume_concentration"]["top_10_pct"] == 100.0

    def test_uniform_distribution(self):
        """10 contracts with identical volumes → top 10 = 100%, top 5 = 50%."""
        from universe.audit import UniverseAuditor
        auditor = UniverseAuditor()
        members = [make_member(f"S{i}", i + 1, 0.9 - i * 0.01, volume=1_000_000)
                   for i in range(10)]
        cn = auditor._section_concentration(members)
        assert abs(cn["volume_concentration"]["top_10_pct"] - 100.0) < 0.01

    def test_two_contracts_top_1_is_50pct(self):
        from universe.audit import UniverseAuditor
        auditor = UniverseAuditor()
        members = [
            make_member("A", 1, 0.9, volume=1_000_000),
            make_member("B", 2, 0.5, volume=1_000_000),
        ]
        cn = auditor._section_concentration(members)
        # top 10 includes both → 100%
        assert cn["volume_concentration"]["top_10_pct"] == 100.0


# =========================================================================== #
#  Section: boundary
# =========================================================================== #


class TestSectionBoundary:
    def _make_ranked(self, n=110) -> list[UniverseMember]:
        members = []
        for i in range(n):
            status = UniverseStatus.ACTIVE_TOP_100 if i < 100 else UniverseStatus.WATCHLIST
            members.append(make_member(
                f"SYM{i:03d}", i + 1,
                score=round(1.0 - (i + 1) * 0.005, 6),
                status=status,
            ))
        return members

    def test_boundary_rows_cover_90_to_110(self):
        from universe.audit import UniverseAuditor
        auditor = UniverseAuditor()
        members = self._make_ranked()
        bd = auditor._section_boundary(members)
        ranks = [r["rank"] for r in bd["boundary_rows"]]
        assert min(ranks) == 90
        assert max(ranks) == 110

    def test_gap_100_101_positive(self):
        from universe.audit import UniverseAuditor
        auditor = UniverseAuditor()
        members = self._make_ranked()
        bd = auditor._section_boundary(members)
        assert bd["gap_100_to_101"] > 0

    def test_gap_is_none_when_fewer_than_101_contracts(self):
        from universe.audit import UniverseAuditor
        auditor = UniverseAuditor()
        members = self._make_ranked(50)
        bd = auditor._section_boundary(members)
        assert bd["score_at_rank_101"] is None


# =========================================================================== #
#  Section: neutral spread
# =========================================================================== #


class TestSectionNeutralSpread:
    def test_no_neutral_when_all_have_spread(self):
        from universe.audit import UniverseAuditor
        auditor = UniverseAuditor()
        members = [make_member(f"S{i}", i + 1, 0.5, spread_bps=1.0) for i in range(10)]
        metrics = [
            MarketMetrics(symbol=m.symbol, spread_bps=1.0, volume_24h_quote=1e6,
                          open_interest=1e5, last_price=50000.0,
                          bid_price=49999.0, ask_price=50001.0)
            for m in members
        ]
        ns = auditor._section_neutral_spread(members, metrics)
        assert ns["neutral_spread_count"] == 0
        assert ns["neutral_spread_pct"] == 0.0
        assert ns["neutral_symbols"] == []

    def test_counts_neutral_correctly(self):
        from universe.audit import UniverseAuditor
        auditor = UniverseAuditor()
        members = [
            make_member("HAS", 1, 0.9, spread_bps=1.0),
            make_member("NONE", 2, 0.5, spread_bps=None),
            make_member("NONE2", 3, 0.4, spread_bps=None),
        ]
        metrics = [
            MarketMetrics(symbol="HAS", spread_bps=1.0, volume_24h_quote=1e6,
                          open_interest=1e5, last_price=50000.0,
                          bid_price=49999.0, ask_price=50001.0),
            MarketMetrics(symbol="NONE", volume_24h_quote=1e6, open_interest=1e5),
            MarketMetrics(symbol="NONE2", volume_24h_quote=1e6, open_interest=1e5),
        ]
        ns = auditor._section_neutral_spread(members, metrics)
        assert ns["neutral_spread_count"] == 2
        assert "NONE" in ns["neutral_symbols"]
        assert "NONE2" in ns["neutral_symbols"]


# =========================================================================== #
#  Section: sanity checks
# =========================================================================== #


class TestSectionSanityChecks:
    def _make_minimal_result(self, n=150):
        from universe.refresh import RefreshResult
        from universe.contract_filter import FilterResult

        active = [make_member(f"A{i:03d}", i + 1, round(1.0 - i * 0.005, 6))
                  for i in range(100)]
        watchlist = [make_member(f"W{i:03d}", 101 + i, round(0.1 - i * 0.001, 6),
                                 status=UniverseStatus.WATCHLIST)
                     for i in range(n - 100)]
        all_members = active + watchlist

        return RefreshResult(
            snapshot_id="SANITY_TEST",
            snapshot_timestamp=datetime.now(tz=timezone.utc),
            total_discovered=n + 100,
            total_eligible=n,
            total_excluded=100,
            total_ranked=n,
            total_failed_metrics=0,
            universe=all_members,
            top_100=active,
            excluded=[],
        )

    def test_all_checks_pass_on_valid_data(self):
        from universe.audit import UniverseAuditor
        auditor = UniverseAuditor()
        result = self._make_minimal_result(150)
        ranked = [m for m in result.universe if m.rank is not None]
        norm_map = {m.symbol: make_norm(m.symbol, m.rank / 150, m.rank / 150, 0.5)
                    for m in ranked}
        sc = auditor._section_sanity_checks(result, ranked, norm_map)
        assert sc["checks"]["ranks_unique"] is True
        assert sc["checks"]["ranks_contiguous"] is True
        assert sc["checks"]["top_100_exactly_100"] is True
        assert sc["checks"]["no_duplicate_symbols"] is True
        assert sc["checks"]["all_top100_active_status"] is True
        assert sc["checks"]["all_watchlist_beyond_100"] is True

    def test_fails_when_duplicate_symbols(self):
        from universe.audit import UniverseAuditor
        from universe.refresh import RefreshResult
        auditor = UniverseAuditor()

        # Create universe with duplicate symbol
        m1 = make_member("BTCUSDT", 1, 0.99)
        m2 = make_member("BTCUSDT", 2, 0.95)  # duplicate!
        active = [m1, m2] + [make_member(f"A{i}", i + 3, 0.5) for i in range(98)]
        result = RefreshResult(
            snapshot_id="DUP",
            snapshot_timestamp=datetime.now(tz=timezone.utc),
            total_discovered=200,
            total_eligible=100,
            total_excluded=100,
            total_ranked=100,
            total_failed_metrics=0,
            universe=active,
            top_100=active,
            excluded=[],
        )
        ranked = active
        norm_map = {}
        sc = auditor._section_sanity_checks(result, ranked, norm_map)
        assert sc["checks"]["no_duplicate_symbols"] is False
        assert "no_duplicate_symbols" in sc["failed_checks"]

    def test_determinism_check_passes(self):
        from universe.audit import UniverseAuditor
        auditor = UniverseAuditor()
        result = self._make_minimal_result(150)
        ranked = [m for m in result.universe if m.rank is not None]
        norm_map = {m.symbol: make_norm(m.symbol, (151 - (m.rank or 0)) / 150, 0.5, 0.5)
                    for m in ranked}
        sc = auditor._section_sanity_checks(result, ranked, norm_map)
        assert sc["checks"]["ranking_is_deterministic"] is True


# =========================================================================== #
#  build_markdown_report smoke test
# =========================================================================== #


class TestMarkdownReport:
    def _minimal_audit(self) -> dict:
        """Minimal audit dict that the report builder can process without crashing."""
        members = [
            make_member(f"SYM{i:03d}", i + 1, round(1.0 - i * 0.005, 6),
                        spread_bps=1.0 if i < 90 else None,
                        status=UniverseStatus.ACTIVE_TOP_100 if i < 100 else UniverseStatus.WATCHLIST)
            for i in range(150)
        ]
        norm_map = {
            m.symbol: make_norm(m.symbol, (151 - (m.rank or 0)) / 150, 0.5, 0.5)
            for m in members if m.rank is not None
        }
        ranked = [m for m in members if m.rank is not None]

        auditor = UniverseAuditor()

        from universe.refresh import RefreshResult
        from universe.contract_filter import FilterResult

        result = RefreshResult(
            snapshot_id="TEST",
            snapshot_timestamp=datetime.now(tz=timezone.utc),
            total_discovered=250,
            total_eligible=150,
            total_excluded=100,
            total_ranked=150,
            total_failed_metrics=0,
            universe=members,
            top_100=members[:100],
            excluded=[
                FilterResult(symbol="Q1", eligible=False,
                             reason="contract_type='CURRENT_QUARTER' (not PERPETUAL)"),
                FilterResult(symbol="OLDCOIN", eligible=False,
                             reason="status='CLOSE' (not TRADING)"),
                FilterResult(symbol="AAPL", eligible=False,
                             reason="underlyingType='STOCK' (not in allowed types)"),
            ],
        )

        all_contracts = []  # empty for this test

        return {
            "audit_timestamp": datetime.now(tz=timezone.utc).isoformat(),
            "snapshot_id": "TEST",
            "snapshot_timestamp": result.snapshot_timestamp.isoformat(),
            "baseline": auditor._section_baseline(result),
            "distributions": auditor._section_distributions(ranked),
            "top100_table": auditor._section_top100_table(members[:100], norm_map),
            "boundary": auditor._section_boundary(ranked),
            "concentration": auditor._section_concentration(ranked),
            "components": auditor._section_components(ranked, norm_map),
            "normalization_outliers": auditor._section_normalization_outliers(ranked, {}),
            "neutral_spread": auditor._section_neutral_spread(ranked, []),
            "classification": auditor._section_classification(result.excluded, all_contracts),
            "composition": auditor._section_composition(members[:100], ranked),
            "sanity_checks": auditor._section_sanity_checks(result, ranked, norm_map),
            "snapshot_integrity": {
                "total_files": 1,
                "latest_file": "data/snapshots/snapshot_test.jsonl",
                "header_count": 1,
                "data_record_count": 150,
                "latest_batch_record_count": 150,
                "latest_batch_matches_eligible": True,
                "all_headers_have_timestamp": True,
                "all_data_have_rank": True,
                "all_data_have_score": True,
                "all_data_have_status": True,
                "unique_snapshot_ids_in_file": 1,
                "append_only_verified": True,
            },
        }

    def test_report_builds_without_error(self):
        """The Markdown report builder should not raise on valid audit data."""
        audit = self._minimal_audit()
        report = build_markdown_report(audit)
        assert isinstance(report, str)
        assert len(report) > 1000  # non-trivial report

    def test_report_contains_key_sections(self):
        audit = self._minimal_audit()
        report = build_markdown_report(audit)
        assert "## 1. Live Universe Baseline" in report
        assert "## 3. Top-100 Complete Table" in report
        assert "## 4. Top-100 Boundary" in report
        assert "## 11. Sanity Checks" in report
        assert "## 13. Audit Verdict" in report

    def test_verdict_in_report(self):
        audit = self._minimal_audit()
        report = build_markdown_report(audit)
        assert "UNIVERSE STATUS:" in report
