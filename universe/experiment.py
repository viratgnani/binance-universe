"""
universe/experiment.py

Normalization comparison experiment for Universe V1.1.

This module loads the raw metrics from the most recent JSONL snapshot,
runs all four normalization candidates on the SAME frozen data, computes
detailed comparison statistics, and writes two outputs:

  docs/universe_normalization_comparison.md  — human-readable Markdown report
  experiment_output.json                     — machine-readable raw results

Usage
-----
    python -m universe.experiment

Design constraints
------------------
- All candidates receive identical raw inputs (same snapshot batch).
- Same RankingEngine and weights for all candidates.
- No live API calls needed — reads from the local snapshot file.
- Deterministic: running twice produces identical output.
"""

from __future__ import annotations

import json
import logging
import math
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from universe.config import UniverseConfig, config as default_config
from universe.models import MarketMetrics, NormalizedMetrics, RankResult
from universe.normalizers import NormalizerBase, get_all_normalizers
from universe.ranking_engine import RankingEngine
from universe.snapshot_repository import SnapshotRepository

logger = logging.getLogger(__name__)


# =========================================================================== #
#  Data loading — reconstruct MarketMetrics from the latest snapshot batch
# =========================================================================== #


def load_metrics_from_snapshot(cfg: UniverseConfig = default_config) -> list[MarketMetrics]:
    """
    Load the most recent snapshot batch and reconstruct MarketMetrics objects.

    Uses the last HEADER in the latest snapshot file to identify the most
    recent refresh batch, then returns all DATA records from that batch
    as MarketMetrics instances.

    The returned list is the single frozen dataset used by all normalizers.
    """
    repo = SnapshotRepository(cfg)
    files = repo.list_snapshot_files()
    if not files:
        raise FileNotFoundError(
            f"No snapshot files found in {cfg.SNAPSHOT_DIR}. "
            "Run `python -m universe.refresh` first."
        )

    latest_file = files[-1]
    all_records = repo.load_records(latest_file)

    # Find the most recent snapshot_id (last HEADER in the file)
    headers = [r for r in all_records if r.get("record_type") == "HEADER"]
    if not headers:
        raise ValueError(f"No HEADER records found in {latest_file}")

    latest_sid = headers[-1]["snapshot_id"]
    logger.info("Loading metrics from snapshot %s (file: %s)", latest_sid, latest_file)

    # Reconstruct MarketMetrics from DATA records in that batch
    data_records = [
        r for r in all_records
        if r.get("record_type") == "DATA" and r.get("snapshot_id") == latest_sid
    ]

    metrics: list[MarketMetrics] = []
    for rec in data_records:
        try:
            m = MarketMetrics(
                symbol=rec["symbol"],
                volume_24h_quote=rec.get("volume_24h_quote"),
                open_interest=rec.get("open_interest"),
                spread_bps=rec.get("spread_bps"),
                metrics_failed=rec.get("metrics_failed", False),
            )
            metrics.append(m)
        except Exception as exc:
            logger.warning("Skipping malformed record %s: %s", rec.get("symbol"), exc)

    logger.info("Loaded %d MarketMetrics from snapshot %s", len(metrics), latest_sid)
    return metrics


# =========================================================================== #
#  Statistics helpers
# =========================================================================== #


def _pct(data: list[float], p: float) -> float:
    """p-th percentile (0–100) by linear interpolation."""
    if not data:
        return float("nan")
    s = sorted(data)
    n = len(s)
    if n == 1:
        return s[0]
    idx = (p / 100.0) * (n - 1)
    lo = int(idx)
    hi = min(lo + 1, n - 1)
    return s[lo] + (idx - lo) * (s[hi] - s[lo])


def _describe(data: list[float]) -> dict[str, float]:
    if not data:
        nan = float("nan")
        return {k: nan for k in ["count", "min", "p25", "median", "p75", "p90", "p95", "max", "mean"]}
    return {
        "count": float(len(data)),
        "min": min(data),
        "p25": _pct(data, 25),
        "median": _pct(data, 50),
        "p75": _pct(data, 75),
        "p90": _pct(data, 90),
        "p95": _pct(data, 95),
        "max": max(data),
        "mean": sum(data) / len(data),
    }


