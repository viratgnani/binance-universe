# Binance Perpetual Universe — V1.1 Normalization Comparison

**Methods compared:** 4

**Contracts:** 397 (same frozen snapshot for all methods)

**Weights (unchanged):** Volume=0.5, OI=0.35, Spread=0.15

## Executive Summary

This experiment compares four normalization methods on the same frozen snapshot of 397 eligible Binance crypto perpetual futures contracts.
The V1 audit identified that plain min-max normalization is heavily distorted by ETH/BTC volume outliers — 98.7% of contracts have `norm_volume < 0.10`. Three candidate methods are evaluated as potential fixes.

| Method | Description |
| --- | --- |
| A — MinMax (V1 baseline) | V1 baseline: min-max normalization (existing behavior) |
| B — Log + MinMax | Log(1+x) transform on volume & OI, then min-max normalization |
| Percentile | Empirical percentile rank normalization (rank / (N-1)) |
| D — Winsorized (p1–p99) | Min-max after winsorizing to [1.0%, 99.0%] for volume & OI; spread unchanged |

## 1. Distribution Compression

Percentage of contracts with normalized value below thresholds. Lower percentages = better differentiation.

**Volume — % of contracts below threshold**

| Method | < 0.05 | < 0.10 | < 0.25 | < 0.50 |
| --- | --- | --- | --- | --- |
| A — MinMax (V1 baseline) | 98.5% | 98.7% | 99.5% | 99.5% |
| B — Log + MinMax | 4.0% | 15.9% | 63.7% | 91.9% |
| Percentile | 5.0% | 10.1% | 24.9% | 49.9% |
| D — Winsorized (p1–p99) | 91.7% | 94.7% | 97.7% | 98.5% |

**OI — % of contracts below threshold**

| Method | < 0.05 | < 0.10 | < 0.25 | < 0.50 |
| --- | --- | --- | --- | --- |
| A — MinMax (V1 baseline) | 98.0% | 98.7% | 99.2% | 99.7% |
| B — Log + MinMax | 0.5% | 0.5% | 3.8% | 34.5% |
| Percentile | 5.0% | 10.1% | 24.9% | 49.9% |
| D — Winsorized (p1–p99) | 90.9% | 92.7% | 97.0% | 98.0% |

**Spread — % of contracts below threshold**

| Method | < 0.05 | < 0.10 | < 0.25 | < 0.50 |
| --- | --- | --- | --- | --- |
| A — MinMax (V1 baseline) | 0.3% | 0.3% | 0.3% | 5.3% |
| B — Log + MinMax | 0.3% | 0.3% | 0.3% | 5.3% |
| Percentile | 5.0% | 10.1% | 24.9% | 49.9% |
| D — Winsorized (p1–p99) | 1.5% | 3.0% | 5.5% | 27.0% |

## 2. Component Contribution Analysis

Actual score contribution per component (weight × normalized value). Max possible: volume=0.5, OI=0.35, spread=0.15.

**Volume contribution (weight × norm)**

| Method | Mean | Median | P25 | P75 | P90 | P95 | Min | Max |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| A — MinMax (V1 baseline) | 0.0041 | 0.0001 | 0.0000 | 0.0005 | 0.0023 | 0.0059 | 0.0000 | 0.5000 |
| B — Log + MinMax | 0.1207 | 0.1004 | 0.0614 | 0.1582 | 0.2359 | 0.2827 | 0.0000 | 0.5000 |
| Percentile | 0.2500 | 0.2500 | 0.1250 | 0.3750 | 0.4500 | 0.4750 | 0.0000 | 0.5000 |
| D — Winsorized (p1–p99) | 0.0146 | 0.0011 | 0.0004 | 0.0039 | 0.0199 | 0.0521 | 0.0000 | 0.5000 |

**OI contribution (weight × norm)**

| Method | Mean | Median | P25 | P75 | P90 | P95 | Min | Max |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| A — MinMax (V1 baseline) | 0.0026 | 0.0002 | 0.0000 | 0.0006 | 0.0017 | 0.0071 | 0.0000 | 0.3500 |
| B — Log + MinMax | 0.1892 | 0.1916 | 0.1657 | 0.2190 | 0.2402 | 0.2694 | 0.0000 | 0.3500 |
| Percentile | 0.1750 | 0.1750 | 0.0875 | 0.2625 | 0.3150 | 0.3325 | 0.0000 | 0.3500 |
| D — Winsorized (p1–p99) | 0.0126 | 0.0014 | 0.0004 | 0.0053 | 0.0147 | 0.0608 | 0.0000 | 0.3500 |

**Spread contribution (weight × norm)**

| Method | Mean | Median | P25 | P75 | P90 | P95 | Min | Max |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| A — MinMax (V1 baseline) | 0.1139 | 0.1168 | 0.0989 | 0.1318 | 0.1415 | 0.1438 | 0.0000 | 0.1500 |
| B — Log + MinMax | 0.1139 | 0.1168 | 0.0989 | 0.1318 | 0.1415 | 0.1438 | 0.0000 | 0.1500 |
| Percentile | 0.0750 | 0.0750 | 0.0375 | 0.1125 | 0.1350 | 0.1425 | 0.0000 | 0.1500 |
| D — Winsorized (p1–p99) | 0.0959 | 0.0999 | 0.0729 | 0.1227 | 0.1374 | 0.1409 | 0.0000 | 0.1500 |

**Feature dominance (% of total mean score contribution)**

