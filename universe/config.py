"""
universe/config.py

Single source of truth for all configurable constants.

To override values without editing this file, subclass or monkey-patch
`UniverseConfig` before calling `run_refresh()`, or pass a custom config
object once the interface supports it.

DO NOT scatter magic numbers throughout the codebase — add them here.
"""

from __future__ import annotations

from pathlib import Path


class UniverseConfig:
    # ------------------------------------------------------------------ #
    #  Universe selection
    # ------------------------------------------------------------------ #

    # Number of top-ranked contracts promoted to ACTIVE_TOP_100 status.
    TOP_N: int = 100

    # ------------------------------------------------------------------ #
    #  Ranking weights
    #
    #  Weights must sum to 1.0 — validated at startup in ranking_engine.py.
    #
    #  Scoring formula (documented fully in ranking_engine.py):
    #
    #    score = VOLUME_WEIGHT  * norm_volume_24h_quote
    #          + OI_WEIGHT      * norm_open_interest
    #          + SPREAD_WEIGHT  * (1 - norm_spread_bps)   ← inverted: lower spread = better
    # ------------------------------------------------------------------ #

    VOLUME_WEIGHT: float = 0.50
    OI_WEIGHT: float = 0.35
    SPREAD_WEIGHT: float = 0.15

    # ------------------------------------------------------------------ #
    #  Normalization method
    #
    #  V1.1: "log_minmax" — log1p(volume, OI) then min-max.
    #        Resolves the extreme-outlier compression identified in the V1
    #        audit: 98.7% of contracts had norm_volume < 0.10 under plain
    #        min-max due to BTC/ETH dominance.
    #
    #  Valid values (must match NormalizerBase.name):
    #    "minmax"          — V1 baseline (plain min-max)
    #    "log_minmax"      — V1.1 production (log1p + min-max)
    #    "percentile"      — evaluated in V1.1 experiment, rejected
    #    "winsorized_p1_p99" — evaluated in V1.1 experiment, rejected
    # ------------------------------------------------------------------ #

    NORMALIZATION_METHOD: str = "log_minmax"

    # ------------------------------------------------------------------ #
    #  Contract filtering
    # ------------------------------------------------------------------ #

    # Binance underlyingSubType values that mark a contract as non-crypto.
    # Add new categories here without changing any other code.
    BLOCKED_UNDERLYING_SUBTYPES: frozenset[str] = frozenset(
        {
            "INDEX",
            "ETF",
            "STOCK",
            "COMMODITY",
            "LEVERAGED",
            "DEFI",        # DeFi index products (not individual crypto assets)
            "NFT",         # NFT index products
        }
    )

    # If True, only include USDT-quoted contracts (excludes BUSD, USDC, etc.).
    # Set False to include all stablecoin-margined perpetuals.
    REQUIRE_USDT_QUOTE: bool = True

    # underlyingType values that are considered crypto-native.
    # Contracts whose underlyingType is NOT in this set are excluded
    # if Binance provides the field.
    ALLOWED_UNDERLYING_TYPES: frozenset[str] = frozenset({"COIN"})

    # ------------------------------------------------------------------ #
    #  Binance API
    # ------------------------------------------------------------------ #

    BINANCE_FAPI_BASE_URL: str = "https://fapi.binance.com"

    # Seconds before an individual HTTP request is timed out.
    REQUEST_TIMEOUT_SECONDS: float = 15.0

    # Maximum number of concurrent open-interest requests.
    # Binance fapi IP weight: 1 per OI call.  Keep well under the 2400/min limit.
    OI_CONCURRENCY_LIMIT: int = 20

    # ------------------------------------------------------------------ #
    #  Snapshot persistence
    # ------------------------------------------------------------------ #

    # Directory where daily JSONL snapshot files are written.
    SNAPSHOT_DIR: Path = Path("data/snapshots")

    # ------------------------------------------------------------------ #
    #  Logging
    # ------------------------------------------------------------------ #

    # Number of top-ranked contracts printed in the summary log.
    LOG_TOP_N_SUMMARY: int = 20


# Module-level singleton — import this everywhere instead of instantiating
# a new object each time.
config = UniverseConfig()