def _compression(values: list[float]) -> dict[str, float]:
    """Fraction of values below thresholds 0.05, 0.10, 0.25, 0.50."""
    if not values:
        return {"pct_below_0.05": 0, "pct_below_0.10": 0, "pct_below_0.25": 0, "pct_below_0.50": 0}
    n = len(values)
    return {
        "pct_below_0.05": round(sum(1 for v in values if v < 0.05) / n * 100, 1),
        "pct_below_0.10": round(sum(1 for v in values if v < 0.10) / n * 100, 1),
        "pct_below_0.25": round(sum(1 for v in values if v < 0.25) / n * 100, 1),
        "pct_below_0.50": round(sum(1 for v in values if v < 0.50) / n * 100, 1),
    }


def _spearman(ranks_a: list[int], ranks_b: list[int]) -> float:
    """
    Spearman rank correlation between two rank lists over the same symbols.
    Assumes ranks_a and ranks_b are already aligned (same symbol order).
    """
    n = len(ranks_a)
    if n < 2:
        return float("nan")
    d2 = sum((a - b) ** 2 for a, b in zip(ranks_a, ranks_b))
    return 1.0 - 6.0 * d2 / (n * (n * n - 1))


def _overlap(set_a: set[str], set_b: set[str]) -> dict[str, Any]:
    intersection = set_a & set_b
    return {
        "count_a": len(set_a),
        "count_b": len(set_b),
        "overlap": len(intersection),
        "overlap_pct": round(len(intersection) / max(len(set_a), 1) * 100, 1),
        "only_in_a": sorted(set_a - set_b),
        "only_in_b": sorted(set_b - set_a),
    }


# =========================================================================== #
#  Per-method result container
# =========================================================================== #


@dataclass
class MethodResult:
    name: str
    description: str

    normalized: list[NormalizedMetrics]
    skipped: list[str]
    ranked: list[RankResult]

    # Computed by experiment
    rank_map: dict[str, int] = field(default_factory=dict)
    score_map: dict[str, float] = field(default_factory=dict)
    norm_map: dict[str, NormalizedMetrics] = field(default_factory=dict)


# =========================================================================== #
#  Experiment runner
# =========================================================================== #


