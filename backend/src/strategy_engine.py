"""
Aethra Finance - transparent yield data normalization and risk scoring.

This module reads public yield data, normalizes it for the static dashboard,
and assigns explainable risk indicators. It does not trade, rebalance, custody
assets, recommend deposits, or guarantee returns.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
import argparse
import json
import math
from pathlib import Path
import sys
from typing import Any, Iterable
from urllib.request import Request, urlopen


DEFILLAMA_POOLS_URL = "https://yields.llama.fi/pools"
DEFILLAMA_YIELDS_UI = "https://defillama.com/yields"
PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_OUTPUT = PROJECT_ROOT / "data" / "opportunities.json"
DEFAULT_CANDIDATE = PROJECT_ROOT / "data" / "refresh-candidate.json"
DEFAULT_FRONTEND = PROJECT_ROOT / "frontend" / "index.html"
DEFAULT_SOURCE_REVIEW_MATRIX_DIR = PROJECT_ROOT / "docs" / "reviews"
SELECTION_BASELINE_POLICY = "Prefer currently reviewed pool ids when they still satisfy source filters"
STALE_AFTER_HOURS = 24
APY_REVIEW_DELTA = 0.5
TVL_REVIEW_DELTA_RATIO = 0.10
TVL_REVIEW_DELTA_USD = 50_000_000
APY_COMPOSITIONS = {"base", "base_plus_rewards", "rewards_only", "farming_pool", "unknown"}

SUPPORTED_CHAINS = {"Ethereum", "Arbitrum", "Optimism", "Base", "Polygon"}
SUPPORTED_ASSETS = {
    "USDC",
    "USDT",
    "DAI",
    "USDS",
    "SUSDS",
    "ETH",
    "WETH",
    "STETH",
    "WSTETH",
    "WEETH",
}

REQUIRED_OPPORTUNITY_FIELDS = {
    "id",
    "chain",
    "protocol",
    "asset",
    "strategy",
    "apy",
    "tvl",
    "updated",
    "source",
    "source_label",
    "contract",
    "contract_address",
    "contract_role",
    "contract_verification",
    "audit",
    "factors",
    "pool_reference",
    "pool_verification",
    "apy_source_label",
    "apy_composition",
    "score",
    "risk",
    "score_reasons",
}


@dataclass(frozen=True)
class ProtocolMetadata:
    protocol_url: str = ""
    docs_url: str = ""
    security_url: str = ""
    risk_notes: tuple[str, ...] = ()


@dataclass(frozen=True)
class YieldOpportunity:
    id: str
    chain: str
    protocol: str
    asset: str
    strategy: str
    apy: float
    tvl: float
    updated: str
    source: str
    source_label: str
    contract: str
    contract_address: str
    contract_verification: str
    audit: str
    factors: tuple[str, ...]
    contract_role: str = ""
    bridge_dependency: bool = False
    verified: bool = False
    source_pool_id: str | None = None
    pool_reference: str = ""
    pool_verification: str = ""
    apy_base: float | None = None
    apy_reward: float | None = None
    apy_source_label: str = "APY source not captured in this snapshot"
    apy_composition: str = "unknown"
    pool_meta: str = ""
    reward_tokens: tuple[str, ...] = ()
    pool_url: str = ""
    explorer_url: str = ""
    related_contracts: tuple[dict[str, str], ...] = ()
    verification_sources: tuple[dict[str, str], ...] = ()
    protocol_url: str = ""
    docs_url: str = ""
    security_url: str = ""
    risk_notes: tuple[str, ...] = ()


@dataclass(frozen=True)
class ScoredOpportunity:
    opportunity: YieldOpportunity
    score: int
    risk: str
    score_reasons: tuple[str, ...]


PROTOCOL_METADATA = {
    "aave": ProtocolMetadata(
        protocol_url="https://app.aave.com/",
        docs_url="https://aave.com/docs",
        security_url="https://github.com/aave-dao/aave-v3-origin/tree/main/audits",
        risk_notes=(
            "Aave positions depend on oracle pricing, liquidation parameters, interest-rate curves, and governance-controlled market settings",
            "Supplying assets does not remove smart contract, bad-debt, asset issuer, or market liquidity risk",
        ),
    ),
    "centrifuge": ProtocolMetadata(
        protocol_url="https://centrifuge.io/",
        docs_url="https://docs.centrifuge.io/",
        security_url="https://docs.centrifuge.io/developer/protocol/security/",
        risk_notes=(
            "Centrifuge exposure can include tokenized real-world asset, permissioning, issuer, legal, and redemption-cycle risk",
            "Pool liquidity and underlying asset valuation should be checked before treating APY as comparable to simple money-market yield",
        ),
    ),
    "ether.fi": ProtocolMetadata(
        protocol_url="https://ether.fi/",
        docs_url="https://etherfi.gitbook.io/etherfi/",
        security_url="https://etherfi.gitbook.io/etherfi/security/audits",
        risk_notes=(
            "Liquid restaking exposure can include validator, operator, withdrawal, slashing, and restaking-layer risk",
            "Token rewards and restaking incentives can change and may not represent durable base yield",
        ),
    ),
    "lido": ProtocolMetadata(
        protocol_url="https://stake.lido.fi/",
        docs_url="https://docs.lido.fi/",
        security_url="https://docs.lido.fi/security/audits/",
        risk_notes=(
            "Liquid staking exposure can include validator performance, oracle, withdrawal queue, governance, and stETH liquidity risk",
            "stETH and wrapped variants can trade away from ETH under stressed market conditions",
        ),
    ),
    "maple": ProtocolMetadata(
        protocol_url="https://maple.finance/",
        docs_url="https://docs.maple.finance/",
        security_url="https://docs.maple.finance/technical-resources/security/security",
        risk_notes=(
            "Maple pools can include borrower credit, collateral, pool delegate, withdrawal, and real-world counterparty risk",
            "Private credit or institutional lending yield should not be compared with overcollateralized lending without reading pool terms",
        ),
    ),
    "sky": ProtocolMetadata(
        protocol_url="https://sky.money/",
        docs_url="https://developers.sky.money/guides/",
        security_url="https://developers.sky.money/guides/",
        risk_notes=(
            "Sky-linked savings exposure depends on USDS mechanics, governance-set rates, collateral composition, and protocol accounting",
            "Stablecoin savings products still carry issuer, peg, governance, and underlying collateral risk",
        ),
    ),
    "spark": ProtocolMetadata(
        protocol_url="https://spark.fi/",
        docs_url="https://docs.spark.fi/",
        security_url="https://spark.fi/",
        risk_notes=(
            "Spark savings exposure can depend on Sky rates, Spark allocation strategy, bridge deployment, and the backing of accepted assets",
            "Official Spark materials should be checked for current audit report scope, bug bounty coverage, and product-specific withdrawal rules",
        ),
    ),
}

PROTOCOL_ALIASES = {
    "aave": "aave",
    "centrifuge": "centrifuge",
    "ether.fi": "ether.fi",
    "etherfi": "ether.fi",
    "lido": "lido",
    "maple": "maple",
    "sky": "sky",
    "spark": "spark",
    "sparklend": "spark",
}

MANUAL_CONTRACT_VERIFICATIONS: tuple[dict[str, Any], ...] = (
    {
        "chain": "Ethereum",
        "protocol_contains": "lido",
        "assets": ("STETH",),
        "contract_address": "0xae7ab96520DE3A18E5e111B5EaAb095312D7fE84",
        "contract_role": "Lido and stETH token proxy",
        "explorer_url": "https://etherscan.io/address/0xae7ab96520DE3A18E5e111B5EaAb095312D7fE84",
        "pool_url": "https://stake.lido.fi/",
        "contract_verification": (
            "Manually matched to the official Lido deployed contracts page on 2026-07-24. "
            "This identifies the Lido/stETH token proxy; it is not a claim that APY, TVL, or audit scope is verified by Aethra."
        ),
        "verification_sources": (
            {"label": "Lido deployed contracts", "url": "https://docs.lido.fi/deployed-contracts/"},
            {"label": "Etherscan address", "url": "https://etherscan.io/address/0xae7ab96520DE3A18E5e111B5EaAb095312D7fE84"},
        ),
        "related_contracts": (),
    },
    {
        "chain": "Ethereum",
        "protocol_contains": "sky",
        "assets": ("SUSDS",),
        "contract_address": "0xa3931d71877C0E7a3148CB7Eb4463524FEc27fbD",
        "contract_role": "sUSDS ERC-4626 token and vault proxy",
        "explorer_url": "https://etherscan.io/address/0xa3931d71877C0E7a3148CB7Eb4463524FEc27fbD",
        "pool_url": "https://sky.money/susds",
        "contract_verification": (
            "Manually matched to official Sky documentation on 2026-07-24. "
            "This identifies the sUSDS token/vault proxy; it is not a claim that APY, TVL, or audit scope is verified by Aethra."
        ),
        "verification_sources": (
            {"label": "Sky sUSDS docs", "url": "https://developers.skyeco.com/protocol/tokens/susds/"},
            {"label": "Sky Base bridge token table", "url": "https://developers.skyeco.com/guides/skylink/base-eth-native-bridge/"},
            {"label": "Etherscan address", "url": "https://etherscan.io/address/0xa3931d71877C0E7a3148CB7Eb4463524FEc27fbD"},
        ),
        "related_contracts": (),
    },
    {
        "chain": "Arbitrum",
        "protocol_contains": "sky",
        "assets": ("SUSDS",),
        "source_pool_ids": ("3637ce7b-529b-49c1-964c-710a50b2939c",),
        "contract_address": "0xdDb46999F8891663a8F2828d25298f70416d7610",
        "contract_role": "Arbitrum sUSDS savings token contract",
        "explorer_url": "https://arbiscan.io/address/0xdDb46999F8891663a8F2828d25298f70416d7610",
        "pool_url": "https://defillama.com/yields/pool/3637ce7b-529b-49c1-964c-710a50b2939c",
        "contract_verification": (
            "Manually matched the exact DeFiLlama pool token to the Sky-labeled sUSDS token contract on Arbitrum on 2026-07-26. "
            "This identifies the Arbitrum sUSDS token contract; it does not verify APY, TVL, rate propagation, bridge assumptions, redeemability, liquidity, or audit scope."
        ),
        "verification_sources": (
            {"label": "DeFiLlama exact pool page", "url": "https://defillama.com/yields/pool/3637ce7b-529b-49c1-964c-710a50b2939c"},
            {"label": "Sky sUSDS docs", "url": "https://developers.skyeco.com/protocol/tokens/susds/"},
            {"label": "Arbitrum Sky gateway proposal", "url": "https://forum.arbitrum.foundation/t/constitutional-proposal-for-arbitrum-dao-to-register-the-sky-custom-gateway-contracts-in-the-router/28617?page=4"},
            {"label": "Arbiscan address", "url": "https://arbiscan.io/address/0xdDb46999F8891663a8F2828d25298f70416d7610"},
        ),
        "related_contracts": (
            {
                "label": "USDS",
                "role": "Underlying asset token on Arbitrum",
                "address": "0x6491c05A82219b8D1479057361ff1654749b876b",
                "explorer_url": "https://arbiscan.io/address/0x6491c05A82219b8D1479057361ff1654749b876b",
            },
        ),
    },
    {
        "chain": "Ethereum",
        "protocol_contains": "ether.fi",
        "assets": ("WEETH",),
        "contract_address": "0xCd5fE23C85820F7B72D0926FC9b05b43E359b7ee",
        "contract_role": "weETH ERC-20 liquid restaking token",
        "explorer_url": "https://etherscan.io/address/0xCd5fE23C85820F7B72D0926FC9b05b43E359b7ee",
        "pool_url": "https://www.ether.fi/app/weeth",
        "contract_verification": (
            "Manually matched to the official ether.fi deployed contracts page on 2026-07-24. "
            "This identifies the weETH token contract and related protocol contracts; it is not a claim that APY, TVL, liquidity, redemption behavior, or audit scope is verified by Aethra."
        ),
        "verification_sources": (
            {"label": "ether.fi deployed contracts", "url": "https://etherfi.gitbook.io/etherfi/contracts-and-integrations/deployed-contracts"},
            {"label": "Etherscan address", "url": "https://etherscan.io/address/0xCd5fE23C85820F7B72D0926FC9b05b43E359b7ee"},
        ),
        "related_contracts": (
            {
                "label": "eETH",
                "role": "ether.fi liquid staking token related to weETH wrapping",
                "address": "0x35fA164735182de50811E8e2E824cFb9B6118ac2",
                "explorer_url": "https://etherscan.io/address/0x35fA164735182de50811E8e2E824cFb9B6118ac2",
            },
            {
                "label": "Liquidity Pool",
                "role": "ether.fi mainnet liquidity pool contract",
                "address": "0x308861A430be4cce5502d0A12724771Fc6DaF216",
                "explorer_url": "https://etherscan.io/address/0x308861A430be4cce5502d0A12724771Fc6DaF216",
            },
        ),
    },
    {
        "chain": "Ethereum",
        "protocol_contains": "aave",
        "assets": ("WETH",),
        "contract_address": "0x87870Bca3F3fD6335C3F4ce8392D69350B4fA4E2",
        "contract_role": "Aave V3 Ethereum Pool proxy, shared by multiple reserves",
        "explorer_url": "https://etherscan.io/address/0x87870Bca3F3fD6335C3F4ce8392D69350B4fA4E2",
        "pool_url": "https://app.aave.com/",
        "contract_verification": (
            "Manually matched to Aave address-book and Aave governance references on 2026-07-24. "
            "This is the market-level Pool proxy. The related-contracts section lists the WETH reserve's aToken and underlying token; none of these fields verify APY, TVL, or audit scope."
        ),
        "verification_sources": (
            {"label": "Aave address-book", "url": "https://www.npmjs.com/package/@aave-dao/aave-address-book"},
            {"label": "Aave tokenlist", "url": "https://github.com/aave-dao/aave-address-book/blob/main/tokenlist.json"},
            {"label": "Aave governance deployment reference", "url": "https://governance.aave.com/t/bgd-aave-v3-ethereum-new-deployment-vs-aave-v2-upgrade/9990?page=2"},
            {"label": "Etherscan address", "url": "https://etherscan.io/address/0x87870Bca3F3fD6335C3F4ce8392D69350B4fA4E2"},
        ),
        "related_contracts": (
            {
                "label": "aEthWETH",
                "role": "Aave V3 Ethereum aToken for supplied WETH",
                "address": "0x4d5F47FA6A74757f35C14fD3a6Ef8E3C9BC514E8",
                "explorer_url": "https://etherscan.io/address/0x4d5F47FA6A74757f35C14fD3a6Ef8E3C9BC514E8",
            },
            {
                "label": "WETH",
                "role": "Underlying reserve asset",
                "address": "0xC02aaA39b223FE8D0A0e5C4F27eAD9083C756Cc2",
                "explorer_url": "https://etherscan.io/address/0xC02aaA39b223FE8D0A0e5C4F27eAD9083C756Cc2",
            },
        ),
    },
    {
        "chain": "Ethereum",
        "protocol_contains": "aave",
        "assets": ("USDT",),
        "contract_address": "0x87870Bca3F3fD6335C3F4ce8392D69350B4fA4E2",
        "contract_role": "Aave V3 Ethereum Pool proxy, shared by multiple reserves",
        "explorer_url": "https://etherscan.io/address/0x87870Bca3F3fD6335C3F4ce8392D69350B4fA4E2",
        "pool_url": "https://app.aave.com/",
        "contract_verification": (
            "Manually matched to Aave address-book and Aave governance references on 2026-07-24. "
            "This is the market-level Pool proxy. The related-contracts section lists the USDT reserve's aToken and underlying token; none of these fields verify APY, TVL, or audit scope."
        ),
        "verification_sources": (
            {"label": "Aave address-book", "url": "https://www.npmjs.com/package/@aave-dao/aave-address-book"},
            {"label": "Aave tokenlist", "url": "https://github.com/aave-dao/aave-address-book/blob/main/tokenlist.json"},
            {"label": "Aave governance deployment reference", "url": "https://governance.aave.com/t/bgd-aave-v3-ethereum-new-deployment-vs-aave-v2-upgrade/9990?page=2"},
            {"label": "Etherscan address", "url": "https://etherscan.io/address/0x87870Bca3F3fD6335C3F4ce8392D69350B4fA4E2"},
        ),
        "related_contracts": (
            {
                "label": "aEthUSDT",
                "role": "Aave V3 Ethereum aToken for supplied USDT",
                "address": "0x23878914EFE38d27C4D67Ab83ed1b93A74D4086a",
                "explorer_url": "https://etherscan.io/address/0x23878914EFE38d27C4D67Ab83ed1b93A74D4086a",
            },
            {
                "label": "USDT",
                "role": "Underlying reserve asset",
                "address": "0xdAC17F958D2ee523a2206206994597C13D831ec7",
                "explorer_url": "https://etherscan.io/address/0xdAC17F958D2ee523a2206206994597C13D831ec7",
            },
        ),
    },
    {
        "chain": "Arbitrum",
        "protocol_contains": "spark savings",
        "assets": ("USDS",),
        "source_pool_ids": ("9d499222-a01a-45bb-bbc9-f01c7923693b",),
        "contract_address": "0xdDb46999F8891663a8F2828d25298f70416d7610",
        "contract_role": "Arbitrum sUSDS savings token contract",
        "explorer_url": "https://arbiscan.io/address/0xdDb46999F8891663a8F2828d25298f70416d7610",
        "pool_url": "https://defillama.com/yields/pool/9d499222-a01a-45bb-bbc9-f01c7923693b",
        "contract_verification": (
            "Manually matched the exact DeFiLlama pool token to the SUSDS constant in Spark's official Arbitrum address registry on 2026-07-24. "
            "This identifies the Arbitrum sUSDS token contract; it does not verify APY, TVL, rate propagation, bridge assumptions, redeemability, liquidity, or audit scope."
        ),
        "verification_sources": (
            {
                "label": "DeFiLlama exact pool page",
                "url": "https://defillama.com/yields/pool/9d499222-a01a-45bb-bbc9-f01c7923693b",
            },
            {"label": "Spark deployments docs", "url": "https://docs.spark.fi/dev/deployments/"},
            {
                "label": "Spark Arbitrum address registry",
                "url": "https://github.com/sparkdotfi/spark-address-registry/blob/master/src/Arbitrum.sol",
            },
            {
                "label": "Arbiscan address",
                "url": "https://arbiscan.io/address/0xdDb46999F8891663a8F2828d25298f70416d7610",
            },
        ),
        "related_contracts": (
            {
                "label": "USDS",
                "role": "Underlying asset token on Arbitrum",
                "address": "0x6491c05A82219b8D1479057361ff1654749b876b",
                "explorer_url": "https://arbiscan.io/address/0x6491c05A82219b8D1479057361ff1654749b876b",
            },
        ),
    },
    {
        "chain": "Ethereum",
        "protocol_contains": "spark savings",
        "assets": ("USDT",),
        "contract_address": "0xe2e7a17dFf93280dec073C995595155283e3C372",
        "contract_role": "Spark Vault V2 spUSDT ERC-4626 vault proxy",
        "explorer_url": "https://etherscan.io/address/0xe2e7a17dFf93280dec073C995595155283e3C372",
        "pool_url": "https://app.spark.fi/",
        "contract_verification": (
            "Manually matched to Spark's official vault docs and Spark Address Registry on 2026-07-24. "
            "This identifies the mainnet spUSDT vault proxy; it does not verify APY, TVL, withdrawal liquidity, intents fulfillment, or audit scope."
        ),
        "verification_sources": (
            {"label": "Spark Vaults smart contracts", "url": "https://docs.spark.fi/integrators/spark-vaults-v2"},
            {"label": "Spark deployments docs", "url": "https://docs.spark.fi/dev/deployments/"},
            {"label": "Spark Ethereum address registry", "url": "https://github.com/sparkdotfi/spark-address-registry/blob/master/src/Ethereum.sol"},
            {"label": "Etherscan address", "url": "https://etherscan.io/address/0xe2e7a17dFf93280dec073C995595155283e3C372"},
        ),
        "related_contracts": (
            {
                "label": "USDT",
                "role": "Underlying vault asset",
                "address": "0xdAC17F958D2ee523a2206206994597C13D831ec7",
                "explorer_url": "https://etherscan.io/address/0xdAC17F958D2ee523a2206206994597C13D831ec7",
            },
            {
                "label": "SavingsVaultIntents",
                "role": "Mainnet intent contract for large Spark Savings vault withdrawals",
                "address": "0x592B7DB9906E6f8924C4D74c2A0aB86CE44fDDDf",
                "explorer_url": "https://etherscan.io/address/0x592B7DB9906E6f8924C4D74c2A0aB86CE44fDDDf",
            },
        ),
    },
    {
        "chain": "Ethereum",
        "protocol_contains": "sparklend",
        "assets": ("USDS",),
        "contract_address": "0xC13e21B648A5Ee794902342038FF3aDAB66BE987",
        "contract_role": "SparkLend Pool proxy, shared by multiple reserves",
        "explorer_url": "https://etherscan.io/address/0xC13e21B648A5Ee794902342038FF3aDAB66BE987",
        "pool_url": "https://app.spark.fi/",
        "contract_verification": (
            "Manually matched to the Spark Address Registry on 2026-07-24. "
            "This is the SparkLend market-level Pool proxy. The related-contracts section lists the USDS reserve's spToken, debt token, and underlying token; none of these fields verify APY, TVL, reserve parameters, liquidity, or audit scope."
        ),
        "verification_sources": (
            {"label": "Spark deployments docs", "url": "https://docs.spark.fi/dev/deployments/"},
            {"label": "SparkLend address registry", "url": "https://github.com/sparkdotfi/spark-address-registry/blob/master/src/SparkLend.sol"},
            {"label": "Spark Ethereum address registry", "url": "https://github.com/sparkdotfi/spark-address-registry/blob/master/src/Ethereum.sol"},
            {"label": "Etherscan address", "url": "https://etherscan.io/address/0xC13e21B648A5Ee794902342038FF3aDAB66BE987"},
        ),
        "related_contracts": (
            {
                "label": "USDS spToken",
                "role": "SparkLend supplied USDS position token",
                "address": "0xC02aB1A5eaA8d1B114EF786D9bde108cD4364359",
                "explorer_url": "https://etherscan.io/address/0xC02aB1A5eaA8d1B114EF786D9bde108cD4364359",
            },
            {
                "label": "USDS debt token",
                "role": "SparkLend variable debt token for borrowed USDS",
                "address": "0x8c147debea24Fb98ade8dDa4bf142992928b449e",
                "explorer_url": "https://etherscan.io/address/0x8c147debea24Fb98ade8dDa4bf142992928b449e",
            },
            {
                "label": "USDS",
                "role": "Underlying reserve asset",
                "address": "0xdC035D45d973E3EC169d2276DDab16f1e407384F",
                "explorer_url": "https://etherscan.io/address/0xdC035D45d973E3EC169d2276DDab16f1e407384F",
            },
        ),
    },
    {
        "chain": "Ethereum",
        "protocol_contains": "maple",
        "assets": ("USDC",),
        "source_pool_ids": ("43641cf5-a92e-416b-bce9-27113d3c0db6",),
        "contract_address": "0x80ac24aA929eaF5013f6436cdA2a7ba190f5Cc0b",
        "contract_role": "Maple Syrup USDC pool contract",
        "explorer_url": "https://etherscan.io/address/0x80ac24aA929eaF5013f6436cdA2a7ba190f5Cc0b",
        "pool_url": "https://app.maple.finance/earn",
        "contract_verification": (
            "Manually matched to DeFiLlama poolMeta 'Syrup USDC' and official Syrup addresses on 2026-07-24. "
            "This identifies the Syrup USDC pool contract; it does not verify APY, TVL, borrower credit quality, collateral, withdrawal queue timing, or audit scope."
        ),
        "verification_sources": (
            {"label": "Syrup addresses", "url": "https://syrup.gitbook.io/syrup/technical-resources/addresses"},
            {"label": "Maple integration docs", "url": "https://docs.maple.finance/integrate/get-started"},
            {"label": "Maple withdrawal docs", "url": "https://docs.maple.finance/syrupusdc-for-lenders/risk"},
            {"label": "Etherscan address", "url": "https://etherscan.io/address/0x80ac24aA929eaF5013f6436cdA2a7ba190f5Cc0b"},
        ),
        "related_contracts": (
            {
                "label": "USDC",
                "role": "Underlying pool asset",
                "address": "0xA0b86991c6218b36c1d19D4a2e9Eb0cE3606eB48",
                "explorer_url": "https://etherscan.io/address/0xA0b86991c6218b36c1d19D4a2e9Eb0cE3606eB48",
            },
            {
                "label": "PoolManager",
                "role": "Syrup USDC pool manager",
                "address": "0x7aD5fFa5fdF509E30186F4609c2f6269f4B6158F",
                "explorer_url": "https://etherscan.io/address/0x7aD5fFa5fdF509E30186F4609c2f6269f4B6158F",
            },
            {
                "label": "WithdrawalManagerQueue",
                "role": "Syrup USDC withdrawal queue manager",
                "address": "0x1bc47a0Dd0FdaB96E9eF982fdf1F34DC6207cfE3",
                "explorer_url": "https://etherscan.io/address/0x1bc47a0Dd0FdaB96E9eF982fdf1F34DC6207cfE3",
            },
            {
                "label": "SyrupRouter",
                "role": "Syrup USDC user action router",
                "address": "0x134cCaaA4F1e4552eC8aEcb9E4A2360dDcF8df76",
                "explorer_url": "https://etherscan.io/address/0x134cCaaA4F1e4552eC8aEcb9E4A2360dDcF8df76",
            },
        ),
    },
    {
        "chain": "Ethereum",
        "protocol_contains": "maple",
        "assets": ("USDT",),
        "source_pool_ids": ("8edfdf02-cdbb-43f7-bca6-954e5fe56813",),
        "contract_address": "0x356B8d89c1e1239Cbbb9dE4815c39A1474d5BA7D",
        "contract_role": "Maple Syrup USDT pool contract",
        "explorer_url": "https://etherscan.io/address/0x356B8d89c1e1239Cbbb9dE4815c39A1474d5BA7D",
        "pool_url": "https://app.maple.finance/earn",
        "contract_verification": (
            "Manually matched to DeFiLlama poolMeta 'Syrup USDT' and official Syrup addresses on 2026-07-24. "
            "This identifies the Syrup USDT pool contract; it does not verify APY, TVL, borrower credit quality, collateral, withdrawal queue timing, or audit scope."
        ),
        "verification_sources": (
            {"label": "Syrup addresses", "url": "https://syrup.gitbook.io/syrup/technical-resources/addresses"},
            {"label": "Maple integration docs", "url": "https://docs.maple.finance/integrate/get-started"},
            {"label": "Maple withdrawal docs", "url": "https://docs.maple.finance/syrupusdc-for-lenders/risk"},
            {"label": "Etherscan address", "url": "https://etherscan.io/address/0x356B8d89c1e1239Cbbb9dE4815c39A1474d5BA7D"},
        ),
        "related_contracts": (
            {
                "label": "USDT",
                "role": "Underlying pool asset",
                "address": "0xdAC17F958D2ee523a2206206994597C13D831ec7",
                "explorer_url": "https://etherscan.io/address/0xdAC17F958D2ee523a2206206994597C13D831ec7",
            },
            {
                "label": "PoolManager",
                "role": "Syrup USDT pool manager",
                "address": "0x0cdA32E08B48bFDDbc7eE96B44b09cf286F9E21a",
                "explorer_url": "https://etherscan.io/address/0x0cdA32E08B48bFDDbc7eE96B44b09cf286F9E21a",
            },
            {
                "label": "WithdrawalManagerQueue",
                "role": "Syrup USDT withdrawal queue manager",
                "address": "0x86eBDf902d800F2a82038290B6DBb2A5eE29eB8C",
                "explorer_url": "https://etherscan.io/address/0x86eBDf902d800F2a82038290B6DBb2A5eE29eB8C",
            },
            {
                "label": "SyrupRouter",
                "role": "Syrup USDT user action router",
                "address": "0xF007476Bb27430795138C511F18F821e8D1e5Ee2",
                "explorer_url": "https://etherscan.io/address/0xF007476Bb27430795138C511F18F821e8D1e5Ee2",
            },
        ),
    },
    {
        "chain": "Base",
        "protocol_contains": "centrifuge",
        "assets": ("USDC",),
        "source_pool_ids": ("82469f6f-951d-4578-b47e-fb4df326f059",),
        "contract_address": "0x2AEf271F00A9d1b0DA8065D396f4E601dBD0Ef0b",
        "contract_role": "Centrifuge JAAA Base USDC vault",
        "explorer_url": "https://basescan.org/address/0x2AEf271F00A9d1b0DA8065D396f4E601dBD0Ef0b",
        "pool_url": "https://app.centrifuge.io/",
        "contract_verification": (
            "Manually matched to DeFiLlama poolMeta 'Janus Henderson AAA CLO Fund' and official Centrifuge deployments on 2026-07-24. "
            "This identifies the Base USDC vault; it does not verify APY, TVL, share pricing, RWA issuer performance, liquidity, redemption timing, or audit scope."
        ),
        "verification_sources": (
            {"label": "Centrifuge deployments", "url": "https://docs.centrifuge.io/developer/protocol/deployments/"},
            {"label": "Basescan address", "url": "https://basescan.org/address/0x2AEf271F00A9d1b0DA8065D396f4E601dBD0Ef0b"},
        ),
        "related_contracts": (
            {
                "label": "JAAA",
                "role": "Janus Henderson AAA CLO Fund token on Base",
                "address": "0x5a0F93D040De44e78F251b03c43be9CF317Dcf64",
                "explorer_url": "https://basescan.org/address/0x5a0F93D040De44e78F251b03c43be9CF317Dcf64",
            },
            {
                "label": "USDC",
                "role": "Underlying vault asset on Base",
                "address": "0x833589fCD6eDb6E08f4c7C32D4f71b54bDa02913",
                "explorer_url": "https://basescan.org/address/0x833589fCD6eDb6E08f4c7C32D4f71b54bDa02913",
            },
        ),
    },
    {
        "chain": "Ethereum",
        "protocol_contains": "centrifuge",
        "assets": ("USDS",),
        "source_pool_ids": ("ff1bb959-d160-4906-bad2-d3e37a1e92e8",),
        "contract_address": "0x381f4f3b43c30b78c1f7777553236e57bb8ae9ff",
        "contract_role": "Centrifuge JTRSY Ethereum USDS vault",
        "explorer_url": "https://etherscan.io/address/0x381f4f3b43c30b78c1f7777553236e57bb8ae9ff",
        "pool_url": "https://app.centrifuge.io/",
        "contract_verification": (
            "Manually matched to DeFiLlama poolMeta 'Janus Henderson Treasury Fund' and official Centrifuge deployments on 2026-07-24. "
            "This identifies the Ethereum USDS vault; it does not verify APY, TVL, share pricing, RWA issuer performance, liquidity, redemption timing, or audit scope."
        ),
        "verification_sources": (
            {"label": "Centrifuge deployments", "url": "https://docs.centrifuge.io/developer/protocol/deployments/"},
            {"label": "Etherscan address", "url": "https://etherscan.io/address/0x381f4f3b43c30b78c1f7777553236e57bb8ae9ff"},
        ),
        "related_contracts": (
            {
                "label": "JTRSY",
                "role": "Janus Henderson Treasury Fund token on Ethereum",
                "address": "0x8c213ee79581ff4984583c6a801e5263418c4b86",
                "explorer_url": "https://etherscan.io/address/0x8c213ee79581ff4984583c6a801e5263418c4b86",
            },
            {
                "label": "USDS",
                "role": "Underlying vault asset on Ethereum",
                "address": "0xdC035D45d973E3EC169d2276DDab16f1e407384F",
                "explorer_url": "https://etherscan.io/address/0xdC035D45d973E3EC169d2276DDab16f1e407384F",
            },
        ),
    },
)


def protocol_metadata(value: str) -> ProtocolMetadata:
    normalized = value.lower()
    for alias, key in PROTOCOL_ALIASES.items():
        if alias in normalized:
            return PROTOCOL_METADATA[key]
    return ProtocolMetadata()


def merge_notes(*groups: Iterable[str]) -> tuple[str, ...]:
    notes: list[str] = []
    for group in groups:
        notes.extend(str(note) for note in group if note)
    return tuple(dict.fromkeys(notes))


def apply_protocol_metadata(row: dict[str, Any]) -> dict[str, Any]:
    metadata = protocol_metadata(str(row.get("protocol", "")))
    row["protocol_url"] = metadata.protocol_url
    row["docs_url"] = metadata.docs_url
    row["security_url"] = metadata.security_url
    row["risk_notes"] = metadata.risk_notes
    row["factors"] = merge_notes(row.get("factors", ()), metadata.risk_notes)
    return row


def manual_contract_verification(row: dict[str, Any]) -> dict[str, Any] | None:
    chain = str(row.get("chain", ""))
    protocol = str(row.get("protocol", "")).lower()
    asset = str(row.get("asset", "")).upper()
    pool_id = extract_pool_id(row)

    for verification in MANUAL_CONTRACT_VERIFICATIONS:
        if chain != verification["chain"]:
            continue
        if verification["protocol_contains"] not in protocol:
            continue
        if asset not in verification["assets"]:
            continue
        source_pool_ids = verification.get("source_pool_ids")
        if source_pool_ids and pool_id not in source_pool_ids:
            continue
        return {
            key: value
            for key, value in verification.items()
            if key not in {"chain", "protocol_contains", "assets", "source_pool_ids"}
        }
    return None


def extract_pool_id(row: dict[str, Any]) -> str | None:
    pool_id = row.get("source_pool_id")
    if pool_id:
        return str(pool_id)

    legacy_contract = str(row.get("contract", ""))
    prefix = "DeFiLlama pool id:"
    if legacy_contract.startswith(prefix):
        return legacy_contract.removeprefix(prefix).strip() or None
    return None


def apply_verification_metadata(row: dict[str, Any]) -> dict[str, Any]:
    pool_id = extract_pool_id(row)
    contract_address = str(row.get("contract_address", "") or "").strip()
    explorer_url = str(row.get("explorer_url", "") or "").strip()
    source_label = str(row.get("source_label", "")).lower()
    is_demo = source_label == "demo data" or str(row.get("id", "")).startswith("demo-")

    row["source_pool_id"] = pool_id
    row["pool_url"] = str(row.get("pool_url", "") or "").strip()
    row["contract_address"] = contract_address
    row["explorer_url"] = explorer_url
    row["contract_role"] = str(row.get("contract_role", "") or "").strip()
    row["related_contracts"] = row.get("related_contracts", ())
    row["verification_sources"] = row.get("verification_sources", ())
    row["apy_base"] = row.get("apy_base") if is_number(row.get("apy_base")) else None
    row["apy_reward"] = row.get("apy_reward") if is_number(row.get("apy_reward")) else None
    row["apy_source_label"] = str(row.get("apy_source_label", "") or "APY source not captured in this snapshot")
    row["apy_composition"] = str(row.get("apy_composition", "") or "unknown")
    row["pool_meta"] = str(row.get("pool_meta", "") or "")
    reward_tokens = row.get("reward_tokens", ())
    row["reward_tokens"] = tuple(str(token) for token in reward_tokens) if isinstance(reward_tokens, (list, tuple)) else ()

    if is_demo:
        row["pool_reference"] = str(row.get("pool_reference", "") or "Demo record")
        row["pool_verification"] = str(row.get("pool_verification", "") or "Demo record only; not a market data record.")
        row["contract"] = str(row.get("contract", "") or "Verify with protocol")
        row["contract_verification"] = str(
            row.get("contract_verification", "") or "Demo record; no contract address is verified by Aethra."
        )
        return row

    row["pool_reference"] = f"DeFiLlama pool id: {pool_id}" if pool_id else "Pool id unavailable"
    row["pool_verification"] = (
        "Aggregator pool id only; verify the exact pool, asset, chain, and terms with the original protocol before acting."
    )

    manual_verification = manual_contract_verification(row)
    if manual_verification:
        row.update(manual_verification)
        contract_address = str(row.get("contract_address", "") or "").strip()
        explorer_url = str(row.get("explorer_url", "") or "").strip()
        row["contract_address"] = contract_address
        row["explorer_url"] = explorer_url

    if contract_address:
        row["contract"] = contract_address
        row["contract_verification"] = str(
            row.get("contract_verification", "")
            or "Contract address supplied in dataset; verify the chain explorer, proxy implementation, and audit scope before use."
        )
    else:
        row["contract"] = "Not provided by DeFiLlama pool snapshot"
        row["contract_verification"] = (
            "Contract address not provided by the source snapshot and not verified by Aethra."
        )

    return row


class TransparentRiskScorer:
    """Rule-based scoring where every point can be explained."""

    def score(self, opportunity: YieldOpportunity) -> ScoredOpportunity:
        score = 10
        reasons: list[str] = ["Base DeFi smart contract and market risk"]

        if not opportunity.verified:
            score += 12
            if opportunity.source_label.lower() == "demo data":
                reasons.append("Data is local fallback demo data, not verified market data")
            else:
                reasons.append("Data is from a third-party aggregator, not the original protocol")

        if "not provided" in opportunity.audit.lower():
            score += 10
            reasons.append("Audit status is not included in the source snapshot")

        if opportunity.tvl < 100_000_000:
            score += 16
            reasons.append("Lower TVL can increase liquidity and exit risk")
        elif opportunity.tvl < 500_000_000:
            score += 8
            reasons.append("Moderate TVL requires liquidity review")

        if opportunity.apy >= 15:
            score += 20
            reasons.append("Very high APY may indicate higher volatility or incentive risk")
        elif opportunity.apy >= 8:
            score += 10
            reasons.append("Elevated APY requires source and sustainability checks")

        if opportunity.bridge_dependency:
            score += 8
            reasons.append("Layer 2 or cross-chain assumptions apply")

        for factor in opportunity.factors:
            normalized = factor.lower()
            if "impermanent" in normalized:
                score += 10
            elif "multi-asset" in normalized:
                score += 6
            elif "volatile" in normalized:
                score += 8
            elif "reward" in normalized:
                score += 6

        score = max(0, min(score, 100))
        level = "Low" if score < 40 else "Medium" if score < 70 else "High"

        return ScoredOpportunity(
            opportunity=opportunity,
            score=score,
            risk=level,
            score_reasons=tuple(dict.fromkeys(reasons)),
        )


def is_number(value: Any) -> bool:
    return isinstance(value, (int, float)) and math.isfinite(value)


def title_protocol(slug: str) -> str:
    return " ".join(part.upper() if part in {"aave", "usdc", "usdt"} else part.capitalize() for part in slug.split("-"))


def infer_strategy(row: dict[str, Any]) -> str:
    exposure = row.get("exposure")
    il_risk = row.get("ilRisk")
    if il_risk == "yes" or exposure == "multi":
        return "Liquidity pool"
    if row.get("stablecoin"):
        return "Stable yield"
    if "stake" in str(row.get("project", "")):
        return "Staking"
    return "Yield pool"


def pool_factors(row: dict[str, Any]) -> tuple[str, ...]:
    factors: list[str] = ["APY and TVL are sourced from DeFiLlama's public yield snapshot"]

    if row.get("stablecoin"):
        factors.append("Stablecoin exposure still carries issuer, peg, and market risk")
    else:
        factors.append("Non-stable asset exposure can be volatile")

    if row.get("ilRisk") == "yes":
        factors.append("Impermanent loss risk is flagged by the source")

    if row.get("exposure") == "multi":
        factors.append("Multi-asset exposure can add price and exit complexity")

    if is_number(row.get("apyReward")) and row["apyReward"] > 0:
        factors.append("Part of APY may come from token rewards")

    if is_number(row.get("apyPct7D")) and abs(row["apyPct7D"]) > 2:
        factors.append("7-day APY movement suggests yield volatility")

    return tuple(factors)


def normalized_number(value: Any) -> float | None:
    if not is_number(value):
        return None
    return round(float(value), 4)


def normalize_reward_tokens(value: Any) -> tuple[str, ...]:
    if not isinstance(value, list):
        return ()
    return tuple(str(token) for token in value if token)


def apy_composition(row: dict[str, Any]) -> tuple[float | None, float | None, str, str]:
    base = normalized_number(row.get("apyBase"))
    reward = normalized_number(row.get("apyReward"))
    pool_meta = str(row.get("poolMeta") or "")

    has_base = base is not None and abs(base) > 0.0001
    has_reward = reward is not None and abs(reward) > 0.0001
    pool_meta_lower = pool_meta.lower()
    farming_hint = any(term in pool_meta_lower for term in ("farm", "reward", "incentive"))

    if has_base and has_reward:
        return base, reward, "base_plus_rewards", "Base APY plus token rewards"
    if has_reward and not has_base:
        return base, reward, "rewards_only", "Reward or farming APY"
    if farming_hint:
        return base, reward, "farming_pool", "Farming or incentive pool"
    if has_base:
        return base, reward, "base", "Base APY"
    return base, reward, "unknown", "APY source needs review"


def normalize_pool(row: dict[str, Any], fetched_at: str) -> YieldOpportunity | None:
    chain = row.get("chain")
    symbol = str(row.get("symbol", "")).upper()
    apy = row.get("apy")
    tvl = row.get("tvlUsd")

    if chain not in SUPPORTED_CHAINS:
        return None
    if not is_number(apy) or not is_number(tvl):
        return None
    if row.get("outlier") is True:
        return None
    if tvl < 50_000_000:
        return None
    if apy < 0.1 or apy > 25:
        return None

    assets = {part.strip().upper() for part in symbol.replace("/", "-").split("-") if part.strip()}
    if not assets.intersection(SUPPORTED_ASSETS):
        return None

    pool_id = row.get("pool")
    project = str(row.get("project", "unknown"))
    protocol = title_protocol(project)
    metadata = protocol_metadata(project)
    apy_base, apy_reward, composition, apy_source_label = apy_composition(row)

    return YieldOpportunity(
        id=str(pool_id or f"{project}-{chain}-{symbol}"),
        chain=chain,
        protocol=protocol,
        asset=symbol,
        strategy=infer_strategy(row),
        apy=round(float(apy), 2),
        tvl=round(float(tvl), 2),
        updated=fetched_at,
        source=DEFILLAMA_YIELDS_UI,
        source_label="DeFiLlama Yields",
        contract="Not provided by DeFiLlama pool snapshot",
        contract_address="",
        contract_verification="Contract address not provided by the source snapshot and not verified by Aethra.",
        audit="Not provided by DeFiLlama pool snapshot",
        factors=pool_factors(row),
        bridge_dependency=chain != "Ethereum",
        verified=False,
        source_pool_id=str(pool_id) if pool_id else None,
        pool_reference=f"DeFiLlama pool id: {pool_id}" if pool_id else "Pool id unavailable",
        pool_verification="Aggregator pool id only; verify the exact pool, asset, chain, and terms with the original protocol before acting.",
        apy_base=apy_base,
        apy_reward=apy_reward,
        apy_source_label=apy_source_label,
        apy_composition=composition,
        pool_meta=str(row.get("poolMeta") or ""),
        reward_tokens=normalize_reward_tokens(row.get("rewardTokens")),
        pool_url="",
        explorer_url="",
        protocol_url=metadata.protocol_url,
        docs_url=metadata.docs_url,
        security_url=metadata.security_url,
        risk_notes=metadata.risk_notes,
    )


def fetch_defillama_pools(url: str = DEFILLAMA_POOLS_URL, timeout: int = 90) -> list[dict[str, Any]]:
    request = Request(url, headers={"User-Agent": "AethraFinance/0.2"})
    with urlopen(request, timeout=timeout) as response:
        payload = json.loads(response.read().decode("utf-8"))
    if payload.get("status") != "success" or not isinstance(payload.get("data"), list):
        raise ValueError("Unexpected DeFiLlama response shape")
    return payload["data"]


def load_preferred_pool_ids(path: Path) -> tuple[str, ...]:
    if not path.exists():
        return ()
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return ()

    records = payload.get("opportunities", [])
    if not isinstance(records, list):
        return ()

    preferred: list[str] = []
    for record in records:
        if not isinstance(record, dict):
            continue
        pool_id = dataset_record_key(record)
        if pool_id and pool_id not in preferred:
            preferred.append(pool_id)
    return tuple(preferred)


def select_diverse_opportunities(
    opportunities: list[YieldOpportunity],
    limit: int,
    preferred_pool_ids: Iterable[str] = (),
) -> list[YieldOpportunity]:
    ranked = sorted(opportunities, key=lambda item: item.tvl, reverse=True)
    preferred = set(preferred_pool_ids)
    selected: list[YieldOpportunity] = []
    selected_ids: set[str] = set()

    for chain in sorted(SUPPORTED_CHAINS):
        chain_pick = next(
            (item for item in ranked if item.chain == chain and item.id in preferred and item.id not in selected_ids),
            None,
        )
        if chain_pick is None:
            chain_pick = next((item for item in ranked if item.chain == chain and item.id not in selected_ids), None)
        if chain_pick:
            selected.append(chain_pick)
            selected_ids.add(chain_pick.id)
        if len(selected) >= limit:
            return selected

    for item in ranked:
        if item.id not in preferred or item.id in selected_ids:
            continue
        selected.append(item)
        selected_ids.add(item.id)
        if len(selected) >= limit:
            return selected

    for item in ranked:
        if item.id in selected_ids:
            continue
        selected.append(item)
        selected_ids.add(item.id)
        if len(selected) >= limit:
            break

    return selected


def display_path(path: Path) -> str:
    try:
        return path.resolve().relative_to(PROJECT_ROOT).as_posix()
    except ValueError:
        return path.as_posix()


def build_from_defillama(
    limit: int = 12,
    timeout: int = 90,
    selection_baseline: Path | None = DEFAULT_OUTPUT,
) -> dict[str, Any]:
    fetched_at = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
    rows = fetch_defillama_pools(timeout=timeout)
    opportunities = [item for item in (normalize_pool(row, fetched_at) for row in rows) if item]
    preferred_pool_ids = load_preferred_pool_ids(selection_baseline) if selection_baseline else ()
    selected = select_diverse_opportunities(opportunities, limit=limit, preferred_pool_ids=preferred_pool_ids)
    scored = score_opportunities(selected)
    return {
        "metadata": {
            "source": "DeFiLlama Yields",
            "source_url": DEFILLAMA_POOLS_URL,
            "display_source_url": DEFILLAMA_YIELDS_UI,
            "generated_at": fetched_at,
            "record_count": len(scored),
            "verification": "Third-party aggregator data; verify with original protocols before acting.",
            "selection_policy": (
                SELECTION_BASELINE_POLICY if preferred_pool_ids else "TVL ranking with chain diversity"
            ),
            "selection_baseline": display_path(selection_baseline) if preferred_pool_ids and selection_baseline else "",
        },
        "opportunities": scored,
    }


def demo_opportunities() -> list[YieldOpportunity]:
    return [
        YieldOpportunity(
            id="demo-aave-ethereum-usdc",
            chain="Ethereum",
            protocol="Aave",
            asset="USDC",
            strategy="Variable lending",
            apy=4.5,
            tvl=5_000_000_000,
            updated="Demo snapshot",
            source="https://app.aave.com/",
            source_label="Demo data",
            contract="Verify with protocol",
            contract_address="",
            contract_verification="Demo record; no contract address is verified by Aethra.",
            audit="Public audits available",
            factors=("Rates can change quickly with utilization",),
            pool_reference="Demo record",
            pool_verification="Demo record only; not a market data record.",
        ),
        YieldOpportunity(
            id="demo-uniswap-arbitrum-eth-usdc",
            chain="Arbitrum",
            protocol="Uniswap",
            asset="ETH/USDC",
            strategy="Concentrated liquidity",
            apy=12.1,
            tvl=2_000_000_000,
            updated="Demo snapshot",
            source="https://app.uniswap.org/",
            source_label="Demo data",
            contract="Verify with protocol",
            contract_address="",
            contract_verification="Demo record; no contract address is verified by Aethra.",
            audit="Public audits available",
            factors=(
                "Impermanent loss can affect realized returns",
                "APY depends on volume, price range, and fee tier",
            ),
            bridge_dependency=True,
            pool_reference="Demo record",
            pool_verification="Demo record only; not a market data record.",
        ),
    ]


def score_opportunities(opportunities: Iterable[YieldOpportunity]) -> list[dict[str, Any]]:
    scorer = TransparentRiskScorer()
    scored = []
    for opportunity in opportunities:
        result = scorer.score(opportunity)
        row = apply_verification_metadata(apply_protocol_metadata(asdict(result.opportunity)))
        row["score"] = result.score
        row["risk"] = result.risk
        row["score_reasons"] = result.score_reasons
        scored.append(row)
    return scored


def write_dataset(payload: dict[str, Any], output_path: Path = DEFAULT_OUTPUT) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def enrich_existing_dataset(path: Path = DEFAULT_OUTPUT) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    records = payload.get("opportunities", [])
    if not isinstance(records, list):
        raise ValueError("Dataset does not contain an opportunities list")
    payload["opportunities"] = [apply_verification_metadata(apply_protocol_metadata(record)) for record in records]
    return payload


def parse_generated_at(value: Any) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def check_dataset(
    path: Path = DEFAULT_OUTPUT,
    max_age_hours: int = STALE_AFTER_HOURS,
    fail_on_warnings: bool = False,
) -> dict[str, Any]:
    errors: list[str] = []
    warnings: list[str] = []
    missing_pool_verification = 0
    missing_contract_address = 0
    missing_explorer_url = 0

    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {
            "status": "fail",
            "path": str(path),
            "errors": [f"Dataset file not found: {path}"],
            "warnings": [],
        }
    except json.JSONDecodeError as exc:
        return {
            "status": "fail",
            "path": str(path),
            "errors": [f"Dataset is not valid JSON: {exc}"],
            "warnings": [],
        }

    metadata = payload.get("metadata", {})
    records = payload.get("opportunities")

    if not isinstance(metadata, dict):
        errors.append("metadata must be an object")
        metadata = {}
    if not isinstance(records, list) or not records:
        errors.append("opportunities must be a non-empty list")
        records = []

    generated_at = parse_generated_at(metadata.get("generated_at"))
    if generated_at is None:
        errors.append("metadata.generated_at is missing or invalid")
        age_hours = None
    else:
        now = datetime.now(timezone.utc)
        age_hours = (now - generated_at).total_seconds() / 3600
        if age_hours < -1:
            errors.append("metadata.generated_at is unexpectedly in the future")
        elif age_hours > max_age_hours:
            errors.append(f"Dataset is stale: generated {age_hours:.1f} hours ago")

    if str(metadata.get("source", "")).lower().startswith("fallback"):
        errors.append("metadata.source indicates fallback data")

    expected_count = metadata.get("record_count")
    if is_number(expected_count) and records and int(expected_count) != len(records):
        warnings.append(f"metadata.record_count is {expected_count}, but found {len(records)} records")

    for index, record in enumerate(records):
        label = f"record[{index}]"
        if not isinstance(record, dict):
            errors.append(f"{label} must be an object")
            continue

        missing = sorted(REQUIRED_OPPORTUNITY_FIELDS - record.keys())
        if missing:
            errors.append(f"{label} missing required fields: {', '.join(missing)}")

        if str(record.get("source_label", "")).lower() == "demo data" or str(record.get("id", "")).startswith("demo-"):
            errors.append(f"{label} appears to be demo data")

        if not is_number(record.get("apy")) or record.get("apy") < 0:
            errors.append(f"{label} has invalid apy")
        if record.get("apy_base") is not None and not is_number(record.get("apy_base")):
            errors.append(f"{label} has invalid apy_base")
        if record.get("apy_reward") is not None and not is_number(record.get("apy_reward")):
            errors.append(f"{label} has invalid apy_reward")
        if not record.get("apy_source_label"):
            errors.append(f"{label} missing apy_source_label")
        if record.get("apy_composition") not in APY_COMPOSITIONS:
            errors.append(f"{label} has invalid apy_composition")
        if record.get("reward_tokens") and not isinstance(record.get("reward_tokens"), list):
            errors.append(f"{label} reward_tokens must be a list")
        if record.get("apy_composition") in {"base_plus_rewards", "rewards_only", "farming_pool"}:
            if record.get("apy_reward") is None and not record.get("pool_meta"):
                warnings.append(f"{label} needs reward APY or pool_meta context for {record.get('apy_composition')}")
        if not is_number(record.get("tvl")) or record.get("tvl") <= 0:
            errors.append(f"{label} has invalid tvl")
        if not is_number(record.get("score")) or not 0 <= record.get("score") <= 100:
            errors.append(f"{label} has invalid risk score")
        if record.get("risk") not in {"Low", "Medium", "High"}:
            errors.append(f"{label} has invalid risk label")

        if not record.get("source"):
            errors.append(f"{label} missing source URL")
        if not record.get("factors"):
            errors.append(f"{label} missing risk factors")
        if not record.get("score_reasons"):
            errors.append(f"{label} missing score reasons")
        if not record.get("protocol_url"):
            warnings.append(f"{label} missing official protocol URL")
        if not record.get("docs_url") and not record.get("security_url"):
            warnings.append(f"{label} missing protocol docs/security URL")
        if not record.get("pool_reference") or not record.get("pool_verification"):
            missing_pool_verification += 1
        if not record.get("contract_address"):
            missing_contract_address += 1
        if not record.get("explorer_url"):
            missing_explorer_url += 1
        if record.get("contract_address") and not record.get("contract_role"):
            errors.append(f"{label} has a contract address without contract_role")
        if record.get("contract_address") and not record.get("verification_sources"):
            errors.append(f"{label} has a contract address without verification_sources")
        if record.get("contract_address") and not record.get("explorer_url"):
            errors.append(f"{label} has a contract address without explorer_url")
        if record.get("related_contracts") and not isinstance(record.get("related_contracts"), list):
            errors.append(f"{label} related_contracts must be a list")
        for related_index, related in enumerate(record.get("related_contracts") or []):
            related_label = f"{label}.related_contracts[{related_index}]"
            if not isinstance(related, dict):
                errors.append(f"{related_label} must be an object")
                continue
            for field in ("label", "role", "address", "explorer_url"):
                if not related.get(field):
                    errors.append(f"{related_label} missing {field}")

    if missing_pool_verification:
        warnings.append(f"{missing_pool_verification} records missing pool-level verification status")
    if missing_contract_address:
        warnings.append(f"{missing_contract_address} records missing verified contract address")
    if missing_explorer_url:
        warnings.append(f"{missing_explorer_url} records missing chain explorer URL")

    return {
        "status": "fail" if errors or (fail_on_warnings and warnings) else "pass",
        "path": str(path),
        "max_age_hours": max_age_hours,
        "fail_on_warnings": fail_on_warnings,
        "age_hours": round(age_hours, 2) if isinstance(age_hours, (int, float)) else None,
        "record_count": len(records),
        "errors": errors,
        "warnings": warnings,
    }


def dataset_record_key(record: dict[str, Any]) -> str:
    return str(record.get("source_pool_id") or record.get("id") or "")


def dataset_record_label(record: dict[str, Any]) -> str:
    parts = [
        str(record.get("protocol", "") or "Unknown protocol"),
        str(record.get("chain", "") or "Unknown chain"),
        str(record.get("asset", "") or "Unknown asset"),
    ]
    return " / ".join(parts)


def compact_record(record: dict[str, Any]) -> dict[str, Any]:
    return {
        "key": dataset_record_key(record),
        "label": dataset_record_label(record),
        "apy": record.get("apy"),
        "tvl": record.get("tvl"),
        "risk": record.get("risk"),
        "score": record.get("score"),
        "apy_composition": record.get("apy_composition", ""),
        "apy_source_label": record.get("apy_source_label", ""),
        "pool_meta": record.get("pool_meta", ""),
        "pool_url": record.get("pool_url", ""),
        "contract_address": record.get("contract_address", ""),
        "contract_role": record.get("contract_role", ""),
    }


def numeric_delta(before: Any, after: Any) -> dict[str, Any]:
    before_number = float(before)
    after_number = float(after)
    delta = after_number - before_number
    delta_ratio = None if before_number == 0 else delta / before_number
    return {
        "before": round(before_number, 4),
        "after": round(after_number, 4),
        "delta": round(delta, 4),
        "delta_pct": round(delta_ratio * 100, 2) if delta_ratio is not None else None,
    }


def compare_dataset_records(baseline: dict[str, Any], candidate: dict[str, Any]) -> dict[str, Any]:
    baseline_records = baseline.get("opportunities", [])
    candidate_records = candidate.get("opportunities", [])
    if not isinstance(baseline_records, list):
        baseline_records = []
    if not isinstance(candidate_records, list):
        candidate_records = []

    baseline_by_key = {dataset_record_key(record): record for record in baseline_records if isinstance(record, dict)}
    candidate_by_key = {dataset_record_key(record): record for record in candidate_records if isinstance(record, dict)}
    baseline_by_key.pop("", None)
    candidate_by_key.pop("", None)

    added = [compact_record(candidate_by_key[key]) for key in sorted(candidate_by_key.keys() - baseline_by_key.keys())]
    removed = [compact_record(baseline_by_key[key]) for key in sorted(baseline_by_key.keys() - candidate_by_key.keys())]

    changed: list[dict[str, Any]] = []
    material_change_count = 0
    watched_fields = (
        "chain",
        "protocol",
        "asset",
        "strategy",
        "risk",
        "score",
        "contract_address",
        "contract_role",
        "explorer_url",
        "pool_url",
        "apy_composition",
        "apy_source_label",
        "apy_base",
        "apy_reward",
        "pool_meta",
        "reward_tokens",
        "verification_sources",
        "related_contracts",
    )

    for key in sorted(baseline_by_key.keys() & candidate_by_key.keys()):
        before = baseline_by_key[key]
        after = candidate_by_key[key]
        changes: list[dict[str, Any]] = []
        material = False

        if is_number(before.get("apy")) and is_number(after.get("apy")):
            apy_change = numeric_delta(before["apy"], after["apy"])
            if abs(apy_change["delta"]) >= APY_REVIEW_DELTA:
                apy_change["field"] = "apy"
                apy_change["review_reason"] = f"APY moved by at least {APY_REVIEW_DELTA} percentage points"
                changes.append(apy_change)
                material = True

        if is_number(before.get("tvl")) and is_number(after.get("tvl")):
            tvl_change = numeric_delta(before["tvl"], after["tvl"])
            delta_pct = abs(tvl_change["delta_pct"] or 0)
            delta_usd = abs(tvl_change["delta"])
            if delta_pct >= TVL_REVIEW_DELTA_RATIO * 100 or delta_usd >= TVL_REVIEW_DELTA_USD:
                tvl_change["field"] = "tvl"
                tvl_change["review_reason"] = "TVL moved materially by percentage or absolute value"
                changes.append(tvl_change)
                material = True

        for field in watched_fields:
            if before.get(field) != after.get(field):
                changes.append(
                    {
                        "field": field,
                        "before": before.get(field),
                        "after": after.get(field),
                        "review_reason": "Core record metadata changed",
                    }
                )
                material = True

        if changes:
            if material:
                material_change_count += 1
            changed.append(
                {
                    "key": key,
                    "label": dataset_record_label(after),
                    "material": material,
                    "changes": changes,
                }
            )

    review_notes = [
        "Review added and removed records against DeFiLlama and the original protocol before promotion.",
        "Review material APY/TVL moves for source changes, rewards, incentives, and liquidity shifts.",
        "Contract and explorer metadata changes are review anchors only; they do not prove safety or audit coverage.",
    ]

    return {
        "status": "review_required" if added or removed or material_change_count else "no_material_change",
        "summary": {
            "baseline_count": len(baseline_by_key),
            "candidate_count": len(candidate_by_key),
            "added_count": len(added),
            "removed_count": len(removed),
            "changed_count": len(changed),
            "material_changed_count": material_change_count,
        },
        "baseline_generated_at": (
            baseline.get("metadata", {}).get("generated_at") if isinstance(baseline.get("metadata"), dict) else None
        ),
        "candidate_generated_at": (
            candidate.get("metadata", {}).get("generated_at") if isinstance(candidate.get("metadata"), dict) else None
        ),
        "thresholds": {
            "apy_delta_percentage_points": APY_REVIEW_DELTA,
            "tvl_delta_ratio": TVL_REVIEW_DELTA_RATIO,
            "tvl_delta_usd": TVL_REVIEW_DELTA_USD,
        },
        "added": added,
        "removed": removed,
        "changed": changed,
        "review_notes": review_notes,
    }


def compare_datasets(baseline_path: Path = DEFAULT_OUTPUT, candidate_path: Path = DEFAULT_CANDIDATE) -> dict[str, Any]:
    baseline = json.loads(baseline_path.read_text(encoding="utf-8"))
    candidate = json.loads(candidate_path.read_text(encoding="utf-8"))
    report = compare_dataset_records(baseline, candidate)
    report["baseline_path"] = str(baseline_path)
    report["candidate_path"] = str(candidate_path)
    return report


def check_frontend_qa(path: Path = DEFAULT_FRONTEND) -> dict[str, Any]:
    errors: list[str] = []
    warnings: list[str] = []

    try:
        html = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return {
            "status": "fail",
            "path": str(path),
            "errors": [f"Frontend file not found: {path}"],
            "warnings": [],
        }

    required_markers = {
        "query-gated QA mode": 'new URLSearchParams(window.location.search).has("qa")',
        "QA state collector": "function collectQaState()",
        "QA renderer": "function renderQaPanel()",
        "QA visible heading": "QA 诊断",
        "structured QA data attribute": "panel.dataset.qa = JSON.stringify(state)",
        "record count diagnostic": "record_count",
        "rendered rows diagnostic": "visible_data_rows",
        "fallback diagnostic": "is_fallback",
        "stale diagnostic": "is_stale",
        "overflow diagnostic": "horizontal_overflow",
        "read-only wallet scope diagnostic": "no_wallet_claim",
        "read-only custody scope diagnostic": "no_custody_claim",
        "third-party notice diagnostic": "third_party_notice",
    }

    for label, marker in required_markers.items():
        if marker not in html:
            errors.append(f"Missing {label}: {marker}")

    body_before_script = html.split("<script>", 1)[0]
    if 'id="qaPanel"' in body_before_script or "id='qaPanel'" in body_before_script:
        errors.append("QA panel must not be present in the default static markup")

    if ".qa-panel" not in html:
        warnings.append("QA panel styles not found")

    return {
        "status": "fail" if errors else "pass",
        "path": str(path),
        "errors": errors,
        "warnings": warnings,
    }


def latest_source_review_matrix_path(directory: Path = DEFAULT_SOURCE_REVIEW_MATRIX_DIR) -> Path | None:
    matrices = sorted(directory.glob("source-review-matrix-*.md"))
    return matrices[-1] if matrices else None


def check_source_review_matrix(
    dataset_path: Path = DEFAULT_OUTPUT,
    matrix_path: Path | None = None,
) -> dict[str, Any]:
    errors: list[str] = []
    warnings: list[str] = []

    try:
        payload = json.loads(dataset_path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {
            "status": "fail",
            "dataset_path": str(dataset_path),
            "matrix_path": str(matrix_path) if matrix_path else None,
            "errors": [f"Dataset file not found: {dataset_path}"],
            "warnings": [],
        }
    except json.JSONDecodeError as exc:
        return {
            "status": "fail",
            "dataset_path": str(dataset_path),
            "matrix_path": str(matrix_path) if matrix_path else None,
            "errors": [f"Dataset is not valid JSON: {exc}"],
            "warnings": [],
        }

    resolved_matrix_path = matrix_path or latest_source_review_matrix_path()
    if resolved_matrix_path is None:
        return {
            "status": "fail",
            "dataset_path": str(dataset_path),
            "matrix_path": None,
            "errors": [f"No source review matrix found in {DEFAULT_SOURCE_REVIEW_MATRIX_DIR}"],
            "warnings": [],
        }

    try:
        matrix_text = resolved_matrix_path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return {
            "status": "fail",
            "dataset_path": str(dataset_path),
            "matrix_path": str(resolved_matrix_path),
            "errors": [f"Source review matrix file not found: {resolved_matrix_path}"],
            "warnings": [],
        }

    metadata = payload.get("metadata", {})
    records = payload.get("opportunities", [])
    if not isinstance(metadata, dict):
        errors.append("metadata must be an object")
        metadata = {}
    if not isinstance(records, list) or not records:
        errors.append("opportunities must be a non-empty list")
        records = []

    generated_at = metadata.get("generated_at")
    if not isinstance(generated_at, str) or not generated_at:
        errors.append("metadata.generated_at is missing or invalid")
    elif generated_at not in matrix_text:
        errors.append(f"Source review matrix does not mention dataset generated_at: {generated_at}")

    record_count = len(records)
    if record_count and f"{record_count} records" not in matrix_text:
        warnings.append(f"Source review matrix does not mention '{record_count} records'")

    matrix_lower = matrix_text.lower()
    if "owner-only" not in matrix_lower:
        errors.append("Source review matrix must state the owner-only review scope")
    if "not approved for public release" not in matrix_lower and "public-release approval" not in matrix_lower:
        errors.append("Source review matrix must state that it is not public-release approval")

    missing_pool_ids: list[str] = []
    missing_labels: list[str] = []
    missing_contracts: list[str] = []
    records_without_pool_id = 0

    for index, record in enumerate(records):
        if not isinstance(record, dict):
            errors.append(f"record[{index}] must be an object")
            continue
        pool_id = str(record.get("source_pool_id") or "")
        if not pool_id:
            records_without_pool_id += 1
        elif pool_id not in matrix_text:
            missing_pool_ids.append(pool_id)

        label = dataset_record_label(record)
        if label not in matrix_text:
            missing_labels.append(label)

        contract_address = str(record.get("contract_address") or "")
        if contract_address and contract_address not in matrix_text:
            missing_contracts.append(f"{label}: {contract_address}")

    if records_without_pool_id:
        errors.append(f"{records_without_pool_id} records are missing source_pool_id and cannot be matrix-checked")
    if missing_pool_ids:
        errors.append(f"Source review matrix missing pool ids: {', '.join(missing_pool_ids)}")
    if missing_labels:
        errors.append(f"Source review matrix missing labels: {', '.join(missing_labels)}")
    if missing_contracts:
        errors.append(f"Source review matrix missing contract anchors: {', '.join(missing_contracts)}")

    return {
        "status": "fail" if errors else "pass",
        "dataset_path": str(dataset_path),
        "matrix_path": str(resolved_matrix_path),
        "dataset_generated_at": generated_at,
        "record_count": record_count,
        "errors": errors,
        "warnings": warnings,
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build Aethra yield opportunity data.")
    parser.add_argument("--refresh", action="store_true", help="Fetch DeFiLlama and write data/opportunities.json")
    parser.add_argument("--enrich-existing", action="store_true", help="Add protocol review links to an existing output file")
    parser.add_argument("--check-dataset", action="store_true", help="Validate data/opportunities.json for release readiness")
    parser.add_argument("--check-frontend-qa", action="store_true", help="Validate hidden frontend QA diagnostics are present")
    parser.add_argument("--check-source-review-matrix", action="store_true", help="Validate the source review matrix covers the current dataset")
    parser.add_argument("--compare-candidate", action="store_true", help="Compare a refresh candidate against the committed snapshot")
    parser.add_argument("--baseline", type=Path, default=DEFAULT_OUTPUT, help="Baseline dataset for candidate comparison")
    parser.add_argument("--candidate", type=Path, default=DEFAULT_CANDIDATE, help="Candidate dataset for comparison")
    parser.add_argument("--fail-on-changes", action="store_true", help="Fail candidate comparison when review is required")
    parser.add_argument("--limit", type=int, default=12, help="Maximum opportunities to keep")
    parser.add_argument("--matrix", type=Path, default=None, help="Source review matrix markdown path")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT, help="Output JSON path")
    parser.add_argument(
        "--selection-baseline",
        type=Path,
        default=DEFAULT_OUTPUT,
        help="Reviewed dataset whose pool ids should be preferred during refresh selection",
    )
    parser.add_argument(
        "--ignore-selection-baseline",
        action="store_true",
        help="Refresh from source ranking only, without preferring the current reviewed pool ids",
    )
    parser.add_argument("--timeout", type=int, default=90, help="HTTP timeout in seconds")
    parser.add_argument("--max-age-hours", type=int, default=STALE_AFTER_HOURS, help="Maximum dataset age for release checks")
    parser.add_argument("--fail-on-warnings", action="store_true", help="Fail dataset checks when warnings are present")
    return parser.parse_args()


if __name__ == "__main__":
    args = parse_args()
    if args.refresh:
        selection_baseline = None if args.ignore_selection_baseline else args.selection_baseline
        data = build_from_defillama(limit=args.limit, timeout=args.timeout, selection_baseline=selection_baseline)
        write_dataset(data, args.output)
        print(json.dumps(data["metadata"], indent=2))
    elif args.enrich_existing:
        data = enrich_existing_dataset(args.output)
        write_dataset(data, args.output)
        print(json.dumps(data.get("metadata", {}), indent=2))
    elif args.check_dataset:
        result = check_dataset(
            args.output,
            max_age_hours=args.max_age_hours,
            fail_on_warnings=args.fail_on_warnings,
        )
        print(json.dumps(result, indent=2))
        sys.exit(0 if result["status"] == "pass" else 1)
    elif args.check_frontend_qa:
        result = check_frontend_qa()
        print(json.dumps(result, indent=2))
        sys.exit(0 if result["status"] == "pass" else 1)
    elif args.check_source_review_matrix:
        result = check_source_review_matrix(args.output, args.matrix)
        print(json.dumps(result, indent=2))
        sys.exit(0 if result["status"] == "pass" else 1)
    elif args.compare_candidate:
        result = compare_datasets(args.baseline, args.candidate)
        print(json.dumps(result, indent=2))
        sys.exit(1 if args.fail_on_changes and result["status"] == "review_required" else 0)
    else:
        print(json.dumps(score_opportunities(demo_opportunities()), indent=2))
