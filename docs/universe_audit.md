# Binance Perpetual Universe Engine — V1 Audit Report

**Audit generated:** 2026-08-31T13:55:02.720931+00:00  
**Snapshot ID:** `20260831T135456Z`  
**Snapshot timestamp:** 2026-08-31T13:54:56.507097+00:00

## 1. Live Universe Baseline

```
timestamp             : 2026-08-31T13:54:56.507097+00:00
total_discovered      : 883
eligible_crypto_perps : 397
excluded              : 486
successfully_ranked   : 397
metric_failures       : 0
active_top_100        : 100
watchlist_count       : 297

eligible == active_top_100 + watchlist_count  → ✅ PASS
  397 == 100 + 297 = 397
```

## 2. Distribution Statistics

**24h Quote Volume (USD)**

| Stat | Value |
| --- | --- |
| count | 397 |
| min | $0.00B |
| p25 | $0.00B |
| median | $0.00B |
| p75 | $0.01B |
| p90 | $0.05B |
| p95 | $0.13B |
| p99 | $1.25B |
| max | $10.95B |
| mean | $0.09B |

**Open Interest (base units)**

| Stat | Value |
| --- | --- |
| count | 397 |
| min | 6878 |
| p25 | 21081812 |
| median | 74188023 |
| p75 | 279854271 |
| p90 | 779228016 |
| p95 | 3217268966 |
| p99 | 18531450709 |
| max | 159717286507 |
| mean | 1195834453 |

**Bid/Ask Spread (bps)** 

| Stat | Value |
| --- | --- |
| count | 397 |
| min | 0.01 |
| p25 | 2.59 |
| median | 4.71 |
| p75 | 7.24 |
| p90 | 9.38 |
| p95 | 10.69 |
| p99 | 14.04 |
| max | 21.25 |
| mean | 5.11 |

**Universe Score** 

| Stat | Value |
| --- | --- |
| count | 397 |
| min | 0.00 |
| p25 | 0.10 |
| median | 0.12 |
| p75 | 0.13 |
| p90 | 0.14 |
| p95 | 0.15 |
| p99 | 0.26 |
| max | 0.65 |
| mean | 0.12 |

## 3. Top-100 Complete Table

Sorted strictly by rank. Columns: rank, symbol, score, 24h volume, OI, spread_bps, norm_volume, norm_OI, norm_spread, vol_contrib, oi_contrib, spread_contrib.