| Method | Volume % | OI % | Spread % | Dominant |
| --- | --- | --- | --- | --- |
| A — MinMax (V1 baseline) | 3.4% | 2.2% | 94.5% | spread |
| B — Log + MinMax | 28.5% | 44.6% | 26.9% | oi |
| Percentile | 50.0% | 35.0% | 15.0% | volume |
| D — Winsorized (p1–p99) | 11.9% | 10.2% | 77.9% | spread |

## 3. Ranking Comparison

### Spearman Rank Correlations

Spearman ρ = 1.0 means identical ordering. Lower = more divergent rankings.

| Pair | Spearman ρ |
| --- | --- |
| A — MinMax (V1 baseline) vs B — Log + MinMax | 0.673575 |
| A — MinMax (V1 baseline) vs Percentile | 0.636872 |
| A — MinMax (V1 baseline) vs D — Winsorized (p1–p99) | 0.941426 |
| B — Log + MinMax vs Percentile | 0.974422 |
| B — Log + MinMax vs D — Winsorized (p1–p99) | 0.759599 |
| Percentile vs D — Winsorized (p1–p99) | 0.705029 |

### Top-N Overlap vs V1 Baseline

Number of symbols shared with the baseline Top-N list.

**B — Log + MinMax vs A — MinMax (V1 baseline):**

| Tier | Baseline | Candidate | Overlap | Overlap % |
| --- | --- | --- | --- | --- |
| Top 10 | 10 | 10 | 6 | 60.0% |
| Top 20 | 20 | 20 | 11 | 55.0% |
| Top 50 | 50 | 50 | 29 | 58.0% |
| Top 100 | 100 | 100 | 65 | 65.0% |

**Percentile vs A — MinMax (V1 baseline):**

| Tier | Baseline | Candidate | Overlap | Overlap % |
| --- | --- | --- | --- | --- |
| Top 10 | 10 | 10 | 3 | 30.0% |
| Top 20 | 20 | 20 | 8 | 40.0% |
| Top 50 | 50 | 50 | 24 | 48.0% |
| Top 100 | 100 | 100 | 60 | 60.0% |

**D — Winsorized (p1–p99) vs A — MinMax (V1 baseline):**

| Tier | Baseline | Candidate | Overlap | Overlap % |
| --- | --- | --- | --- | --- |
| Top 10 | 10 | 10 | 9 | 90.0% |
| Top 20 | 20 | 20 | 15 | 75.0% |
| Top 50 | 50 | 50 | 34 | 68.0% |
| Top 100 | 100 | 100 | 84 | 84.0% |

## 4. Top-20 Rank Lists

| Rank | A — MinMax (V1 baseline) | B — Log + MinMax | Percentile | D — Winsorized (p1–p99) |
| --- | --- | --- | --- | --- |
| 1 | ETHUSDT | 1000PEPEUSDT | 1000PEPEUSDT | ETHUSDT |
| 2 | BTCUSDT | ETHUSDT | DOGEUSDT | BTCUSDT |
| 3 | 1000SATSUSDT | PUMPUSDT | PUMPUSDT | ZECUSDT |
| 4 | NEIROUSDT | XRPUSDT | PENGUUSDT | XRPUSDT |
| 5 | SOLUSDT | DOGEUSDT | XRPUSDT | SOLUSDT |
| 6 | ZECUSDT | SKRUSDT | 1000SHIBUSDT | 1000PEPEUSDT |
| 7 | XRPUSDT | SOLUSDT | ZORAUSDT | PUMPUSDT |
| 8 | 1000PEPEUSDT | BTCUSDT | SKRUSDT | SKRUSDT |
| 9 | PUMPUSDT | ZORAUSDT | ZKUSDT | NEIROUSDT |
| 10 | DOGSUSDT | 牛来USDT | NOTUSDT | 1000SATSUSDT |
| 11 | SKRUSDT | BTRUSDT | BOMEUSDT | DOGSUSDT |
| 12 | DOGEUSDT | SUIUSDT | AKEUSDT | DOGEUSDT |
| 13 | BOMEUSDT | PENGUUSDT | XPLUSDT | BOMEUSDT |
| 14 | BNBUSDT | ZKCUSDT | 1000BONKUSDT | HMSTRUSDT |
| 15 | PAXGUSDT | ZECUSDT | 龙虾USDT | 牛来USDT |
| 16 | XAUTUSDT | ADAUSDT | TRXUSDT | BNBUSDT |
| 17 | SUIUSDT | 1000SHIBUSDT | BLESSUSDT | NOTUSDT |
| 18 | PENGUUSDT | WLDUSDT | TUTUSDT | ZORAUSDT |
| 19 | TAOUSDT | TRUMPUSDT | COTIUSDT | TRUMPUSDT |
| 20 | TRXUSDT | NOTUSDT | BTRUSDT | SUIUSDT |

## 5. Rank Region Analysis

### Ranks 1–20

**A — MinMax (V1 baseline)**