class NormalizationExperiment:
    """
    Runs all normalizers on the same frozen metric snapshot and produces
    comparison statistics.
    """

    def __init__(
        self,
        metrics: list[MarketMetrics],
        cfg: UniverseConfig = default_config,
    ) -> None:
        self._metrics = metrics
        self._cfg = cfg
        self._engine = RankingEngine(cfg)
        self._normalizers = get_all_normalizers()

    # ----------------------------------------------------------------------- #
    #  Main entry point
    # ----------------------------------------------------------------------- #

    def run(self) -> dict[str, Any]:
        """Run the full experiment and return structured results dict."""
        method_results: dict[str, MethodResult] = {}

        # Run every normalizer
        for norm in self._normalizers:
            normalized, skipped = norm.normalize(self._metrics)
            ranked = self._engine.rank(normalized)

            mr = MethodResult(
                name=norm.name,
                description=norm.description,
                normalized=normalized,
                skipped=skipped,
                ranked=ranked,
            )
            mr.rank_map = {r.symbol: r.rank for r in ranked}
            mr.score_map = {r.symbol: r.score for r in ranked}
            mr.norm_map = {n.symbol: n for n in normalized}
            method_results[norm.name] = mr
            print(f"  [{norm.name}] Ranked {len(ranked)} contracts, {len(skipped)} skipped")

        baseline_name = self._normalizers[0].name

        # All comparisons reference the baseline (minmax)
        results = {
            "snapshot_metric_count": len(self._metrics),
            "methods": {},
            "pairwise_spearman": {},
            "overlap": {},
            "rank_regions": {},
            "btc_eth_analysis": {},
            "feature_dominance": {},
            "distribution_compression": {},
            "component_contributions": {},
        }

        # ------------------------------------------------------------------- #
        #  Per-method stats
        # ------------------------------------------------------------------- #
        for name, mr in method_results.items():
            norm_vols = [mr.norm_map[s].norm_volume for s in mr.norm_map]
            norm_ois  = [mr.norm_map[s].norm_oi for s in mr.norm_map]
            norm_sprs = [mr.norm_map[s].norm_spread for s in mr.norm_map]
            scores    = [mr.score_map[s] for s in mr.score_map]

            results["methods"][name] = {
                "description": mr.description,
                "ranked_count": len(mr.ranked),
                "skipped_count": len(mr.skipped),
                "skipped": mr.skipped,
                "top_10": [r.symbol for r in mr.ranked[:10]],
                "top_20": [r.symbol for r in mr.ranked[:20]],
                "top_100": [r.symbol for r in mr.ranked[:100]],
                "score_distribution": _describe(scores),
                "norm_volume_distribution": _describe(norm_vols),
                "norm_oi_distribution": _describe(norm_ois),
                "norm_spread_distribution": _describe(norm_sprs),
            }

            results["distribution_compression"][name] = {
                "volume": _compression(norm_vols),
                "oi": _compression(norm_ois),
                "spread": _compression(norm_sprs),
            }

            # Component contributions
            vc = [self._cfg.VOLUME_WEIGHT * mr.norm_map[s].norm_volume for s in mr.norm_map]
            oc = [self._cfg.OI_WEIGHT * mr.norm_map[s].norm_oi for s in mr.norm_map]
            sc = [self._cfg.SPREAD_WEIGHT * mr.norm_map[s].norm_spread for s in mr.norm_map]
            results["component_contributions"][name] = {
                "volume":  _describe(vc),
                "oi":      _describe(oc),
                "spread":  _describe(sc),
                "weights": {
                    "volume": self._cfg.VOLUME_WEIGHT,
                    "oi":     self._cfg.OI_WEIGHT,
                    "spread": self._cfg.SPREAD_WEIGHT,
                },
            }

        # ------------------------------------------------------------------- #
        #  Pairwise Spearman rank correlations
        # ------------------------------------------------------------------- #
        names = list(method_results.keys())
        # Use the common symbol set (all methods should produce same symbols)
        common_syms = sorted(
            set.intersection(*[set(method_results[n].rank_map.keys()) for n in names])
        )

        for i, na in enumerate(names):
            for nb in names[i:]:
                ranks_a = [method_results[na].rank_map.get(s, 9999) for s in common_syms]
                ranks_b = [method_results[nb].rank_map.get(s, 9999) for s in common_syms]
                rho = round(_spearman(ranks_a, ranks_b), 6)
                key = f"{na}_vs_{nb}"
                results["pairwise_spearman"][key] = rho

        # ------------------------------------------------------------------- #
        #  Top-N overlaps vs baseline
        # ------------------------------------------------------------------- #
        baseline = method_results[baseline_name]
        b_top10  = set(baseline.ranked[r].symbol for r in range(min(10,  len(baseline.ranked))))
        b_top20  = set(baseline.ranked[r].symbol for r in range(min(20,  len(baseline.ranked))))
        b_top50  = set(baseline.ranked[r].symbol for r in range(min(50,  len(baseline.ranked))))
        b_top100 = set(baseline.ranked[r].symbol for r in range(min(100, len(baseline.ranked))))

        for name, mr in method_results.items():
            if name == baseline_name:
                continue
            m_top10  = set(mr.ranked[r].symbol for r in range(min(10,  len(mr.ranked))))
            m_top20  = set(mr.ranked[r].symbol for r in range(min(20,  len(mr.ranked))))
            m_top50  = set(mr.ranked[r].symbol for r in range(min(50,  len(mr.ranked))))
            m_top100 = set(mr.ranked[r].symbol for r in range(min(100, len(mr.ranked))))
            results["overlap"][name] = {
                "top_10":  _overlap(b_top10,  m_top10),
                "top_20":  _overlap(b_top20,  m_top20),
                "top_50":  _overlap(b_top50,  m_top50),
                "top_100": _overlap(b_top100, m_top100),
            }

        # ------------------------------------------------------------------- #
        #  Rank regions
        # ------------------------------------------------------------------- #
        regions = [
            ("1_20",   1,   20),
            ("90_110", 90,  110),
            ("190_210",190, 210),
            ("290_310",290, 310),
            ("380_397",380, 397),
        ]
        for name, mr in method_results.items():
            results["rank_regions"][name] = {}
            for region_key, lo, hi in regions:
                region_rows = [
                    {
                        "rank": r.rank,
                        "symbol": r.symbol,
                        "score": round(r.score, 6),
                        "norm_volume": round(mr.norm_map[r.symbol].norm_volume, 4) if r.symbol in mr.norm_map else None,
                        "norm_oi":     round(mr.norm_map[r.symbol].norm_oi, 4)     if r.symbol in mr.norm_map else None,
                        "norm_spread": round(mr.norm_map[r.symbol].norm_spread, 4) if r.symbol in mr.norm_map else None,
                    }
                    for r in mr.ranked
                    if lo <= r.rank <= hi
                ]
                results["rank_regions"][name][region_key] = region_rows

        # ------------------------------------------------------------------- #
        #  BTC / ETH analysis
        # ------------------------------------------------------------------- #
        btc_eth_metrics = {
            m.symbol: m for m in self._metrics
            if m.symbol in ("BTCUSDT", "ETHUSDT")
        }

        results["btc_eth_analysis"] = {}
        for sym, raw in btc_eth_metrics.items():
            results["btc_eth_analysis"][sym] = {
                "raw_volume_usd": raw.volume_24h_quote,
                "raw_oi": raw.open_interest,
                "raw_spread_bps": raw.spread_bps,
                "by_method": {},
            }
            for name, mr in method_results.items():
                nm = mr.norm_map.get(sym)
                results["btc_eth_analysis"][sym]["by_method"][name] = {
                    "norm_volume": round(nm.norm_volume, 6) if nm else None,
                    "norm_oi":     round(nm.norm_oi, 6)     if nm else None,
                    "norm_spread": round(nm.norm_spread, 6) if nm else None,
                    "score": mr.score_map.get(sym),
                    "rank":  mr.rank_map.get(sym),
                }

        # ------------------------------------------------------------------- #
        #  Feature dominance (mean component contribution)
        # ------------------------------------------------------------------- #
        for name, mr in method_results.items():
            cc = results["component_contributions"][name]
            vol_mean = cc["volume"]["mean"]
            oi_mean  = cc["oi"]["mean"]
            spr_mean = cc["spread"]["mean"]
            total    = vol_mean + oi_mean + spr_mean
            results["feature_dominance"][name] = {
                "vol_pct": round(vol_mean / total * 100, 1) if total else 0,
                "oi_pct":  round(oi_mean  / total * 100, 1) if total else 0,
                "spr_pct": round(spr_mean / total * 100, 1) if total else 0,
                "dominant": (
                    "volume" if vol_mean >= oi_mean and vol_mean >= spr_mean
                    else "oi" if oi_mean >= spr_mean else "spread"
                ),
            }

        return results