| Rank | Symbol | Score | Vol (USD) | OI | Sprd bps | nVol | nOI | nSprd | vContrib | oContrib | sContrib |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 1 | ETHUSDT | 0.64979 | $10948.87M | 2376426 | 0.04 | 1.0000 | 0.0000 | 0.9981 | 0.5000 | 0.0000 | 0.1497 |
| 2 | BTCUSDT | 0.63146 | $10543.27M | 107249 | 0.01 | 0.9629 | 0.0000 | 0.9998 | 0.4814 | 0.0000 | 0.1500 |
| 3 | 1000SATSUSDT | 0.43400 | $1.69M | 159717286507 | 9.36 | 0.0001 | 1.0000 | 0.4278 | 0.0001 | 0.3500 | 0.0642 |
| 4 | NEIROUSDT | 0.26874 | $6.20M | 57889989213 | 1.20 | 0.0005 | 0.3625 | 0.9273 | 0.0003 | 0.1269 | 0.1391 |
| 5 | SOLUSDT | 0.25955 | $2548.36M | 8415953 | 0.98 | 0.2327 | 0.0001 | 0.9408 | 0.1164 | 0.0000 | 0.1411 |
| 6 | ZECUSDT | 0.22625 | $1687.46M | 528091 | 0.12 | 0.1541 | 0.0000 | 0.9931 | 0.0770 | 0.0000 | 0.1490 |
| 7 | XRPUSDT | 0.20176 | $1230.96M | 311170652 | 0.73 | 0.1124 | 0.0019 | 0.9557 | 0.0562 | 0.0007 | 0.1433 |
| 8 | 1000PEPEUSDT | 0.20104 | $279.16M | 18353219447 | 0.28 | 0.0255 | 0.1149 | 0.9835 | 0.0127 | 0.0402 | 0.1475 |
| 9 | PUMPUSDT | 0.19606 | $275.32M | 22809000991 | 2.34 | 0.0251 | 0.1428 | 0.8573 | 0.0126 | 0.0500 | 0.1286 |
| 10 | DOGSUSDT | 0.17580 | $2.99M | 44347738893 | 10.13 | 0.0002 | 0.2776 | 0.3798 | 0.0001 | 0.0972 | 0.0570 |
| 11 | SKRUSDT | 0.16815 | $1010.54M | 670646518 | 4.18 | 0.0922 | 0.0042 | 0.7864 | 0.0461 | 0.0015 | 0.1180 |
| 12 | DOGEUSDT | 0.16780 | $450.99M | 2623081293 | 1.22 | 0.0412 | 0.0164 | 0.9261 | 0.0206 | 0.0057 | 0.1389 |
| 13 | BOMEUSDT | 0.16528 | $13.81M | 10172819706 | 1.09 | 0.0012 | 0.0637 | 0.9340 | 0.0006 | 0.0223 | 0.1401 |
| 14 | BNBUSDT | 0.16206 | $285.43M | 627006 | 0.15 | 0.0260 | 0.0000 | 0.9917 | 0.0130 | 0.0000 | 0.1488 |
| 15 | PAXGUSDT | 0.15355 | $80.19M | 14602 | 0.02 | 0.0073 | 0.0000 | 0.9992 | 0.0036 | 0.0000 | 0.1499 |
| 16 | XAUTUSDT | 0.15245 | $56.06M | 6878 | 0.02 | 0.0051 | 0.0000 | 0.9992 | 0.0025 | 0.0000 | 0.1499 |
| 17 | SUIUSDT | 0.15184 | $249.13M | 124335659 | 1.40 | 0.0227 | 0.0008 | 0.9151 | 0.0114 | 0.0003 | 0.1373 |
| 18 | PENGUUSDT | 0.15123 | $51.77M | 3181038504 | 1.16 | 0.0047 | 0.0199 | 0.9299 | 0.0023 | 0.0070 | 0.1395 |
| 19 | TAOUSDT | 0.15118 | $92.90M | 278427 | 0.44 | 0.0084 | 0.0000 | 0.9736 | 0.0042 | 0.0000 | 0.1460 |
| 20 | TRXUSDT | 0.15099 | $54.79M | 257834620 | 0.30 | 0.0050 | 0.0016 | 0.9822 | 0.0025 | 0.0006 | 0.1473 |
| 21 | LINKUSDT | 0.15061 | $150.14M | 9846328 | 0.89 | 0.0137 | 0.0001 | 0.9459 | 0.0068 | 0.0000 | 0.1419 |
| 22 | BCHUSDT | 0.15031 | $68.84M | 374994 | 0.41 | 0.0063 | 0.0000 | 0.9756 | 0.0031 | 0.0000 | 0.1463 |
| 23 | USDCUSDT | 0.15010 | $2.22M | 6553232 | 0.01 | 0.0002 | 0.0000 | 1.0000 | 0.0001 | 0.0000 | 0.1500 |
| 24 | 牛来USDT | 0.14955 | $404.89M | 137959059 | 2.73 | 0.0369 | 0.0009 | 0.7779 | 0.0185 | 0.0003 | 0.1167 |
| 25 | NOTUSDT | 0.14886 | $22.95M | 6032346133 | 2.19 | 0.0021 | 0.0378 | 0.5994 | 0.0010 | 0.0132 | 0.0899 |
| 26 | ZKCUSDT | 0.14859 | $245.25M | 95837356 | 1.82 | 0.0224 | 0.0006 | 0.7778 | 0.0112 | 0.0002 | 0.1167 |
| 27 | XLMUSDT | 0.14837 | $43.47M | 171355988 | 0.57 | 0.0039 | 0.0011 | 0.9656 | 0.0020 | 0.0004 | 0.1448 |
| 28 | HUMAUSDT | 0.14818 | $7.89M | 544236028 | 0.48 | 0.0007 | 0.0034 | 0.9413 | 0.0003 | 0.0012 | 0.1412 |
| 29 | MAGMAUSDT | 0.14804 | $99.33M | 26539982 | 0.94 | 0.0090 | 0.0002 | 0.8671 | 0.0045 | 0.0001 | 0.1301 |
| 30 | ALLOUSDT | 0.14741 | $4.82M | 39299069 | 0.42 | 0.0004 | 0.0002 | 0.9750 | 0.0002 | 0.0001 | 0.1463 |
| 31 | XMRUSDT | 0.14694 | $142.73M | 101191 | 1.36 | 0.0130 | 0.0000 | 0.8935 | 0.0065 | 0.0000 | 0.1340 |
| 32 | 1000SHIBUSDT | 0.14688 | $35.99M | 4250734738 | 2.00 | 0.0032 | 0.0266 | 0.8782 | 0.0016 | 0.0093 | 0.1317 |
| 33 | COTIUSDT | 0.14653 | $16.10M | 517534661 | 0.76 | 0.0014 | 0.0032 | 0.9539 | 0.0007 | 0.0011 | 0.1431 |
| 34 | KOMAUSDT | 0.14556 | $3.53M | 319453304 | 0.76 | 0.0003 | 0.0020 | 0.9542 | 0.0001 | 0.0007 | 0.1431 |
| 35 | ZKUSDT | 0.14549 | $47.06M | 567398838 | 1.13 | 0.0043 | 0.0036 | 0.9317 | 0.0021 | 0.0012 | 0.1398 |
| 36 | ONGUSDT | 0.14549 | $63.91M | 93054151 | 1.09 | 0.0058 | 0.0006 | 0.9340 | 0.0029 | 0.0002 | 0.1401 |
| 37 | BASUSDT | 0.14470 | $2.13M | 95356711 | 0.80 | 0.0002 | 0.0006 | 0.9271 | 0.0001 | 0.0002 | 0.1391 |
| 38 | UBUSDT | 0.14455 | $4.76M | 30925514 | 0.82 | 0.0004 | 0.0002 | 0.9505 | 0.0002 | 0.0001 | 0.1426 |
| 39 | XPLUSDT | 0.14443 | $40.91M | 396777674 | 1.18 | 0.0037 | 0.0025 | 0.9282 | 0.0019 | 0.0009 | 0.1392 |
| 40 | CCUSDT | 0.14443 | $4.17M | 94267458 | 0.85 | 0.0003 | 0.0006 | 0.8442 | 0.0002 | 0.0002 | 0.1266 |
| 41 | MEMEUSDT | 0.14436 | $2.46M | 3620520849 | 1.95 | 0.0002 | 0.0227 | 0.8815 | 0.0001 | 0.0079 | 0.1322 |
| 42 | ZROUSDT | 0.14435 | $22.85M | 20785756 | 0.96 | 0.0021 | 0.0001 | 0.8829 | 0.0010 | 0.0000 | 0.1324 |
| 43 | AVAXUSDT | 0.14405 | $84.65M | 7820919 | 1.40 | 0.0077 | 0.0000 | 0.9149 | 0.0038 | 0.0000 | 0.1372 |
| 44 | POLUSDT | 0.14400 | $33.56M | 181925505 | 1.13 | 0.0030 | 0.0011 | 0.9314 | 0.0015 | 0.0004 | 0.1397 |
| 45 | ARBUSDT | 0.14366 | $31.64M | 209131545 | 1.17 | 0.0029 | 0.0013 | 0.9288 | 0.0014 | 0.0005 | 0.1393 |
| 46 | DOTUSDT | 0.14335 | $39.91M | 31829583 | 1.22 | 0.0036 | 0.0002 | 0.9262 | 0.0018 | 0.0001 | 0.1389 |
| 47 | FFUSDT | 0.14320 | $9.17M | 374384416 | 1.15 | 0.0008 | 0.0023 | 0.8604 | 0.0004 | 0.0008 | 0.1291 |
| 48 | OPUSDT | 0.14314 | $20.20M | 160040740 | 1.16 | 0.0018 | 0.0010 | 0.9297 | 0.0009 | 0.0004 | 0.1395 |
| 49 | WUSDT | 0.14303 | $3.59M | 279854271 | 1.10 | 0.0003 | 0.0018 | 0.9330 | 0.0001 | 0.0006 | 0.1399 |
| 50 | ACEUSDT | 0.14279 | $22.43M | 55813761 | 1.19 | 0.0020 | 0.0003 | 0.8547 | 0.0010 | 0.0001 | 0.1282 |
| 51 | SAHARAUSDT | 0.14262 | $3.56M | 464708309 | 1.22 | 0.0003 | 0.0029 | 0.8512 | 0.0001 | 0.0010 | 0.1277 |
| 52 | VVVUSDT | 0.14249 | $18.56M | 831500 | 1.19 | 0.0017 | 0.0000 | 0.9278 | 0.0008 | 0.0000 | 0.1392 |
| 53 | AXSUSDT | 0.14240 | $5.56M | 5640772 | 1.12 | 0.0005 | 0.0000 | 0.9320 | 0.0002 | 0.0000 | 0.1398 |
| 54 | ALGOUSDT | 0.14222 | $8.07M | 86054332 | 1.19 | 0.0007 | 0.0005 | 0.9279 | 0.0003 | 0.0002 | 0.1392 |
| 55 | FILUSDT | 0.14221 | $57.25M | 50485584 | 1.50 | 0.0052 | 0.0003 | 0.9090 | 0.0026 | 0.0001 | 0.1364 |
| 56 | HBARUSDT | 0.14219 | $21.37M | 375584236 | 1.37 | 0.0019 | 0.0024 | 0.9170 | 0.0010 | 0.0008 | 0.1375 |
| 57 | LABUSDT | 0.14215 | $28.36M | 193285343 | 1.36 | 0.0026 | 0.0012 | 0.9173 | 0.0013 | 0.0004 | 0.1376 |
| 58 | MOVRUSDT | 0.14201 | $12.58M | 4453686 | 1.22 | 0.0011 | 0.0000 | 0.9259 | 0.0006 | 0.0000 | 0.1389 |
| 59 | ZORAUSDT | 0.14179 | $282.33M | 719029540 | 3.22 | 0.0258 | 0.0045 | 0.8035 | 0.0129 | 0.0016 | 0.1205 |
| 60 | VETUSDT | 0.14175 | $12.07M | 767664682 | 1.49 | 0.0011 | 0.0048 | 0.8180 | 0.0005 | 0.0017 | 0.1227 |
| 61 | ESPUSDT | 0.14141 | $4.95M | 30076580 | 1.26 | 0.0004 | 0.0002 | 0.9233 | 0.0002 | 0.0001 | 0.1385 |
| 62 | ETCUSDT | 0.14124 | $21.50M | 2591888 | 1.39 | 0.0019 | 0.0000 | 0.9157 | 0.0010 | 0.0000 | 0.1374 |
| 63 | BTRUSDT | 0.14121 | $266.58M | 214855200 | 3.04 | 0.0243 | 0.0013 | 0.8764 | 0.0122 | 0.0005 | 0.1315 |
| 64 | HUSDT | 0.14109 | $2.68M | 230601725 | 1.36 | 0.0002 | 0.0014 | 0.9175 | 0.0001 | 0.0005 | 0.1376 |
| 65 | XAIUSDT | 0.14098 | $1.53M | 177138899 | 1.35 | 0.0001 | 0.0011 | 0.9181 | 0.0001 | 0.0004 | 0.1377 |
| 66 | AUSDT | 0.14073 | $2.29M | 29077384 | 1.34 | 0.0002 | 0.0002 | 0.6719 | 0.0001 | 0.0001 | 0.1008 |
| 67 | AKEUSDT | 0.14072 | $27.27M | 3362190815 | 2.54 | 0.0025 | 0.0211 | 0.9229 | 0.0012 | 0.0074 | 0.1384 |
| 68 | VIRTUALUSDT | 0.14071 | $24.32M | 23209242 | 1.49 | 0.0022 | 0.0001 | 0.9096 | 0.0011 | 0.0001 | 0.1364 |
| 69 | CAPUSDT | 0.14049 | $5.79M | 165117923 | 1.44 | 0.0005 | 0.0010 | 0.9124 | 0.0002 | 0.0004 | 0.1369 |
| 70 | SLXUSDT | 0.14006 | $6.28M | 49409894 | 1.47 | 0.0005 | 0.0003 | 0.9106 | 0.0003 | 0.0001 | 0.1366 |
| 71 | BASEDUSDT | 0.13989 | $4.11M | 64808858 | 1.49 | 0.0003 | 0.0004 | 0.9096 | 0.0002 | 0.0001 | 0.1364 |
| 72 | ONEUSDT | 0.13943 | $2.76M | 3720486920 | 2.68 | 0.0002 | 0.0233 | 0.7550 | 0.0001 | 0.0082 | 0.1132 |
| 73 | KITEUSDT | 0.13890 | $6.43M | 181640824 | 1.68 | 0.0005 | 0.0011 | 0.7956 | 0.0003 | 0.0004 | 0.1193 |
| 74 | ZENUSDT | 0.13843 | $30.97M | 1243888 | 1.85 | 0.0028 | 0.0000 | 0.8876 | 0.0014 | 0.0000 | 0.1331 |
| 75 | LTCUSDT | 0.13825 | $62.47M | 1178402 | 2.07 | 0.0057 | 0.0000 | 0.8736 | 0.0028 | 0.0000 | 0.1310 |
| 76 | GPSUSDT | 0.13796 | $10.30M | 1024999210 | 2.10 | 0.0009 | 0.0064 | 0.9365 | 0.0005 | 0.0022 | 0.1405 |
| 77 | VTHOUSDT | 0.13788 | $1.25M | 2511918564 | 2.51 | 0.0001 | 0.0157 | 0.8470 | 0.0000 | 0.0055 | 0.1271 |
| 78 | APTUSDT | 0.13788 | $30.14M | 32936184 | 1.93 | 0.0027 | 0.0002 | 0.8826 | 0.0014 | 0.0001 | 0.1324 |
| 79 | NILUSDT | 0.13756 | $20.58M | 65333953 | 1.92 | 0.0018 | 0.0004 | 0.8830 | 0.0009 | 0.0001 | 0.1324 |
| 80 | OUSDT | 0.13750 | $6.88M | 10850621 | 1.82 | 0.0006 | 0.0001 | 0.8890 | 0.0003 | 0.0000 | 0.1333 |
| 81 | ZKPUSDT | 0.13750 | $49.27M | 81115112 | 2.12 | 0.0045 | 0.0005 | 0.7411 | 0.0022 | 0.0002 | 0.1112 |
| 82 | SPXUSDT | 0.13738 | $12.10M | 13251350 | 1.88 | 0.0011 | 0.0001 | 0.7708 | 0.0005 | 0.0000 | 0.1156 |
| 83 | ATHUSDT | 0.13703 | $2.67M | 617603585 | 2.05 | 0.0002 | 0.0039 | 0.6248 | 0.0001 | 0.0014 | 0.0937 |
| 84 | ONTUSDT | 0.13701 | $7.95M | 53041994 | 1.91 | 0.0007 | 0.0003 | 0.8835 | 0.0003 | 0.0001 | 0.1325 |
| 85 | DASHUSDT | 0.13698 | $73.37M | 397701 | 2.33 | 0.0067 | 0.0000 | 0.8582 | 0.0033 | 0.0000 | 0.1287 |
| 86 | 1000BONKUSDT | 0.13682 | $26.07M | 4394923065 | 3.41 | 0.0023 | 0.0275 | 0.7922 | 0.0012 | 0.0096 | 0.1188 |
| 87 | ZAMAUSDT | 0.13654 | $7.68M | 124917181 | 2.00 | 0.0007 | 0.0008 | 0.7553 | 0.0003 | 0.0003 | 0.1133 |
| 88 | WLDUSDT | 0.13639 | $128.59M | 176172084 | 2.82 | 0.0117 | 0.0011 | 0.8280 | 0.0059 | 0.0004 | 0.1242 |
| 89 | PIXELUSDT | 0.13628 | $1.46M | 311772187 | 2.06 | 0.0001 | 0.0020 | 0.7490 | 0.0000 | 0.0007 | 0.1124 |
| 90 | SPACEUSDT | 0.13625 | $1.67M | 337751572 | 2.07 | 0.0001 | 0.0021 | 0.6207 | 0.0001 | 0.0007 | 0.0931 |
| 91 | CYSUSDT | 0.13588 | $138.31M | 17254822 | 2.91 | 0.0126 | 0.0001 | 0.6449 | 0.0063 | 0.0000 | 0.0967 |
| 92 | UAIUSDT | 0.13583 | $69.57M | 26037743 | 2.47 | 0.0063 | 0.0002 | 0.6980 | 0.0032 | 0.0001 | 0.1047 |
| 93 | KATUSDT | 0.13581 | $3.90M | 510489187 | 2.20 | 0.0003 | 0.0032 | 0.7314 | 0.0002 | 0.0011 | 0.1097 |
| 94 | PYTHUSDT | 0.13578 | $10.47M | 171929280 | 2.14 | 0.0009 | 0.0011 | 0.8695 | 0.0005 | 0.0004 | 0.1304 |
| 95 | TRUMPUSDT | 0.13572 | $341.51M | 28015364 | 4.25 | 0.0312 | 0.0002 | 0.7406 | 0.0156 | 0.0001 | 0.1111 |
| 96 | REUSDT | 0.13563 | $10.62M | 19787959 | 2.12 | 0.0009 | 0.0001 | 0.8712 | 0.0005 | 0.0000 | 0.1307 |
| 97 | PNUTUSDT | 0.13554 | $3.81M | 83296095 | 2.11 | 0.0003 | 0.0005 | 0.7429 | 0.0002 | 0.0002 | 0.1114 |
| 98 | MAGICUSDT | 0.13522 | $6.95M | 35735320 | 2.16 | 0.0006 | 0.0002 | 0.7367 | 0.0003 | 0.0001 | 0.1105 |
| 99 | MANTRAUSDT | 0.13521 | $6.67M | 663063443 | 2.35 | 0.0006 | 0.0042 | 0.8567 | 0.0003 | 0.0015 | 0.1285 |
| 100 | HEIUSDT | 0.13493 | $7.03M | 30090871 | 2.20 | 0.0006 | 0.0002 | 0.8662 | 0.0003 | 0.0001 | 0.1299 |