| Rank | Symbol | Score | nVol | nOI | nSprd |
| --- | --- | --- | --- | --- | --- |
| 1 | ETHUSDT | 0.64979 | 1.0000 | 0.0000 | 0.9985 |
| 2 | BTCUSDT | 0.63146 | 0.9630 | 0.0000 | 0.9999 |
| 3 | 1000SATSUSDT | 0.43400 | 0.0001 | 1.0000 | 0.5596 |
| 4 | NEIROUSDT | 0.26874 | 0.0005 | 0.3625 | 0.9441 |
| 5 | SOLUSDT | 0.25955 | 0.2327 | 0.0001 | 0.9545 |
| 6 | ZECUSDT | 0.22625 | 0.1541 | 0.0000 | 0.9947 |
| 7 | XRPUSDT | 0.20176 | 0.1124 | 0.0019 | 0.9659 |
| 8 | 1000PEPEUSDT | 0.20104 | 0.0255 | 0.1149 | 0.9873 |
| 9 | PUMPUSDT | 0.19606 | 0.0251 | 0.1428 | 0.8902 |
| 10 | DOGSUSDT | 0.17580 | 0.0002 | 0.2777 | 0.5233 |
| 11 | SKRUSDT | 0.16815 | 0.0923 | 0.0042 | 0.8037 |
| 12 | DOGEUSDT | 0.16780 | 0.0412 | 0.0164 | 0.9432 |
| 13 | BOMEUSDT | 0.16528 | 0.0012 | 0.0637 | 0.9492 |
| 14 | BNBUSDT | 0.16206 | 0.0260 | 0.0000 | 0.9936 |
| 15 | PAXGUSDT | 0.15355 | 0.0073 | 0.0000 | 0.9994 |

**B — Log + MinMax**

| Rank | Symbol | Score | nVol | nOI | nSprd |
| --- | --- | --- | --- | --- | --- |
| 1 | 1000PEPEUSDT | 0.77346 | 0.6400 | 0.8724 | 0.9873 |
| 2 | ETHUSDT | 0.77040 | 1.0000 | 0.3446 | 0.9985 |
| 3 | PUMPUSDT | 0.76270 | 0.6387 | 0.8852 | 0.8902 |
| 4 | XRPUSDT | 0.75890 | 0.7856 | 0.6320 | 0.9659 |
| 5 | DOGEUSDT | 0.75023 | 0.6871 | 0.7577 | 0.9432 |
| 6 | SKRUSDT | 0.74073 | 0.7662 | 0.6773 | 0.8037 |
| 7 | SOLUSDT | 0.71837 | 0.8570 | 0.4192 | 0.9545 |
| 8 | BTCUSDT | 0.70481 | 0.9963 | 0.1619 | 0.9999 |
| 9 | ZORAUSDT | 0.68641 | 0.6411 | 0.6814 | 0.8489 |
| 10 | 牛来USDT | 0.67346 | 0.6765 | 0.5841 | 0.8719 |
| 11 | BTRUSDT | 0.65991 | 0.6355 | 0.6102 | 0.8572 |
| 12 | SUIUSDT | 0.65692 | 0.6289 | 0.5779 | 0.9347 |
| 13 | PENGUUSDT | 0.64846 | 0.4747 | 0.7691 | 0.9461 |
| 14 | ZKCUSDT | 0.64778 | 0.6273 | 0.5626 | 0.9147 |
| 15 | ZECUSDT | 0.64706 | 0.8165 | 0.2559 | 0.9947 |

**Percentile**

| Rank | Symbol | Score | nVol | nOI | nSprd |
| --- | --- | --- | --- | --- | --- |
| 1 | 1000PEPEUSDT | 0.97992 | 0.9722 | 0.9899 | 0.9823 |
| 2 | DOGEUSDT | 0.95694 | 0.9848 | 0.9419 | 0.8990 |
| 3 | PUMPUSDT | 0.94849 | 0.9697 | 0.9924 | 0.7753 |
| 4 | PENGUUSDT | 0.92134 | 0.9015 | 0.9495 | 0.9217 |
| 5 | XRPUSDT | 0.91010 | 0.9899 | 0.7727 | 0.9646 |
| 6 | 1000SHIBUSDT | 0.90467 | 0.8838 | 0.9672 | 0.8283 |
| 7 | ZORAUSDT | 0.90215 | 0.9747 | 0.8939 | 0.6793 |
| 8 | SKRUSDT | 0.88801 | 0.9874 | 0.8864 | 0.5606 |
| 9 | ZKUSDT | 0.88725 | 0.8965 | 0.8561 | 0.9293 |
| 10 | NOTUSDT | 0.88258 | 0.8434 | 0.9747 | 0.7980 |
| 11 | BOMEUSDT | 0.87790 | 0.7854 | 0.9848 | 0.9369 |
| 12 | AKEUSDT | 0.87450 | 0.8561 | 0.9520 | 0.7551 |
| 13 | XPLUSDT | 0.86831 | 0.8914 | 0.8157 | 0.9141 |
| 14 | 1000BONKUSDT | 0.86490 | 0.8510 | 0.9697 | 0.6667 |
| 15 | 龙虾USDT | 0.85922 | 0.9217 | 0.8914 | 0.5758 |

**D — Winsorized (p1–p99)**

