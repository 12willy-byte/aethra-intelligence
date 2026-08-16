# Aethra Finance

Aethra Finance is a non-custodial DeFi yield intelligence tool.

It helps users compare public yield opportunities across chains, understand risk factors, and navigate to the original protocols. Aethra does not custody funds, execute trades, rebalance portfolios, or guarantee returns.

> **Data notice**: Displayed APY and TVL values come from third-party aggregator snapshots (DeFiLlama Yields). Each record carries its source, update time, verification status, and risk notes. Records verified against official protocol APIs are labeled with their verification source and time. Anything not verified is explicitly marked unverified. Do not treat this tool as financial, legal, or investment advice.

## Features

- Compare DeFi yield opportunities across chains and protocols
- Show APY, TVL, asset, chain, protocol, source, and update time
- Distinguish base APY from reward/farming APY (`apy_composition`)
- Explain risk factors in plain language with a transparent rule-based score
- Provide source links, manually curated contract review anchors, and chain explorer links
- 24-hour freshness labeling (`fresh` / `stale`) on the dataset snapshot

## Out of Scope

- No user deposits
- No vaults
- No automated rebalancing
- No cross-chain asset transfers
- No token launch
- No yield guarantees
- No investment advice

## Data Pipeline

```
DeFiLlama Yields API (public aggregator)
  -> backend/src/strategy_engine.py   (fetch, filter, select, score, snapshot)
  -> data/opportunities.json          (static dataset consumed by the frontend)
  -> frontend/index.html              (static dashboard)
```

- The generator filters for supported chains/assets, minimum TVL, and APY range, then selects a small reviewed subset with a stable-selection policy.
- `backend/verify_sources.py` cross-checks snapshot records against official protocol public APIs (Lido, Aave V3, Maple, Centrifuge). A record is marked `verified=True` only when **both** APY and TVL match official values within documented tolerances. Endpoints and field mappings are documented in the script header.
- GitHub Actions `release-guardrails.yml` runs dataset validation, frontend QA-diagnostic checks, unit tests, and legacy-narrative scans on push/PR.
- GitHub Actions `yield-refresh-candidate.yml` (scheduled) produces a review-only candidate artifact; it never auto-publishes data. Promotion requires human review.

## Quick Start

Serve the static dashboard from the repository root:

```bash
python3 -m http.server 3000
# open http://localhost:3000/frontend/
```

Refresh the yield snapshot from DeFiLlama:

```bash
cd backend
python3 src/strategy_engine.py --refresh --limit 12 --timeout 180
```

Cross-check the snapshot against official protocol APIs:

```bash
python3 verify_sources.py
```

Validate the dataset before release:

```bash
python3 src/strategy_engine.py --check-dataset --fail-on-warnings
```

Run unit tests:

```bash
python3 -m unittest discover -s backend/tests -p "test_*.py"
```

## Repository Layout

- `backend/` – normalization, risk scoring, official-source verification
- `frontend/` – static dashboard
- `data/` – generated dataset snapshot
- `docs/` – product, data-sources, risk methodology, architecture, disclaimer

## License

MIT – see [LICENSE](LICENSE).