## 4. Top-100 Boundary (Ranks 90–110)

| Rank | Symbol | Score | Vol (USD) | OI | Sprd bps | Status |
| --- | --- | --- | --- | --- | --- | --- |
| 90 | SPACEUSDT | 0.1362553 | $1.67M | 337751572 | 2.07 | ACTIVE_TOP_100 |
| 91 | CYSUSDT | 0.1358845 | $138.31M | 17254822 | 2.91 | ACTIVE_TOP_100 |
| 92 | UAIUSDT | 0.1358264 | $69.57M | 26037743 | 2.47 | ACTIVE_TOP_100 |
| 93 | KATUSDT | 0.1358097 | $3.90M | 510489187 | 2.20 | ACTIVE_TOP_100 |
| 94 | PYTHUSDT | 0.1357771 | $10.47M | 171929280 | 2.14 | ACTIVE_TOP_100 |
| 95 | TRUMPUSDT | 0.1357199 | $341.51M | 28015364 | 4.25 | ACTIVE_TOP_100 |
| 96 | REUSDT | 0.1356297 | $10.62M | 19787959 | 2.12 | ACTIVE_TOP_100 |
| 97 | PNUTUSDT | 0.1355370 | $3.81M | 83296095 | 2.11 | ACTIVE_TOP_100 |
| 98 | MAGICUSDT | 0.1352167 | $6.95M | 35735320 | 2.16 | ACTIVE_TOP_100 |
| 99 | MANTRAUSDT | 0.1352075 | $6.67M | 663063443 | 2.35 | ACTIVE_TOP_100 |
| 100 | HEIUSDT | 0.1349268 | $7.03M | 30090871 | 2.20 | ACTIVE_TOP_100 |
| 101 | SEIUSDT | 0.1347951 | $10.58M | 148811101 | 2.27 | WATCHLIST |
| 102 | CFXUSDT | 0.1345019 | $3.40M | 88663043 | 2.25 | WATCHLIST |
| 103 | PTBUSDT | 0.1344687 | $5.24M | 5219933747 | 3.86 | WATCHLIST |
| 104 | VANAUSDT | 0.1342451 | $1.51M | 1793654 | 2.25 | WATCHLIST |
| 105 | NMRUSDT | 0.1341662 | $1.00M | 155613 | 2.26 | WATCHLIST |
| 106 | LUNA2USDT | 0.1339902 | $1.72M | 28331834 | 2.29 | WATCHLIST |
| 107 | SOPHUSDT | 0.1333711 | $2.15M | 444924586 | 2.51 | WATCHLIST |
| 108 | BLESSUSDT | 0.1331415 | $31.26M | 599925723 | 2.78 | WATCHLIST |
| 109 | GUAUSDT | 0.1329978 | $1.33M | 118359003 | 2.46 | WATCHLIST |
| 110 | GIGGLEUSDT | 0.1328327 | $29.05M | 309037 | 2.63 | WATCHLIST |