| Rank | Symbol | Score | nVol | nOI | nSprd |
| --- | --- | --- | --- | --- | --- |
| 1 | ETHUSDT | 0.65004 | 1.0000 | 0.0001 | 0.9999 |
| 2 | BTCUSDT | 0.65000 | 1.0000 | 0.0000 | 1.0000 |
| 3 | ZECUSDT | 0.64913 | 1.0000 | 0.0000 | 0.9941 |
| 4 | XRPUSDT | 0.64113 | 0.9854 | 0.0168 | 0.9504 |
| 5 | SOLUSDT | 0.64012 | 1.0000 | 0.0004 | 0.9331 |
| 6 | 1000PEPEUSDT | 0.60563 | 0.2231 | 0.9904 | 0.9829 |
| 7 | PUMPUSDT | 0.58536 | 0.2201 | 1.0000 | 0.8356 |
| 8 | SKRUSDT | 0.52274 | 0.8089 | 0.0362 | 0.7043 |
| 9 | NEIROUSDT | 0.48987 | 0.0045 | 1.0000 | 0.9173 |
| 10 | 1000SATSUSDT | 0.40058 | 0.0009 | 1.0000 | 0.3341 |
| 11 | DOGSUSDT | 0.39284 | 0.0020 | 1.0000 | 0.2791 |
| 12 | DOGEUSDT | 0.36730 | 0.3607 | 0.1415 | 0.9160 |
| 13 | BOMEUSDT | 0.33621 | 0.0106 | 0.5489 | 0.9251 |
| 14 | HMSTRUSDT | 0.28860 | 0.0009 | 0.5705 | 0.5898 |
| 15 | 牛来USDT | 0.28568 | 0.3238 | 0.0074 | 0.8078 |

### Ranks 90–110 (Top-100 boundary)

**A — MinMax (V1 baseline)**

| Rank | Symbol | Score | nVol | nOI | nSprd |
| --- | --- | --- | --- | --- | --- |
| 90 | SPACEUSDT | 0.13625 | 0.0001 | 0.0021 | 0.9030 |
| 91 | CYSUSDT | 0.13588 | 0.0126 | 0.0001 | 0.8637 |
| 92 | UAIUSDT | 0.13583 | 0.0063 | 0.0002 | 0.8841 |
| 93 | KATUSDT | 0.13581 | 0.0003 | 0.0032 | 0.8969 |
| 94 | PYTHUSDT | 0.13578 | 0.0009 | 0.0011 | 0.8996 |
| 95 | TRUMPUSDT | 0.13572 | 0.0312 | 0.0002 | 0.8005 |
| 96 | REUSDT | 0.13563 | 0.0009 | 0.0001 | 0.9008 |
| 97 | PNUTUSDT | 0.13554 | 0.0003 | 0.0005 | 0.9013 |
| 98 | MAGICUSDT | 0.13522 | 0.0006 | 0.0002 | 0.8989 |
| 99 | MANTRAUSDT | 0.13521 | 0.0006 | 0.0042 | 0.8898 |
| 100 | HEIUSDT | 0.13493 | 0.0006 | 0.0002 | 0.8971 |
| 101 | SEIUSDT | 0.13479 | 0.0009 | 0.0009 | 0.8934 |
| 102 | CFXUSDT | 0.13450 | 0.0003 | 0.0006 | 0.8945 |
| 103 | PTBUSDT | 0.13447 | 0.0004 | 0.0327 | 0.8187 |
| 104 | VANAUSDT | 0.13425 | 0.0001 | 0.0000 | 0.8946 |

**B — Log + MinMax**

| Rank | Symbol | Score | nVol | nOI | nSprd |
| --- | --- | --- | --- | --- | --- |
| 90 | TACUSDT | 0.48638 | 0.2916 | 0.7327 | 0.5608 |
| 91 | CLOUSDT | 0.48625 | 0.3699 | 0.5191 | 0.7976 |
| 92 | KAITOUSDT | 0.48591 | 0.3653 | 0.5051 | 0.8431 |
| 93 | ROBOUSDT | 0.48498 | 0.3225 | 0.6556 | 0.6283 |
| 94 | KITEUSDT | 0.48335 | 0.2700 | 0.6003 | 0.9215 |
| 95 | XMRUSDT | 0.48304 | 0.5742 | 0.1585 | 0.9363 |
| 96 | ALGOUSDT | 0.48258 | 0.2924 | 0.5562 | 0.9445 |
| 97 | ZAMAUSDT | 0.48207 | 0.2875 | 0.5782 | 0.9062 |
| 98 | STRKUSDT | 0.48183 | 0.2974 | 0.6026 | 0.8147 |
| 99 | BCHUSDT | 0.48105 | 0.5027 | 0.2357 | 0.9812 |
| 100 | ESPORTSUSDT | 0.48011 | 0.2813 | 0.6627 | 0.7168 |
| 101 | MIRAUSDT | 0.47899 | 0.3723 | 0.5399 | 0.6925 |
| 102 | ZILUSDT | 0.47792 | 0.2275 | 0.6897 | 0.8186 |
| 103 | CAPUSDT | 0.47791 | 0.2598 | 0.5947 | 0.9326 |
| 104 | STXUSDT | 0.47747 | 0.3647 | 0.4961 | 0.8098 |

**Percentile**

