# Risk Methodology

Aethra risk scores are transparent indicators, not predictions and not investment advice.

## Factors

Initial risk scoring uses:

- Protocol maturity
- Audit status
- TVL depth
- Yield volatility
- Asset risk
- Smart contract complexity
- Bridge or cross-chain dependency
- Liquidity and exit risk
- Historical security incidents

## Risk Levels

- Low: fewer visible risk factors, mature protocol, deeper liquidity, clearer audit history
- Medium: meaningful risk factors or partial uncertainty
- High: material smart contract, liquidity, bridge, asset, or verification risk

## User-Facing Rule

Every risk score should be accompanied by the reasons behind it. A score without explanation should not be displayed.

## Protocol Review Links

Protocol docs, security pages, and audit repositories are shown to help users verify context outside Aethra.

These links are not endorsements. A listed security page does not prove that a specific pool, wrapper token, bridge deployment, or strategy version is covered by a current audit. Users should check:

- Whether the displayed pool or asset is in the audit scope
- Whether the chain deployment matches the reviewed contracts
- Whether any material upgrades happened after the latest report
- Whether the opportunity depends on governance, bridge, oracle, real-world asset, or counterparty assumptions

## Pool And Contract Verification

Pool ids from aggregators are references, not verified contract addresses. Aethra should show pool-level and contract-level verification separately:

- Pool verification: whether the displayed pool can be traced back to the original protocol, asset, chain, and product terms
- Contract verification: whether a chain explorer address is known, matches the displayed chain, and can be tied to the relevant protocol deployment
- Audit scope: whether the specific contract, wrapper, market, pool, or proxy version appears in current security materials

Missing contract addresses should remain visible as a warning. They should not be filled with guessed addresses.

When a verified address is shown, its role must be explicit. A market-level lending pool proxy, an ERC-4626 vault token, and a liquid staking token proxy are different contract surfaces. Showing one of them is a navigation aid for review, not a conclusion that the displayed opportunity is safe or fully audited.

For lending markets, related aToken or underlying token addresses help users trace the reserve, but they do not verify current reserve parameters, borrow/supply caps, oracle configuration, or liquidation risk.

For savings vaults, a vault proxy and underlying token address help users identify the contract surface, but they do not verify deposit caps, withdrawal timing, idle liquidity, intent fulfillment, offchain liquidity preparation, or fee/reward mechanics.

For cross-chain savings tokens, a token contract and underlying token address help users identify the chain deployment, but they do not verify bridge security, rate propagation, oracle freshness, redeemability, or available exit liquidity.

For institutional credit pools, pool and manager addresses help users trace the smart contract surface, but they do not verify borrower underwriting, collateral sufficiency, defaults, impairments, withdrawal queue timing, or counterparty performance.

For tokenized real-world asset vaults, vault and fund-token addresses help users trace the onchain surface, but they do not verify issuer obligations, legal structure, asset quality, NAV methodology, redemption terms, transfer restrictions, or reporting timeliness.

For liquid staking or restaking tokens, token and liquidity pool addresses help users trace protocol surfaces, but they do not verify validator, operator, slashing, withdrawal queue, redemption, incentive, or secondary-market liquidity risk.