```
Score at rank #99  : 0.13520753
Score at rank #100 : 0.13492682
Score at rank #101 : 0.13479512

Gap #99 → #100     : 0.00028071  (0.2076%)
Gap #100 → #101    : 0.0001317  (0.0976%)

```

⚠️ **OBSERVATION**: Very small percentage gap at the #100/#101 boundary. The cutoff could easily shift with minor metric changes.

## 5. Concentration Analysis

Total eligible universe volume: $35.41B

| Tier | Volume % | OI % |
| --- | --- | --- |
| Top 10 | 77.73% | 63.92% |
| Top 25 | 86.19% | 68.81% |
| Top 50 | 89.1% | 71.37% |
| Top 100 | 94.46% | 76.06% |

## 6. Score Component Analysis

**Top 100** — Weights: Vol=0.5, OI=0.35, Spread=0.15

| Component | Mean | Median | Min | Max |
| --- | --- | --- | --- | --- |
| Volume contrib | 0.02 | 0.00 | 0.00 | 0.50 |
| OI contrib | 0.01 | 0.00 | 0.00 | 0.35 |
| Spread contrib | 0.13 | 0.14 | 0.06 | 0.15 |

**Full Universe (397)** — Weights: Vol=0.5, OI=0.35, Spread=0.15

| Component | Mean | Median | Min | Max |
| --- | --- | --- | --- | --- |
| Volume contrib | 0.00 | 0.00 | 0.00 | 0.50 |
| OI contrib | 0.00 | 0.00 | 0.00 | 0.35 |
| Spread contrib | 0.10 | 0.11 | 0.00 | 0.15 |