| Rank | Symbol | Score | nVol | nOI | nSprd |
| --- | --- | --- | --- | --- | --- |
| 90 | NEARUSDT | 0.67020 | 0.9470 | 0.3813 | 0.4217 |
| 91 | BEAMXUSDT | 0.66995 | 0.5783 | 0.9646 | 0.2879 |
| 92 | JCTUSDT | 0.66907 | 0.6616 | 0.9470 | 0.0455 |
| 93 | RVNUSDT | 0.66730 | 0.6338 | 0.8788 | 0.2854 |
| 94 | ZECUSDT | 0.65846 | 0.9924 | 0.0404 | 0.9874 |
| 95 | CYSUSDT | 0.65694 | 0.9520 | 0.2172 | 0.6995 |
| 96 | BEATUSDT | 0.65606 | 0.8586 | 0.5732 | 0.1742 |
| 97 | BIGTIMEUSDT | 0.65543 | 0.5758 | 0.7525 | 0.6944 |
| 98 | MUBARAKUSDT | 0.65480 | 0.6414 | 0.7424 | 0.4949 |
| 99 | 我踏马来了USDT | 0.65442 | 0.7247 | 0.8030 | 0.0732 |
| 100 | BTCUSDT | 0.65278 | 0.9975 | 0.0126 | 0.9975 |
| 101 | ATHUSDT | 0.65265 | 0.4520 | 0.8662 | 0.8232 |
| 102 | BNBUSDT | 0.65139 | 0.9773 | 0.0429 | 0.9848 |
| 103 | AVAXUSDT | 0.64962 | 0.9343 | 0.1490 | 0.8687 |
| 104 | ZROUSDT | 0.64874 | 0.8409 | 0.2475 | 0.9444 |

**D — Winsorized (p1–p99)**

| Rank | Symbol | Score | nVol | nOI | nSprd |
| --- | --- | --- | --- | --- | --- |
| 90 | MOVRUSDT | 0.14225 | 0.0096 | 0.0002 | 0.9156 |
| 91 | APTUSDT | 0.14224 | 0.0237 | 0.0018 | 0.8651 |
| 92 | HUSDT | 0.14109 | 0.0017 | 0.0124 | 0.9059 |
| 93 | ATHUSDT | 0.14095 | 0.0017 | 0.0333 | 0.8562 |
| 94 | AXSUSDT | 0.14053 | 0.0040 | 0.0003 | 0.9228 |
| 95 | MANTRAUSDT | 0.14022 | 0.0049 | 0.0358 | 0.8350 |
| 96 | CAPUSDT | 0.14020 | 0.0042 | 0.0089 | 0.8999 |
| 97 | XAIUSDT | 0.13972 | 0.0008 | 0.0096 | 0.9065 |
| 98 | NEARUSDT | 0.13946 | 0.0933 | 0.0021 | 0.6137 |
| 99 | ESPUSDT | 0.13922 | 0.0035 | 0.0016 | 0.9126 |
| 100 | NILUSDT | 0.13910 | 0.0161 | 0.0035 | 0.8656 |
| 101 | FLOCKUSDT | 0.13844 | 0.0829 | 0.0040 | 0.6373 |
| 102 | KITEUSDT | 0.13826 | 0.0047 | 0.0098 | 0.8832 |
| 103 | SLXUSDT | 0.13791 | 0.0046 | 0.0027 | 0.8978 |
| 104 | KATUSDT | 0.13785 | 0.0027 | 0.0275 | 0.8457 |

### Ranks 190–210 (Middle)

**A — MinMax (V1 baseline)**

| Rank | Symbol | Score | nVol | nOI | nSprd |
| --- | --- | --- | --- | --- | --- |
| 190 | PARTIUSDT | 0.12053 | 0.0002 | 0.0008 | 0.8011 |
| 191 | GWEIUSDT | 0.12051 | 0.0004 | 0.0008 | 0.8002 |
| 192 | ONUSDT | 0.12035 | 0.0002 | 0.0003 | 0.8009 |
| 193 | MTLUSDT | 0.12026 | 0.0001 | 0.0000 | 0.8015 |
| 194 | XNYUSDT | 0.11997 | 0.0001 | 0.0036 | 0.7910 |
| 195 | BICOUSDT | 0.11965 | 0.0017 | 0.0017 | 0.7881 |
| 196 | ENSOUSDT | 0.11965 | 0.0011 | 0.0000 | 0.7940 |
| 197 | ELSAUSDT | 0.11941 | 0.0001 | 0.0002 | 0.7955 |
| 198 | SHELLUSDT | 0.11913 | 0.0001 | 0.0005 | 0.7928 |
| 199 | POWRUSDT | 0.11882 | 0.0000 | 0.0001 | 0.7917 |
| 200 | FLOCKUSDT | 0.11881 | 0.0095 | 0.0005 | 0.7594 |
| 201 | SAFEUSDT | 0.11871 | 0.0000 | 0.0001 | 0.7911 |
| 202 | INXUSDT | 0.11861 | 0.0001 | 0.0019 | 0.7859 |
| 203 | YGGUSDT | 0.11806 | 0.0001 | 0.0004 | 0.7857 |
| 204 | BANANAS31USDT | 0.11793 | 0.0001 | 0.0052 | 0.7737 |

**B — Log + MinMax**

| Rank | Symbol | Score | nVol | nOI | nSprd |
| --- | --- | --- | --- | --- | --- |
| 190 | GIGGLEUSDT | 0.41907 | 0.4181 | 0.2243 | 0.8768 |
| 191 | TOWNSUSDT | 0.41869 | 0.1691 | 0.6839 | 0.6319 |
| 192 | LIGHTUSDT | 0.41861 | 0.2839 | 0.4774 | 0.7307 |
| 193 | IDUSDT | 0.41845 | 0.2008 | 0.5435 | 0.8523 |
| 194 | MEWUSDT | 0.41819 | 0.1110 | 0.7551 | 0.6559 |
| 195 | 1000RATSUSDT | 0.41668 | 0.1660 | 0.6225 | 0.7719 |
| 196 | GRASSUSDT | 0.41630 | 0.2439 | 0.4698 | 0.8664 |
| 197 | HOTUSDT | 0.41593 | 0.1000 | 0.7780 | 0.6241 |
| 198 | XNYUSDT | 0.41518 | 0.1252 | 0.6684 | 0.7910 |
| 199 | XAIUSDT | 0.41477 | 0.1293 | 0.5988 | 0.9370 |
| 200 | AIXBTUSDT | 0.41455 | 0.2068 | 0.5612 | 0.7651 |
| 201 | NIGHTUSDT | 0.41454 | 0.1796 | 0.6113 | 0.7385 |
| 202 | OPENUSDT | 0.41441 | 0.2683 | 0.5288 | 0.6346 |
| 203 | GUSDT | 0.41437 | 0.0939 | 0.6759 | 0.8724 |
| 204 | SKLUSDT | 0.41305 | 0.1044 | 0.6575 | 0.8715 |