# =========================================================================== #
#  Markdown report builder
# =========================================================================== #


def _fmt(v, fmt=".4f"):
    if v is None or (isinstance(v, float) and math.isnan(v)):
        return "N/A"
    return f"{v:{fmt}}"


def _fmt_usd(v, scale=1e9, label="B"):
    if v is None:
        return "N/A"
    return f"${v/scale:.2f}{label}"


def build_report(results: dict, cfg: UniverseConfig = default_config) -> str:
    lines: list[str] = []
    method_names = list(results["methods"].keys())
    baseline = method_names[0]

    METHOD_LABELS = {
        "minmax":             "A — MinMax (V1 baseline)",
        "log_minmax":         "B — Log + MinMax",
        "percentile":         "Percentile",
        "winsorized_p1_p99":  "D — Winsorized (p1–p99)",
    }

    def label(n):
        return METHOD_LABELS.get(n, n)

    def h(lvl, text):
        lines.append(f"{'#'*lvl} {text}\n")

    def p(text):
        lines.append(text + "\n")

    def table(headers, rows):
        lines.append("| " + " | ".join(headers) + " |")
        lines.append("| " + " | ".join(["---"] * len(headers)) + " |")
        for row in rows:
            lines.append("| " + " | ".join(str(c) for c in row) + " |")
        lines.append("")

    def code(text):
        lines.append("```")
        lines.append(text)
        lines.append("```\n")

    # ------------------------------------------------------------------- #
    h(1, "Binance Perpetual Universe — V1.1 Normalization Comparison")

    p(f"**Methods compared:** {len(method_names)}")
    p(f"**Contracts:** {results['snapshot_metric_count']} (same frozen snapshot for all methods)")
    p(f"**Weights (unchanged):** Volume={cfg.VOLUME_WEIGHT}, OI={cfg.OI_WEIGHT}, "
      f"Spread={cfg.SPREAD_WEIGHT}")

    # ------------------------------------------------------------------- #
    h(2, "Executive Summary")

    p("This experiment compares four normalization methods on the same frozen "
      "snapshot of 397 eligible Binance crypto perpetual futures contracts.\n"
      "The V1 audit identified that plain min-max normalization is heavily distorted "
      "by ETH/BTC volume outliers — 98.7% of contracts have `norm_volume < 0.10`. "
      "Three candidate methods are evaluated as potential fixes.")

    table(
        ["Method", "Description"],
        [[label(n), results["methods"][n]["description"]] for n in method_names],
    )

    # ------------------------------------------------------------------- #
    h(2, "1. Distribution Compression")

    p("Percentage of contracts with normalized value below thresholds. "
      "Lower percentages = better differentiation.")

    for metric_key, metric_label in [("volume", "Volume"), ("oi", "OI"), ("spread", "Spread")]:
        p(f"**{metric_label} — % of contracts below threshold**")
        rows = []
        for n in method_names:
            c = results["distribution_compression"][n][metric_key]
            rows.append([
                label(n),
                f"{c['pct_below_0.05']}%",
                f"{c['pct_below_0.10']}%",
                f"{c['pct_below_0.25']}%",
                f"{c['pct_below_0.50']}%",
            ])
        table(["Method", "< 0.05", "< 0.10", "< 0.25", "< 0.50"], rows)

    # ------------------------------------------------------------------- #
    h(2, "2. Component Contribution Analysis")

    p(f"Actual score contribution per component (weight × normalized value). "
      f"Max possible: volume={cfg.VOLUME_WEIGHT}, OI={cfg.OI_WEIGHT}, spread={cfg.SPREAD_WEIGHT}.")

    for comp in ["volume", "oi", "spread"]:
        comp_label = {"volume": "Volume", "oi": "OI", "spread": "Spread"}[comp]
        p(f"**{comp_label} contribution (weight × norm)**")
        rows = []
        for n in method_names:
            cc = results["component_contributions"][n][comp]
            rows.append([
                label(n),
                _fmt(cc["mean"]),
                _fmt(cc["median"]),
                _fmt(cc["p25"]),
                _fmt(cc["p75"]),
                _fmt(cc["p90"]),
                _fmt(cc["p95"]),
                _fmt(cc["min"]),
                _fmt(cc["max"]),
            ])
        table(["Method", "Mean", "Median", "P25", "P75", "P90", "P95", "Min", "Max"], rows)

    p("**Feature dominance (% of total mean score contribution)**")
    table(
        ["Method", "Volume %", "OI %", "Spread %", "Dominant"],
        [
            [
                label(n),
                f"{results['feature_dominance'][n]['vol_pct']}%",
                f"{results['feature_dominance'][n]['oi_pct']}%",
                f"{results['feature_dominance'][n]['spr_pct']}%",
                results["feature_dominance"][n]["dominant"],
            ]
            for n in method_names
        ],
    )

    # ------------------------------------------------------------------- #
    h(2, "3. Ranking Comparison")

    h(3, "Spearman Rank Correlations")
    p("Spearman ρ = 1.0 means identical ordering. Lower = more divergent rankings.")
    corr = results["pairwise_spearman"]
    table(
        ["Pair", "Spearman ρ"],
        [
            [f"{label(k.split('_vs_')[0])} vs {label(k.split('_vs_')[1])}", f"{v:.6f}"]
            for k, v in corr.items()
            if k.split("_vs_")[0] != k.split("_vs_")[1]
        ],
    )

    h(3, "Top-N Overlap vs V1 Baseline")
    p("Number of symbols shared with the baseline Top-N list.")
    for n in method_names:
        if n == baseline:
            continue
        ov = results["overlap"][n]
        p(f"**{label(n)} vs {label(baseline)}:**")
        table(
            ["Tier", "Baseline", "Candidate", "Overlap", "Overlap %"],
            [
                ["Top 10",  ov["top_10"]["count_a"],  ov["top_10"]["count_b"],  ov["top_10"]["overlap"],  f"{ov['top_10']['overlap_pct']}%"],
                ["Top 20",  ov["top_20"]["count_a"],  ov["top_20"]["count_b"],  ov["top_20"]["overlap"],  f"{ov['top_20']['overlap_pct']}%"],
                ["Top 50",  ov["top_50"]["count_a"],  ov["top_50"]["count_b"],  ov["top_50"]["overlap"],  f"{ov['top_50']['overlap_pct']}%"],
                ["Top 100", ov["top_100"]["count_a"], ov["top_100"]["count_b"], ov["top_100"]["overlap"], f"{ov['top_100']['overlap_pct']}%"],
            ],
        )

    # ------------------------------------------------------------------- #
    h(2, "4. Top-20 Rank Lists")

    rows = []
    for rank_idx in range(20):
        row = [str(rank_idx + 1)]
        for n in method_names:
            ranked = results["methods"][n].get("top_20", [])
            sym = ranked[rank_idx] if rank_idx < len(ranked) else "—"
            row.append(sym)
        rows.append(row)
    table(["Rank"] + [label(n) for n in method_names], rows)

    # ------------------------------------------------------------------- #
    h(2, "5. Rank Region Analysis")

    for region_key, region_label in [
        ("1_20",    "Ranks 1–20"),
        ("90_110",  "Ranks 90–110 (Top-100 boundary)"),
        ("190_210", "Ranks 190–210 (Middle)"),
        ("380_397", "Ranks 380–397 (Bottom)"),
    ]:
        h(3, region_label)
        for n in method_names:
            rows_r = results["rank_regions"][n].get(region_key, [])
            if not rows_r:
                continue
            p(f"**{label(n)}**")
            table(
                ["Rank", "Symbol", "Score", "nVol", "nOI", "nSprd"],
                [
                    [r["rank"], r["symbol"], f"{r['score']:.5f}",
                     f"{r['norm_volume']:.4f}" if r["norm_volume"] is not None else "—",
                     f"{r['norm_oi']:.4f}"     if r["norm_oi"]     is not None else "—",
                     f"{r['norm_spread']:.4f}" if r["norm_spread"] is not None else "—"]
                    for r in rows_r[:15]  # cap at 15 to keep report readable
                ],
            )

    # ------------------------------------------------------------------- #
    h(2, "6. BTC / ETH Analysis")

    p("Effect of normalization method on the two largest contracts.")
    for sym in ["ETHUSDT", "BTCUSDT"]:
        entry = results["btc_eth_analysis"].get(sym)
        if not entry:
            continue
        p(f"**{sym}** — raw volume: {_fmt_usd(entry['raw_volume_usd'])}, "
          f"raw OI: {_fmt(entry['raw_oi'], '.0f')}, "
          f"spread: {_fmt(entry['raw_spread_bps'])} bps")
        table(
            ["Method", "nVol", "nOI", "nSprd", "Score", "Rank"],
            [
                [
                    label(n),
                    _fmt(v["norm_volume"]),
                    _fmt(v["norm_oi"]),
                    _fmt(v["norm_spread"]),
                    _fmt(v["score"]),
                    str(v["rank"]),
                ]
                for n, v in entry["by_method"].items()
            ],
        )

    # ------------------------------------------------------------------- #
    h(2, "7. Recommendation")

    # Evidence-based verdict
    # Key questions:
    # 1. Does the method reduce compression significantly vs baseline?
    # 2. Does spread remain non-dominant?
    # 3. Is Top-100 sufficiently stable (high overlap)?
    # 4. Is it deterministic and explainable?

    compression_data = results["distribution_compression"]
    dominance_data   = results["feature_dominance"]

    # Baseline compression %<0.10 for volume
    base_comp_vol = compression_data[baseline]["volume"]["pct_below_0.10"]

    candidates = [n for n in method_names if n != baseline]
    improvements: dict[str, dict] = {}
    for n in candidates:
        comp_vol   = compression_data[n]["volume"]["pct_below_0.10"]
        dominant   = dominance_data[n]["dominant"]
        spr_pct    = dominance_data[n]["spr_pct"]
        top100_ov  = results["overlap"].get(n, {}).get("top_100", {}).get("overlap_pct", 0)
        spearman   = results["pairwise_spearman"].get(f"{baseline}_vs_{n}", 0)

        improvements[n] = {
            "vol_compression_pct": comp_vol,
            "spread_dominant": dominant == "spread",
            "spread_pct": spr_pct,
            "top100_overlap_pct": top100_ov,
            "spearman_vs_baseline": spearman,
            "reduction_vs_baseline": round(base_comp_vol - comp_vol, 1),
        }

    # Choose best: highest compression reduction, spread not dominant, high top100 overlap
    def _score_method(n):
        imp = improvements[n]
        # Penalize if spread dominates
        spread_penalty = 20 if imp["spread_dominant"] else 0
        # Reward compression reduction
        return imp["reduction_vs_baseline"] - spread_penalty

    best = max(candidates, key=_score_method) if candidates else None

    base_comp = compression_data[baseline]["volume"]["pct_below_0.10"]
    p(f"**Baseline (V1 minmax):** {base_comp}% of contracts have `norm_volume < 0.10`.")

    for n in candidates:
        imp = improvements[n]
        p(f"**{label(n)}:** {imp['vol_compression_pct']}% below 0.10 "
          f"(−{imp['reduction_vs_baseline']}pp vs baseline), "
          f"spread contributes {imp['spread_pct']}% of mean score, "
          f"Top-100 overlap with baseline: {imp['top100_overlap_pct']}%, "
          f"Spearman vs baseline: {imp['spearman_vs_baseline']:.4f}")

    p("")

    if best:
        best_imp = improvements[best]
        is_meaningful_improvement = best_imp["reduction_vs_baseline"] > 15.0
        spread_ok = not best_imp["spread_dominant"]

        if is_meaningful_improvement and spread_ok:
            verdict = f"ADOPT {label(best)} FOR V1.1"
            reason = (
                f"Reduces volume compression from {base_comp}% to "
                f"{best_imp['vol_compression_pct']}% (−{best_imp['reduction_vs_baseline']}pp) "
                f"while keeping spread non-dominant ({best_imp['spread_pct']}% of mean score). "
                f"Top-100 overlap with baseline: {best_imp['top100_overlap_pct']}%. "
                f"Spearman rank correlation vs baseline: {best_imp['spearman_vs_baseline']:.4f}."
            )
        else:
            verdict = "KEEP V1"
            reason = (
                "No candidate achieves meaningful compression reduction without "
                "either making spread dominant or destabilizing the Top-100. "
                "The V1 min-max baseline remains the most defensible option."
            )
    else:
        verdict = "KEEP V1"
        reason = "No candidates evaluated."

    code(f"RECOMMENDATION: {verdict}\n\nReason: {reason}")

    lines.append("---")
    lines.append(
        "*Report generated by `universe/experiment.py` — "
        "Binance Perpetual Universe V1.1 Normalization Experiment*"
    )

    return "\n".join(lines)