## 7. Normalization Outlier Analysis

**Volume extremes (top 5 / bottom 5 by raw 24h volume):**

| Direction | Symbol | Raw Volume (USD) |
| --- | --- | --- |
| Top | ETHUSDT | $10.95B |
| Top | BTCUSDT | $10.54B |
| Top | SOLUSDT | $2.55B |
| Top | ZECUSDT | $1.69B |
| Top | XRPUSDT | $1.23B |
| Bottom | ASRUSDT | $0.00B |
| Bottom | AVAUSDT | $0.00B |
| Bottom | SLPUSDT | $0.00B |
| Bottom | CELRUSDT | $0.00B |
| Bottom | CTKUSDT | $0.00B |

**OI extremes (top 5 / bottom 5 by raw open interest):**

| Direction | Symbol | Raw OI |
| --- | --- | --- |
| Top | 1000SATSUSDT | 159717286507 |
| Top | NEIROUSDT | 57889989213 |
| Top | DOGSUSDT | 44347738893 |
| Top | PUMPUSDT | 22809000991 |
| Top | 1000PEPEUSDT | 18353219447 |
| Bottom | XMRUSDT | 101191 |
| Bottom | BSVUSDT | 88053 |
| Bottom | QNTUSDT | 44214 |
| Bottom | PAXGUSDT | 14602 |
| Bottom | XAUTUSDT | 6878 |