**Percentile**

| Rank | Symbol | Score | nVol | nOI | nSprd |
| --- | --- | --- | --- | --- | --- |
| 190 | OPENUSDT | 0.52172 | 0.6742 | 0.4419 | 0.1995 |
| 191 | BROCCOLI714USDT | 0.52083 | 0.6237 | 0.5808 | 0.0379 |
| 192 | IDUSDT | 0.52058 | 0.5000 | 0.4798 | 0.6843 |
| 193 | 1000SATSUSDT | 0.52046 | 0.3106 | 1.0000 | 0.1010 |
| 194 | PORTALUSDT | 0.51856 | 0.5657 | 0.6692 | 0.0101 |
| 195 | IOTXUSDT | 0.51578 | 0.3485 | 0.8611 | 0.2677 |
| 196 | SWARMSUSDT | 0.51250 | 0.4318 | 0.8182 | 0.0682 |
| 197 | ORDIUSDT | 0.51061 | 0.7449 | 0.0732 | 0.7500 |
| 198 | CHILLGUYUSDT | 0.50909 | 0.5581 | 0.6540 | 0.0076 |
| 199 | XNYUSDT | 0.50871 | 0.2626 | 0.8586 | 0.5126 |
| 200 | PARTIUSDT | 0.50833 | 0.4394 | 0.5909 | 0.5455 |
| 201 | AXSUSDT | 0.50720 | 0.6465 | 0.1263 | 0.9318 |
| 202 | XAIUSDT | 0.50644 | 0.2803 | 0.6667 | 0.8864 |
| 203 | GRASSUSDT | 0.50581 | 0.6288 | 0.2449 | 0.7045 |
| 204 | ENSOUSDT | 0.50568 | 0.7778 | 0.1086 | 0.5253 |

**D — Winsorized (p1–p99)**

| Rank | Symbol | Score | nVol | nOI | nSprd |
| --- | --- | --- | --- | --- | --- |
| 190 | ACHUSDT | 0.11068 | 0.0008 | 0.0139 | 0.7028 |
| 191 | CKBUSDT | 0.11049 | 0.0016 | 0.0642 | 0.5814 |
| 192 | RAVEUSDT | 0.11039 | 0.0020 | 0.0010 | 0.7268 |
| 193 | SCRUSDT | 0.11010 | 0.0028 | 0.0042 | 0.7149 |
| 194 | RONINUSDT | 0.10948 | 0.0001 | 0.0013 | 0.7264 |
| 195 | PIEVERSEUSDT | 0.10908 | 0.0020 | 0.0007 | 0.7189 |
| 196 | SFPUSDT | 0.10907 | 0.0001 | 0.0006 | 0.7254 |
| 197 | GWEIUSDT | 0.10902 | 0.0037 | 0.0065 | 0.6991 |
| 198 | PHAUSDT | 0.10860 | 0.0012 | 0.0028 | 0.7134 |
| 199 | 币安人生USDT | 0.10854 | 0.0028 | 0.0042 | 0.7045 |
| 200 | ENJUSDT | 0.10853 | 0.0014 | 0.0053 | 0.7064 |
| 201 | TWTUSDT | 0.10837 | 0.0041 | 0.0004 | 0.7080 |
| 202 | ENSOUSDT | 0.10821 | 0.0094 | 0.0002 | 0.6896 |
| 203 | PARTIUSDT | 0.10811 | 0.0016 | 0.0065 | 0.7005 |
| 204 | WALUSDT | 0.10791 | 0.0018 | 0.0039 | 0.7042 |

### Ranks 380–397 (Bottom)

**A — MinMax (V1 baseline)**

| Rank | Symbol | Score | nVol | nOI | nSprd |
| --- | --- | --- | --- | --- | --- |
| 380 | TRADOORUSDT | 0.07452 | 0.0001 | 0.0000 | 0.4965 |
| 381 | BBUSDT | 0.07257 | 0.0005 | 0.0018 | 0.4779 |
| 382 | SLPUSDT | 0.07183 | 0.0000 | 0.0084 | 0.4592 |
| 383 | BROCCOLI714USDT | 0.06867 | 0.0004 | 0.0007 | 0.4549 |
| 384 | ASRUSDT | 0.06786 | 0.0000 | 0.0000 | 0.4523 |
| 385 | 1000000BOBUSDT | 0.06724 | 0.0000 | 0.0005 | 0.4469 |
| 386 | XVGUSDT | 0.06501 | 0.0003 | 0.0028 | 0.4260 |
| 387 | BSVUSDT | 0.06004 | 0.0001 | 0.0000 | 0.3999 |
| 388 | CELRUSDT | 0.05993 | 0.0000 | 0.0035 | 0.3914 |
| 389 | AVAAIUSDT | 0.05979 | 0.0001 | 0.0020 | 0.3935 |
| 390 | BULLAUSDT | 0.05971 | 0.0002 | 0.0018 | 0.3933 |
| 391 | GOATUSDT | 0.05804 | 0.0001 | 0.0005 | 0.3854 |
| 392 | SAGAUSDT | 0.05484 | 0.0003 | 0.0015 | 0.3612 |
| 393 | PORTALUSDT | 0.05163 | 0.0003 | 0.0011 | 0.3406 |
| 394 | CHILLGUYUSDT | 0.04697 | 0.0003 | 0.0011 | 0.3097 |

