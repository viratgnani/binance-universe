"""
tests/test_contract_filter.py

Unit tests for ContractFilter and parse_exchange_info.

All tests use in-memory data — no Binance API calls.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from universe.contract_filter import ContractFilter, parse_exchange_info
from universe.config import UniverseConfig
from universe.models import ContractInfo


# --------------------------------------------------------------------------- #
#  Helpers
# --------------------------------------------------------------------------- #

FIXTURE_DIR = Path(__file__).parent / "fixtures"


def load_fixture() -> dict:
    with open(FIXTURE_DIR / "exchange_info.json") as fh:
        return json.load(fh)


def make_contract(**overrides) -> ContractInfo:
    """Build a minimal valid BTCUSDT-like ContractInfo with any field overridden."""
    defaults = dict(
        symbol="BTCUSDT",
        base_asset="BTC",
        quote_asset="USDT",
        margin_asset="USDT",
        contract_type="PERPETUAL",
        status="TRADING",
        underlying_type="COIN",
        underlying_sub_type=[],
    )
    defaults.update(overrides)
    return ContractInfo(**defaults)


# --------------------------------------------------------------------------- #
#  parse_exchange_info
# --------------------------------------------------------------------------- #


class TestParseExchangeInfo:
    def test_parses_all_symbols(self):
        raw = load_fixture()
        contracts = parse_exchange_info(raw)
        symbols = {c.symbol for c in contracts}
        assert "BTCUSDT" in symbols
        assert "ETHUSDT" in symbols
        assert "AAAPLUSDT" in symbols  # stock — parsed, filtering happens later

    def test_listing_time_populated(self):
        raw = load_fixture()
        contracts = parse_exchange_info(raw)
        btc = next(c for c in contracts if c.symbol == "BTCUSDT")
        assert btc.listing_time is not None

    def test_underlying_sub_type_parsed(self):
        raw = load_fixture()
        contracts = parse_exchange_info(raw)
        stock = next(c for c in contracts if c.symbol == "AAAPLUSDT")
        assert "STOCK" in stock.underlying_sub_type

    def test_handles_empty_symbols_list(self):
        contracts = parse_exchange_info({"symbols": []})
        assert contracts == []

    def test_skips_malformed_entry(self):
        """A missing required field ('symbol') should not crash the parser."""
        raw = {"symbols": [{"contractType": "PERPETUAL"}]}  # no 'symbol' key
        contracts = parse_exchange_info(raw)
        assert contracts == []


# --------------------------------------------------------------------------- #
#  ContractFilter — Rule 1: contract type
# --------------------------------------------------------------------------- #


class TestContractTypeFilter:
    def test_perpetual_is_eligible(self):
        cf = ContractFilter()
        c = make_contract(contract_type="PERPETUAL")
        result = cf.evaluate(c)
        assert result.eligible

    def test_quarterly_is_rejected(self):
        cf = ContractFilter()
        c = make_contract(symbol="BTCUSDT_250328", contract_type="CURRENT_QUARTER")
        result = cf.evaluate(c)
        assert not result.eligible
        assert "PERPETUAL" in result.reason

    def test_next_quarter_is_rejected(self):
        cf = ContractFilter()
        c = make_contract(contract_type="NEXT_QUARTER")
        result = cf.evaluate(c)
        assert not result.eligible


# --------------------------------------------------------------------------- #
#  ContractFilter — Rule 2: status
# --------------------------------------------------------------------------- #


class TestStatusFilter:
    def test_trading_status_is_eligible(self):
        cf = ContractFilter()
        c = make_contract(status="TRADING")
        result = cf.evaluate(c)
        assert result.eligible

    def test_close_status_is_rejected(self):
        cf = ContractFilter()
        c = make_contract(symbol="OLDCOINUSDT", status="CLOSE")
        result = cf.evaluate(c)
        assert not result.eligible
        assert "TRADING" in result.reason

    def test_settling_status_is_rejected(self):
        cf = ContractFilter()
        c = make_contract(symbol="ETH_SETTLING", status="SETTLING")
        result = cf.evaluate(c)
        assert not result.eligible

    def test_pre_delivering_status_is_rejected(self):
        cf = ContractFilter()
        c = make_contract(status="PRE_DELIVERING")
        result = cf.evaluate(c)
        assert not result.eligible


# --------------------------------------------------------------------------- #
#  ContractFilter — Rule 3: quote asset
# --------------------------------------------------------------------------- #


class TestQuoteAssetFilter:
    def test_usdt_quote_is_eligible(self):
        cf = ContractFilter()
        c = make_contract(quote_asset="USDT")
        assert cf.evaluate(c).eligible

    def test_busd_quote_rejected_when_require_usdt(self):
        cfg = UniverseConfig()
        cfg.REQUIRE_USDT_QUOTE = True
        cf = ContractFilter(cfg)
        c = make_contract(symbol="BTCBUSD", quote_asset="BUSD", margin_asset="BUSD")
        result = cf.evaluate(c)
        assert not result.eligible
        assert "USDT" in result.reason

    def test_busd_quote_allowed_when_require_usdt_false(self):
        cfg = UniverseConfig()
        cfg.REQUIRE_USDT_QUOTE = False
        cf = ContractFilter(cfg)
        c = make_contract(symbol="BTCBUSD", quote_asset="BUSD", margin_asset="BUSD")
        assert cf.evaluate(c).eligible


# --------------------------------------------------------------------------- #
#  ContractFilter — Rule 4: underlying type
# --------------------------------------------------------------------------- #


class TestUnderlyingTypeFilter:
    def test_coin_underlying_is_eligible(self):
        cf = ContractFilter()
        c = make_contract(underlying_type="COIN")
        assert cf.evaluate(c).eligible

    def test_stock_underlying_type_is_rejected(self):
        cf = ContractFilter()
        c = make_contract(
            symbol="AAAPLUSDT",
            underlying_type="STOCK",
            underlying_sub_type=["STOCK"],
        )
        result = cf.evaluate(c)
        assert not result.eligible

    def test_index_underlying_type_is_rejected(self):
        cf = ContractFilter()
        c = make_contract(
            symbol="SP500USDT",
            underlying_type="INDEX",
            underlying_sub_type=["INDEX"],
        )
        result = cf.evaluate(c)
        assert not result.eligible

    def test_absent_underlying_type_passes_through(self):
        """
        If Binance doesn't provide underlyingType, we don't automatically
        exclude — we fall through to the subtype check.
        """
        cf = ContractFilter()
        c = make_contract(underlying_type=None, underlying_sub_type=[])
        result = cf.evaluate(c)
        assert result.eligible


# --------------------------------------------------------------------------- #
#  ContractFilter — Rule 5: underlying subtype
# --------------------------------------------------------------------------- #


class TestUnderlyingSubTypeFilter:
    def test_empty_subtype_is_eligible(self):
        cf = ContractFilter()
        c = make_contract(underlying_sub_type=[])
        assert cf.evaluate(c).eligible

    def test_etf_subtype_is_rejected(self):
        cf = ContractFilter()
        c = make_contract(
            symbol="ETF3XUSDT",
            underlying_type="COIN",   # even if type says COIN
            underlying_sub_type=["ETF"],
        )
        result = cf.evaluate(c)
        assert not result.eligible
        assert "ETF" in result.reason

    def test_defi_subtype_is_rejected(self):
        cf = ContractFilter()
        c = make_contract(underlying_type="COIN", underlying_sub_type=["DEFI"])
        result = cf.evaluate(c)
        assert not result.eligible

    def test_commodity_subtype_is_rejected(self):
        cf = ContractFilter()
        c = make_contract(underlying_type="COIN", underlying_sub_type=["COMMODITY"])
        result = cf.evaluate(c)
        assert not result.eligible

    def test_subtype_check_is_case_insensitive(self):
        """Subtype comparison must be case-insensitive."""
        cf = ContractFilter()
        c = make_contract(underlying_type="COIN", underlying_sub_type=["stock"])
        result = cf.evaluate(c)
        assert not result.eligible

    def test_configurable_blocked_subtypes(self):
        """Adding a custom blocked subtype excludes the contract without code change."""
        cfg = UniverseConfig()
        cfg.BLOCKED_UNDERLYING_SUBTYPES = frozenset({"MYTOKEN"})
        cf = ContractFilter(cfg)
        c = make_contract(underlying_type="COIN", underlying_sub_type=["MYTOKEN"])
        result = cf.evaluate(c)
        assert not result.eligible


# --------------------------------------------------------------------------- #
#  ContractFilter — batch filtering
# --------------------------------------------------------------------------- #


class TestFilterBatch:
    def test_full_fixture_filtering(self):
        """
        Run the full fixture through the filter.

        Expected eligible from fixture:
          BTCUSDT, ETHUSDT, SOLUSDT, ADAUSDT, XRPUSDT  (5 valid crypto perps)

        Expected excluded:
          BTCUSDT_250328  — quarterly
          AAAPLUSDT       — stock underlying
          SP500USDT       — index underlying
          DEFIUSDT        — DeFi subtype
          BTCBUSD         — non-USDT quote
          OLDCOINUSDT     — status=CLOSE
          ETHUSDT_SETTLING — status=SETTLING
        """
        raw = load_fixture()
        contracts = parse_exchange_info(raw)
        cf = ContractFilter()
        eligible, rejected = cf.filter_batch(contracts)

        eligible_symbols = {c.symbol for c in eligible}
        rejected_symbols = {r.symbol for r in rejected}

        assert "BTCUSDT" in eligible_symbols
        assert "ETHUSDT" in eligible_symbols
        assert "SOLUSDT" in eligible_symbols
        assert "ADAUSDT" in eligible_symbols
        assert "XRPUSDT" in eligible_symbols

        assert "BTCUSDT_250328" in rejected_symbols
        assert "AAAPLUSDT" in rejected_symbols
        assert "SP500USDT" in rejected_symbols
        assert "DEFIUSDT" in rejected_symbols
        assert "BTCBUSD" in rejected_symbols
        assert "OLDCOINUSDT" in rejected_symbols
        assert "ETHUSDT_SETTLING" in rejected_symbols

    def test_empty_input(self):
        cf = ContractFilter()
        eligible, rejected = cf.filter_batch([])
        assert eligible == []
        assert rejected == []