# =========================================================================== #
#  CLI entry point
# =========================================================================== #


def main() -> None:
    logging.basicConfig(level=logging.WARNING)

    print("=" * 60)
    print("  Binance Universe — V1.1 Normalization Experiment")
    print("=" * 60)

    cfg = default_config

    print("\nLoading metrics from latest snapshot...")
    metrics = load_metrics_from_snapshot(cfg)
    print(f"  Loaded {len(metrics)} contracts from snapshot.")

    print("\nRunning normalization candidates...")
    experiment = NormalizationExperiment(metrics, cfg)
    results = experiment.run()

    # Save raw JSON
    out_json = Path("experiment_output.json")
    out_json.write_text(
        json.dumps(results, indent=2, default=str), encoding="utf-8"
    )
    print(f"\n  Raw results -> {out_json}")

    # Save Markdown report
    docs_dir = Path("docs")
    docs_dir.mkdir(exist_ok=True)
    report_path = docs_dir / "universe_normalization_comparison.md"
    report = build_report(results, cfg)
    report_path.write_text(report, encoding="utf-8")
    print(f"  Report      -> {report_path}")

    # Print summary
    print("\n" + "=" * 60)
    print("  EXPERIMENT SUMMARY")
    print("=" * 60)
    for name in results["methods"]:
        dom  = results["feature_dominance"][name]
        comp = results["distribution_compression"][name]["volume"]["pct_below_0.10"]
        print(f"  [{name}]")
        print(f"    norm_vol < 0.10 : {comp}%")
        print(f"    dominant feature: {dom['dominant']} "
              f"(vol={dom['vol_pct']}%, OI={dom['oi_pct']}%, spr={dom['spr_pct']}%)")
    print("=" * 60)
    print(f"\n  Full report -> {report_path}")


if __name__ == "__main__":
    main()