**Spread extremes (widest / tightest):**

| Direction | Symbol | Spread bps |
| --- | --- | --- |
| Widest | TAUSDT | 21.25 |
| Widest | CLANKERUSDT | 15.36 |
| Widest | HANAUSDT | 14.97 |
| Widest | CHILLGUYUSDT | 14.67 |
| Widest | PORTALUSDT | 14.02 |
| Tightest | ETHUSDT | 0.04 |
| Tightest | XAUTUSDT | 0.02 |
| Tightest | PAXGUSDT | 0.02 |
| Tightest | BTCUSDT | 0.01 |
| Tightest | USDCUSDT | 0.01 |

```
Volume compression analysis:
  max value            : $10.95B
  p99 value            : $1.25B
  max / p99 ratio      : 8.76x
  % contracts norm < 0.10 : 98.7%
  % contracts norm < 0.05 : 98.5%

OI compression analysis:
  max value            : 159717286507
  p99 value            : 18531450709
  max / p99 ratio      : 8.62x
  % contracts norm < 0.10 : 98.7%

```

## 8. Neutral Spread Audit

Contracts with `spread_bps = None` receive `norm_spread = 0.5` (spread contribution = 0.075).

```
Neutral spread contracts : 0 (0.0% of universe)
Neutral norm_spread      : 0.5
Spread contribution      : 0.075

```

