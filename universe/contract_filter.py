"""
universe/contract_filter.py

Eligibility rules that decide which Binance perpetual contracts enter the
master universe.

Design principles:
  - No Binance API calls here — this module only inspects ContractInfo objects.
  - No hardcoded symbol lists — all rules derive from contract metadata.
  - New categories can be excluded by adding to config.BLOCKED_UNDERLYING_SUBTYPES.
  - Every rejection is accompanied by a reason string for auditability.

Filter pipeline (applied in order):
  1. contractType == "PERPETUAL"
  2. status == "TRADING"
  3. quote_asset filter (USDT-only when config.REQUIRE_USDT_QUOTE is True)
  4. underlyingType filter  (must be "COIN" if field is present)
  5. underlyingSubType filter (must not contain any blocked subtype)
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from universe.config import UniverseConfig, config as default_config
from universe.models import ContractInfo

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class FilterResult:
    """Outcome of running one contract through the filter pipeline."""

    symbol: str
    eligible: bool
    reason: str  # Human-readable reason for eligibility or rejection


class ContractFilter:
    """
    Stateless filter that evaluates ContractInfo objects against the configured
    eligibility rules.

    All configuration comes from a :class:`UniverseConfig` instance so the
    filter behaviour can be adjusted without touching this file.
    """

    def __init__(self, cfg: UniverseConfig = default_config) -> None:
        self._cfg = cfg

    # ------------------------------------------------------------------ #
    #  Public interface
    # ------------------------------------------------------------------ #

    def evaluate(self, contract: ContractInfo) -> FilterResult:
        """
        Run a single contract through the eligibility pipeline.

        Returns a :class:`FilterResult` describing whether the contract is
        eligible and, if not, why it was rejected.
        """
        # Rule 1 — must be a perpetual futures contract
        if contract.contract_type != "PERPETUAL":
            return FilterResult(
                symbol=contract.symbol,
                eligible=False,
                reason=f"contract_type={contract.contract_type!r} (not PERPETUAL)",
            )

        # Rule 2 — must be actively trading
        if contract.status != "TRADING":
            return FilterResult(
                symbol=contract.symbol,
                eligible=False,
                reason=f"status={contract.status!r} (not TRADING)",
            )

        # Rule 3 — quote asset filter
        if self._cfg.REQUIRE_USDT_QUOTE and contract.quote_asset != "USDT":
            return FilterResult(
                symbol=contract.symbol,
                eligible=False,
                reason=f"quote_asset={contract.quote_asset!r} (not USDT)",
            )

        # Rule 4 — underlying type must be crypto-native (if the field exists)
        if contract.underlying_type is not None:
            if contract.underlying_type not in self._cfg.ALLOWED_UNDERLYING_TYPES:
                return FilterResult(
                    symbol=contract.symbol,
                    eligible=False,
                    reason=(
                        f"underlyingType={contract.underlying_type!r} "
                        f"(not in allowed types: {self._cfg.ALLOWED_UNDERLYING_TYPES})"
                    ),
                )
        else:
            # Binance may not populate this field on all contracts.
            # Log a warning but do not automatically exclude — we fall through
            # to the subtype check which is more specific.
            logger.debug(
                "%s: underlyingType field absent — relying on subtype check only",
                contract.symbol,
            )

        # Rule 5 — no blocked underlying subtypes
        blocked = self._cfg.BLOCKED_UNDERLYING_SUBTYPES
        contract_subtypes = {s.upper() for s in contract.underlying_sub_type}
        blocked_found = contract_subtypes & {b.upper() for b in blocked}
        if blocked_found:
            return FilterResult(
                symbol=contract.symbol,
                eligible=False,
                reason=f"underlyingSubType contains blocked category: {blocked_found}",
            )

        return FilterResult(symbol=contract.symbol, eligible=True, reason="OK")

    def filter_batch(
        self, contracts: list[ContractInfo]
    ) -> tuple[list[ContractInfo], list[FilterResult]]:
        """
        Filter a list of contracts.

        Returns:
            eligible  — contracts that passed all rules
            rejected  — FilterResult objects for contracts that did not pass
        """
        eligible: list[ContractInfo] = []
        rejected: list[FilterResult] = []

        for contract in contracts:
            result = self.evaluate(contract)
            if result.eligible:
                eligible.append(contract)
            else:
                rejected.append(result)
                logger.debug(
                    "Excluded %s: %s", contract.symbol, result.reason
                )

        logger.info(
            "Contract filter: %d eligible, %d excluded (from %d total)",
            len(eligible),
            len(rejected),
            len(contracts),
        )
        return eligible, rejected


# --------------------------------------------------------------------------- #
#  Exchange-info parser (converts raw Binance dict → ContractInfo)
# --------------------------------------------------------------------------- #


def parse_exchange_info(raw: dict) -> list[ContractInfo]:
    """
    Convert the raw /fapi/v1/exchangeInfo response into a list of ContractInfo
    objects.

    Unrecognised or malformed symbol entries are skipped with a warning rather
    than crashing the whole refresh.
    """
    symbols_raw: list[dict] = raw.get("symbols", [])
    contracts: list[ContractInfo] = []

    for entry in symbols_raw:
        try:
            listing_ms: int | None = entry.get("onboardDate") or entry.get("listingDate")
            listing_dt = None
            if listing_ms:
                from datetime import datetime, timezone
                listing_dt = datetime.fromtimestamp(listing_ms / 1000, tz=timezone.utc)

            contract = ContractInfo(
                symbol=entry["symbol"],
                base_asset=entry.get("baseAsset", ""),
                quote_asset=entry.get("quoteAsset", ""),
                margin_asset=entry.get("marginAsset", ""),
                contract_type=entry.get("contractType", ""),
                status=entry.get("status", ""),
                listing_time=listing_dt,
                underlying_type=entry.get("underlyingType"),
                underlying_sub_type=entry.get("underlyingSubType", []),
                raw=entry,
            )
            contracts.append(contract)
        except (KeyError, ValueError) as exc:
            logger.warning(
                "Skipping malformed exchange info entry %s: %s",
                entry.get("symbol", "<unknown>"),
                exc,
            )

    logger.info("Parsed %d contracts from exchange info", len(contracts))
    return contracts
