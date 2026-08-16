# Architecture

Aethra Finance is a non-custodial information product. The MVP does not hold user funds, submit transactions, rebalance portfolios, or bridge assets.

## System Overview

```
Public Data Sources
  -> Ingestion Scripts
  -> Normalized Yield Dataset
  -> Transparent Risk Scoring
  -> Static/API Output
  -> Frontend Dashboard
```

## Components

### Frontend

The first UI is a static dashboard in `frontend/index.html`.

It provides:

- Opportunity table
- Filters
- Detail panel
- Local watchlist
- Risk explanations
- Data source notes

### Backend

The backend is a lightweight scoring and normalization layer.

It provides:

- Demo opportunity records
- Transparent risk scoring
- JSON output for frontend or later API use

It does not provide automated strategy execution.

### Data Layer

Each opportunity should be normalized into a common schema:

- `chain`
- `protocol`
- `asset`
- `strategy_type`
- `apy_pct`
- `tvl_usd`
- `source_url`
- `updated_at`
- `contract_address`
- `audit_status`
- `risk_factors`

## Security Boundary

Because the MVP is non-custodial:

- There are no deposit contracts.
- There are no token approvals.
- There is no transaction executor.
- There is no cross-chain messaging layer.
- Wallet connection is not required for core use.

Security work focuses on data integrity, source labeling, UI clarity, and avoiding misleading financial claims.

## Future Review Gates

Custody, vaults, tokenomics, and automated execution can only be reconsidered after:

- Verified user demand
- Reliable data pipeline
- Threat model
- Legal review
- Independent smart contract audit
- Clear incident response process

Until those gates are met, Aethra remains an informational tool.