✅ All contracts have valid spread data — no neutral assignments.

Contracts with neutral spread receive exactly 0.0750 spread contribution (= SPREAD_WEIGHT * 0.5 = 0.15 * 0.5). This is mid-range, so they are neither rewarded nor penalized relative to the median spread contract.

## 9. Classification Audit

| Rejection Reason | Count | Sample Symbols |
| --- | --- | --- |
| Non-perpetual (quarterly/delivery) | 184 | XAUUSDT, XAGUSDT, TSLAUSDT, XPTUSDT, XPDUSDT |
| Inactive (not TRADING) | 131 | OMGUSDT, WAVESUSDT, MKRUSDT, DEFIUSDT, BALUSDT |
| Non-USDT quote asset | 43 | ETHBTC, BTCUSDC, ETHUSDC, BNBUSDC, SOLUSDC |
| TradFi (underlyingType blocked) | 2 | BTCDOMUSDT, ALLUSDT |
| TradFi (underlyingSubType blocked) | 126 | KNCUSDT, ZRXUSDT, COMPUSDT, KAVAUSDT, BANDUSDT |
| Other | 0 |  |

**TradFi subtypes found in excluded contracts:**

```
{
  "DeFi": 115,
  "NFT": 11,
  "Index": 2,
  "Alpha": 1
}
```