**B — Log + MinMax**

| Rank | Symbol | Score | nVol | nOI | nSprd |
| --- | --- | --- | --- | --- | --- |
| 380 | ARKUSDT | 0.27128 | 0.0686 | 0.4326 | 0.5705 |
| 381 | CYBERUSDT | 0.27004 | 0.1041 | 0.3914 | 0.5399 |
| 382 | SANTOSUSDT | 0.26463 | 0.0666 | 0.3494 | 0.7269 |
| 383 | ETHWUSDT | 0.25910 | 0.0570 | 0.3846 | 0.6401 |
| 384 | KSMUSDT | 0.24967 | 0.1111 | 0.2422 | 0.7292 |
| 385 | 1000000MOGUSDT | 0.24914 | 0.0445 | 0.4093 | 0.5575 |
| 386 | QNTUSDT | 0.24912 | 0.1677 | 0.1097 | 0.8459 |
| 387 | METISUSDT | 0.24650 | 0.1219 | 0.2552 | 0.6417 |
| 388 | RLCUSDT | 0.24646 | 0.0710 | 0.3730 | 0.5358 |
| 389 | NMRUSDT | 0.24228 | 0.0876 | 0.1839 | 0.8943 |
| 390 | TAUSDT | 0.23927 | 0.0790 | 0.5708 | 0.0000 |
| 391 | PHAROSUSDT | 0.23381 | 0.0424 | 0.3775 | 0.5366 |
| 392 | CTKUSDT | 0.23009 | 0.0000 | 0.4067 | 0.5849 |
| 393 | AVAUSDT | 0.22931 | 0.0268 | 0.3974 | 0.5121 |
| 394 | ILVUSDT | 0.22526 | 0.0773 | 0.2394 | 0.6857 |

**Percentile**

| Rank | Symbol | Score | nVol | nOI | nSprd |
| --- | --- | --- | --- | --- | --- |
| 380 | METISUSDT | 0.16553 | 0.2424 | 0.0379 | 0.2071 |
| 381 | SFPUSDT | 0.16515 | 0.0227 | 0.1818 | 0.6010 |
| 382 | CVCUSDT | 0.15568 | 0.0177 | 0.3914 | 0.0657 |
| 383 | BSVUSDT | 0.15202 | 0.2904 | 0.0076 | 0.0278 |
| 384 | DIAUSDT | 0.14634 | 0.1162 | 0.1515 | 0.2348 |
| 385 | CYBERUSDT | 0.13952 | 0.1667 | 0.1237 | 0.0859 |
| 386 | GTCUSDT | 0.13864 | 0.0808 | 0.2222 | 0.1364 |
| 387 | ALPINEUSDT | 0.12323 | 0.0480 | 0.1212 | 0.3788 |
| 388 | SANTOSUSDT | 0.11250 | 0.0581 | 0.0859 | 0.3561 |
| 389 | ARKUSDT | 0.10821 | 0.0631 | 0.1692 | 0.1162 |
| 390 | ILVUSDT | 0.10290 | 0.0934 | 0.0328 | 0.2980 |
| 391 | ETHWUSDT | 0.09407 | 0.0455 | 0.1162 | 0.2045 |
| 392 | RLCUSDT | 0.08119 | 0.0707 | 0.0985 | 0.0758 |
| 393 | 1000000MOGUSDT | 0.07942 | 0.0303 | 0.1414 | 0.0985 |
| 394 | CTKUSDT | 0.06831 | 0.0000 | 0.1389 | 0.1313 |

**D — Winsorized (p1–p99)**

| Rank | Symbol | Score | nVol | nOI | nSprd |
| --- | --- | --- | --- | --- | --- |
| 380 | STARUSDT | 0.03896 | 0.0017 | 0.0019 | 0.2497 |
| 381 | OPGUSDT | 0.03790 | 0.0022 | 0.0023 | 0.2398 |
| 382 | TRADOORUSDT | 0.03619 | 0.0007 | 0.0003 | 0.2383 |
| 383 | BROCCOLI714USDT | 0.03008 | 0.0034 | 0.0060 | 0.1753 |
| 384 | XVGUSDT | 0.02923 | 0.0022 | 0.0240 | 0.1315 |
| 385 | 1000000BOBUSDT | 0.02620 | 0.0002 | 0.0046 | 0.1631 |
| 386 | ASRUSDT | 0.02575 | 0.0000 | 0.0001 | 0.1714 |
| 387 | CELRUSDT | 0.02237 | 0.0000 | 0.0301 | 0.0789 |
| 388 | AVAAIUSDT | 0.01884 | 0.0007 | 0.0176 | 0.0822 |
| 389 | BULLAUSDT | 0.01840 | 0.0014 | 0.0155 | 0.0819 |
| 390 | BSVUSDT | 0.01421 | 0.0009 | 0.0000 | 0.0919 |
| 391 | GOATUSDT | 0.01240 | 0.0006 | 0.0047 | 0.0699 |
| 392 | SAGAUSDT | 0.01065 | 0.0024 | 0.0128 | 0.0331 |
| 393 | HANAUSDT | 0.00632 | 0.0012 | 0.0164 | 0.0000 |
| 394 | PORTALUSDT | 0.00493 | 0.0026 | 0.0096 | 0.0019 |

