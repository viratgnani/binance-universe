# Binance Perpetual Universe — V1.1 Normalization

## Summary

Universe V1.1 uses **Log + MinMax normalization** for 24h quote volume and
open interest.  Spread uses its existing directional normalization (unchanged).

---

## Why Log Normalization

Crypto perpetual volume and open interest are heavily right-skewed.  Under V1
(plain min-max), two extreme observations — BTCUSDT and ETHUSDT — compressed
the entire rest of the universe:

| Metric | V1 (plain min-max) | V1.1 (log + min-max) |
| --- | --- | --- |
| Contracts with `norm_volume < 0.10` | **98.7%** | **17.4%** |
| Contracts with `norm_oi < 0.10`     | **98.7%** | **0.5%** |
| Spread dominance of mean score      | **94.5%** | **25.0%** |
| Volume contribution to mean score   | 3.4%      | 28.9%    |
| OI contribution to mean score       | 2.2%      | 46.1%    |

With plain min-max, spread became the de-facto ranking criterion for 98% of the
universe — not because spread was the most important signal, but because the
other two features had no effective information content.  The ranking weights
(volume 50%, OI 35%, spread 15%) were therefore not reflected in practice.

### The Fix

```text
x' = log(1 + x)
```

Applied to **24h quote volume** and **open interest** before min-max scaling.
This compresses the extreme upper tail without discarding the signal or
eliminating the relative ordering of contracts.  The transformation is:

- **Monotone** — rank ordering is preserved
- **Invertible** — original values can be recovered
- **Interpretable** — well-understood in quantitative finance for fat-tailed data
- **Deterministic** — same input always produces same output

Spread is **NOT** log-transformed.  Its dynamic range is already manageable and
the existing directional normalization (lower spread = better) is correct.

---

## Transformation Detail

| Metric | V1 transformation | V1.1 transformation |
| --- | --- | --- |
| `volume_24h_quote` | `(v - min) / (max - min)` | `(log(1+v) - log(1+min)) / (log(1+max) - log(1+min))` |
| `open_interest`    | `(v - min) / (max - min)` | `(log(1+v) - log(1+min)) / (log(1+max) - log(1+min))` |
| `spread_bps`       | `1 - (v - min) / (max - min)` | `1 - (v - min) / (max - min)` (unchanged) |

Missing spread: `norm_spread = 0.5` (neutral, unchanged from V1).

---

## Alternatives Evaluated and Rejected

The following methods were evaluated during the V1.1 experiment (2026-08-31)
using the same frozen 397-contract snapshot:

| Method | Why Rejected |
| --- | --- |
| **Percentile / rank normalization** | BTC ranked #100, ETH ranked #82. Loses all magnitude information — treats $10B volume as marginally different from $2.5B because both are near the top of the rank distribution. Semantically indefensible for a market-quality universe. |
| **Winsorized min-max (p1–p99)** | Only 4pp compression reduction (98.7% → 94.7%). Spread still dominated at 77.9% of mean score. Does not solve the identified problem. |

---

## Configuration

The active normalization method is configured in `universe/config.py`:

```python
NORMALIZATION_METHOD: str = "log_minmax"
```

Valid values (must match `NormalizerBase.name`):

| Value | Class | Status |
| --- | --- | --- |
| `"minmax"` | `MinMaxNormalizer` | V1 baseline |
| `"log_minmax"` | `LogMinMaxNormalizer` | **V1.1 production** |
| `"percentile"` | `PercentileNormalizer` | Evaluated, rejected |
| `"winsorized_p1_p99"` | `WinsorizedMinMaxNormalizer` | Evaluated, rejected |

---

## Production Pipeline

```
Binance
   |
contract discovery       /fapi/v1/exchangeInfo
   |
eligibility filtering    PERPETUAL + TRADING + USDT + crypto-only
   |
market metrics           bulk ticker + OI + book ticker
   |
LogMinMax normalization  log1p(volume, OI) + min-max; spread unchanged
   |
ranking                  score = 0.50 * norm_vol + 0.35 * norm_oi + 0.15 * norm_spr
   |
Top 100                  ACTIVE_TOP_100 (rank 1-100) / WATCHLIST (101-397)
   |
snapshot                 append-only JSONL
```

---

## Live V1.1 Validation Results

Collected: 2026-08-31T18:36:10Z

```
Total discovered   : 883
Eligible contracts : 397
Excluded           : 486
Successfully ranked: 397
Metric failures    : 0
ACTIVE_TOP_100     : 100
WATCHLIST          : 297
```

### Distribution Compression (Confirmed Fixed)

| Metric | V1 < 0.10 | V1.1 < 0.10 |
| --- | --- | --- |
| Volume | 98.7% | 17.4% |
| OI     | 98.7% | 0.5%  |

### Feature Contribution (Confirmed Balanced)

| Component | V1 | V1.1 |
| --- | --- | --- |
| Volume | 3.4% | 28.9% |
| OI     | 2.2% | 46.1% |
| Spread | 94.5% | 25.0% |

### Comparison vs V1 (Live Universe)

| Tier | Overlap |
| --- | --- |
| Top-100 | 74/100 (74%) |
| Top-50  | 31/50  (62%) |
| Top-20  | 11/20  (55%) |
| Top-10  | 6/10   (60%) |

Spearman rank correlation vs V1: **0.8587**

The moderate divergence is expected and reflects the normalization improvement.
Contracts that ranked highly in V1 primarily because of tight spread may now
rank lower due to balanced feature contributions.

### Top 20 (Live V1.1)

| Rank | Symbol | Score | Vol | OI | Spread bps |
| --- | --- | --- | --- | --- | --- |
| 1 | 1000PEPEUSDT | 0.77042 | $0.28B | 18,327,689,699 | 0.2797 |
| 2 | ETHUSDT | 0.76424 | $9.95B | 2,382,318 | 0.0405 |
| 3 | XRPUSDT | 0.75338 | $1.20B | 308,276,045 | 0.7222 |
| 4 | PUMPUSDT | 0.75187 | $0.27B | 22,783,465,303 | 2.2457 |
| 5 | SKRUSDT | 0.74535 | $1.16B | 695,619,779 | 2.9044 |
| 6 | DOGEUSDT | 0.74419 | $0.45B | 2,653,281,820 | 1.1996 |
| 7 | SOLUSDT | 0.71155 | $2.45B | 8,350,959 | 0.9620 |
| 8 | BTCUSDT | 0.70685 | $11.29B | 107,329 | 0.0127 |
| 9 | ZORAUSDT | 0.69442 | $0.34B | 729,346,731 | 2.1099 |
| 10 | SUIUSDT | 0.64984 | $0.25B | 121,285,395 | 1.3742 |

---

## Freeze Notice

V1.1 normalization is **frozen** as of 2026-09-01.

Future ranking changes require a new controlled experiment using the same
methodology (same frozen snapshot, all candidates evaluated on identical data,
evidence-based recommendation).

Do not change `NORMALIZATION_METHOD` without a corresponding experiment.