## 10. Top-100 Composition (Listing Age)

```
BTC/ETH ranks            : {'ETHUSDT': 1, 'BTCUSDT': 2}

Top-100 listing age (days):
  min    : 1
  median : 768
  mean   : 1050.7
  max    : 2548
  unknown: 0

```

**Top-100 age bucket distribution:**

| Age bucket | Top 100 count | Full universe count |
| --- | --- | --- |
| 1-2y | 24 | 134 |
| 1-6m | 6 | 23 |
| 2-4y | 23 | 85 |
| 4y+ | 28 | 73 |
| 6-12m | 18 | 80 |
| <1m | 1 | 2 |

## 11. Sanity Checks

- ✅ `ranks_unique`
- ✅ `ranks_contiguous`
- ✅ `rank_1_has_max_score`
- ✅ `rank_100_score_gt_rank_101`
- ✅ `top_100_exactly_100`
- ✅ `no_duplicate_symbols`
- ✅ `no_excluded_in_top_100`
- ✅ `all_top100_active_status`
- ✅ `all_watchlist_beyond_100`
- ✅ `ranking_is_deterministic`

✅ **All sanity checks PASSED.**

## 12. Snapshot Integrity

```
Snapshot files found          : 1
Latest file                   : data\snapshots\snapshot_20260831.jsonl
Header records in file        : 5
Data records in file          : 1985
Latest batch record count     : 397
Matches eligible count        : True
All headers have timestamp    : True
All data have rank            : True
All data have score           : True
All data have status          : True
Unique snapshot IDs in file   : 5
Append-only verified          : True

```

## 13. Audit Verdict

```
UNIVERSE STATUS: PASS WITH ISSUES
```

### 🟡 Important Issues

1. Volume compression: 99% of contracts have norm_volume < 0.10 due to extreme outliers (max/p99 = 8.76x). Min-max normalization is being significantly distorted by the top 1-2 symbols. Consider log or rank-based normalization in a future revision.

### 🔵 Minor Issues

1. Very small gap (0.0976%) between #100 and #101. A small change in market conditions could cause boundary shuffling.

### 📋 Observations

1. Top-10 contracts represent 77.73% of universe volume and 63.92% of universe OI — high concentration is expected in crypto markets.

---
*Audit generated by `universe/audit.py` — Binance Perpetual Universe Engine V1*