## 6. BTC / ETH Analysis

Effect of normalization method on the two largest contracts.

**ETHUSDT** — raw volume: $10.95B, raw OI: 2376426, spread: 0.0410 bps

| Method | nVol | nOI | nSprd | Score | Rank |
| --- | --- | --- | --- | --- | --- |
| A — MinMax (V1 baseline) | 1.0000 | 0.0000 | 0.9985 | 0.6498 | 1 |
| B — Log + MinMax | 1.0000 | 0.3446 | 0.9985 | 0.7704 | 2 |
| Percentile | 1.0000 | 0.0833 | 0.9899 | 0.6777 | 82 |
| D — Winsorized (p1–p99) | 1.0000 | 0.0001 | 0.9999 | 0.6500 | 1 |

**BTCUSDT** — raw volume: $10.54B, raw OI: 107249, spread: 0.0129 bps

| Method | nVol | nOI | nSprd | Score | Rank |
| --- | --- | --- | --- | --- | --- |
| A — MinMax (V1 baseline) | 0.9630 | 0.0000 | 0.9999 | 0.6315 | 2 |
| B — Log + MinMax | 0.9963 | 0.1619 | 0.9999 | 0.7048 | 8 |
| Percentile | 0.9975 | 0.0126 | 0.9975 | 0.6528 | 100 |
| D — Winsorized (p1–p99) | 1.0000 | 0.0000 | 1.0000 | 0.6500 | 2 |

## 7. Recommendation

### Evidence Summary

| Metric | MinMax (V1) | Log+MinMax | Percentile | Winsorized |
| --- | --- | --- | --- | --- |
| norm_vol < 0.10 | 98.7% | 15.9% | 10.1% | 94.7% |
| Dominant feature | spread (94.5%) | OI (44.6%) | volume (50.0%) | spread (77.9%) |
| BTC rank | 2 | 8 | **100** | 2 |
| ETH rank | 1 | 2 | **82** | 1 |
| Top-100 overlap vs baseline | — | 65% | 60% | 84% |
| Spearman vs baseline | — | 0.674 | 0.637 | 0.941 |

### Key Findings

**Winsorized (p1–p99)** fails as a fix. At 94.7% compressed, it provides only 4pp improvement over V1 and spread still dominates at 77.9%. Not recommended.

**Percentile** achieves the strongest compression reduction (−88.6pp) and exactly replicates the configured weight distribution (50/35/15) by construction. However, it has a critical problem: BTC ranks #100 and ETH ranks #82. Percentile normalization is insensitive to magnitudes by design — BTCUSDT's $10.5B volume is treated as only marginally different from SOLANUS's $2.5B because both are near the top of the rank distribution. A market-quality universe that places BTC at the borderline of the Top-100 is semantically wrong, regardless of the statistical properties of the normalizer.

**Log + MinMax** reduces compression from 98.7% to 15.9% (−82.8pp). Feature dominance becomes OI-led (vol=28.5%, OI=44.6%, spread=26.9%), which is reasonable and reflects the actual spread of the distribution. BTC and ETH rank #8 and #2 respectively — sensible positions. The Spearman correlation of 0.674 indicates moderate divergence from V1, meaning the method meaningfully re-orders the universe rather than being a no-op.

The OI dominance under Log+MinMax (44.6%) deserves attention: the live universe contains meme-token contracts (1000SATSUSDT, NEIROUSDT, DOGSUSDT, PUMPUSDT) with enormous OI in base units — billions of tokens — which log-compress to a high relative rank. This is accurate behavior: those contracts genuinely have deep open interest by unit count. Whether that is the desired signal is a configuration decision, not a normalization bug.

```
RECOMMENDATION: ADOPT B — Log + MinMax FOR V1.1

Reason:
  - Reduces volume compression from 98.7% to 15.9% (−82.8pp vs V1 baseline)
  - Eliminates spread's near-total dominance (94.5% → 26.9%)
  - Balances feature contributions: volume 28.5%, OI 44.6%, spread 26.9%
  - BTC ranks #8, ETH ranks #2 — semantically reasonable
  - Deterministic and mathematically straightforward (log1p is invertible and explainable)
  - Does not require hyperparameter tuning (unlike Winsorized)
  - Spearman vs V1: 0.674 — meaningfully different, not a trivial rearrangement

REJECTED: Percentile
  - BTC rank #100, ETH rank #82: semantically indefensible for a market-quality universe
  - Loses all magnitude information; treats $10B volume as marginally different from $2.5B

REJECTED: Winsorized (p1–p99)
  - Provides only 4pp compression reduction; spread still dominates at 77.9%
  - Does not solve the identified problem

NOTED: V1 MinMax remains the better choice if BTC/ETH rank stability is the
  primary concern and spread dominance is acceptable. If adopted, the V1 audit
  finding remains an open issue.
```

---
*Report generated by `universe/experiment.py` — Binance Perpetual Universe V1.1 Normalization Experiment*