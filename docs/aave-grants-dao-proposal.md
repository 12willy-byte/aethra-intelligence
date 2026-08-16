# Aethra Finance — Aave Grants DAO Proposal

- **Category**: Applications and integrations
- **Submitted**: 2026-08-16
- **Repository**: https://github.com/12willy-byte/aethra-intelligence (MIT, public)
- **Funding requested**: $15,000 USD (milestone-based, see breakdown below)
- **Status**: Working open-source prototype, deployed data pipeline, official-source verification in place

## One-line summary

Aethra Finance is an open-source, non-custodial yield intelligence dashboard that shows Aave users exactly where every APY/TVL number came from, how fresh it is, and which values have been cross-checked against official Aave data — then links them to the protocol to act.

## Problem

Aave users comparing yields across money markets (Aave, Spark, Sky, etc.) face three trust problems:

1. **Unattributed numbers**: APY/TVL figures are repeated across dashboards and social posts without a source or update time.
2. **Misleading precision**: aggregator TVL is often confused with protocol-verified values, and "total supply" is conflated with "available liquidity" (a ~6x difference on Aave).
3. **Risk opacity**: risk scores are usually black boxes, so users cannot tell *why* one opportunity is rated riskier than another.

## Solution

Aethra Finance is a transparent, read-only yield intelligence layer:

- Every opportunity shows APY, TVL, source URL, update time, APY composition (base vs reward/farming), and a rule-based risk score with plain-language reasons.
- A dedicated verifier (`backend/verify_sources.py`) cross-checks snapshot records against **official protocol APIs**. A record is marked `verified=True` only when **both** APY and TVL match official values within documented tolerances. Endpoints and field mappings are documented in the script.
- For Aave V3 Ethereum specifically, the verifier uses the official Aave GraphQL (`api.v3.aave.com`): supply APY and **available liquidity** (not total supply), matching DeFiLlama's Aave TVL definition within tolerance.
- 24-hour freshness labeling: the dashboard flags datasets older than 24h as stale and refuses to present them as current.
- No custody, no wallet connection, no trades, no token, no investment advice. Users leave the dashboard to act on the original protocol.

## Why the Aave ecosystem

- Aethra's current 12-record dataset includes Aave V3 Ethereum WETH and USDT with **official Aave GraphQL verification** (supply APY and available liquidity both match within tolerance).
- It drives qualified users to `app.aave.com` with accurate, sourced expectations instead of hype.
- It demonstrates the "available liquidity vs total supply" distinction on Aave, reducing a common source of misleading TVL claims.
- The tooling is reusable for any Aave-integrated app: the verification pattern (official GraphQL + field-mapping + tolerance policy) is documented and MIT-licensed.

## Current state (already built and public)

- Public repository with MIT license: https://github.com/12willy-byte/aethra-intelligence
- DeFiLlama Yields ingestion + stable selection + transparent scoring (`backend/src/strategy_engine.py`)
- Official-source verification (`backend/verify_sources.py`): Lido, Aave V3, Maple, Centrifuge endpoints probed and mapped; 4 of 12 records currently verified, the rest explicitly unverified with documented reasons
- CI release guardrails (dataset validation, frontend QA checks, unit tests, claim scans) passing
- Data snapshot refreshed 2026-08-16 with 0 errors / 0 warnings

## Roadmap and milestones

### M1 — Foundation (completed)
Data pipeline, stable selection policy, official-source verifier, CI guardrails, public open-source release.

### M2 — Aave depth and user-facing verification ($6,000)
- Extend official Aave V3 verification to more reserves and the Arbitrum/Base markets
- Add per-record verification badges in the frontend (verified / source / timestamp / unverified reasons)
- Public alpha: host a read-only dashboard with fresh data and collect user feedback

### M3 — Coverage and users ($6,000)
- Onboard 2–3 additional Aave-ecosystem surfaces (e.g., Aave aToken/underlying trace links per reserve)
- Grow a public user base (newsletter + dashboard) with an AI-assisted update workflow (single maintainer + automated refresh/verification)
- Publish a monthly transparency report comparing displayed vs official values

### M4 — Sustainability experiment ($3,000)
- Evaluate opt-in data API / premium tier (never paywalling the verified baseline)
- Integrate community feedback into the roadmap and report outcomes to Aave Grants DAO

## Budget breakdown (total $15,000)

| Milestone | Amount | Use |
|---|---|---|
| M2 | $6,000 | Verification extension, frontend verification UI, alpha hosting, user feedback loop |
| M3 | $6,000 | Broader Aave coverage, user growth (AI-assisted operations), monthly transparency reports |
| M4 | $3,000 | Data API / premium experiment, ecosystem integrations |

All milestones are deliverable- and report-based; payments can be split per milestone.

## Team

- Single maintainer (individual developer) with AI-assisted automation for data refresh, verification, and operations — matching the "small team, low overhead" profile Aave Grants DAO supports.
- GitHub: https://github.com/12willy-byte

## Commitments and boundaries

- Stay open source (MIT), read-only, non-custodial, and tokenless.
- Never display a value as verified unless an official endpoint matched it within the documented tolerance.
- Never present stale data as current; the 24-hour freshness rule is enforced by CI.
- No financial, legal, or investment advice; every surface links to the original protocol for action.

## Links

- Repository: https://github.com/12willy-byte/aethra-intelligence
- Data sources policy: `docs/data-sources.md`
- Risk methodology: `docs/risk-methodology.md`
- Verification script: `backend/verify_sources.py`
- Live dataset snapshot: `data/opportunities.json` (generated 2026-08-16)
