# Aethra Finance Backend

The backend is a transparent risk scoring and data normalization layer for a non-custodial information product.

It does not execute trades, rebalance portfolios, send transactions, bridge assets, or custody funds.

## Current File

- `src/strategy_engine.py`: DeFiLlama yield snapshot normalizer plus transparent risk scoring

## Running

Print local fallback scoring:

```bash
python3 src/strategy_engine.py
```

Refresh the dashboard dataset:

```bash
python3 src/strategy_engine.py --refresh --limit 12 --timeout 180
```

This writes `../data/opportunities.json`.

Refresh selection prefers pool ids from the current reviewed `../data/opportunities.json` when they still pass the source filters. This reduces candidate churn from small DeFiLlama ranking moves while still updating APY, TVL, APY composition, and risk metadata from the latest source snapshot.

To inspect raw source ranking without this stability preference:

```bash
python3 src/strategy_engine.py --refresh --limit 12 --timeout 180 --ignore-selection-baseline --output ../data/refresh-candidate.json
```

Add protocol review links to the existing snapshot without refreshing APY/TVL:

```bash
python3 src/strategy_engine.py --enrich-existing
```

Check whether the current dataset is release-ready:

```bash
python3 src/strategy_engine.py --check-dataset
```

The check fails for stale snapshots, missing required fields, invalid APY/TVL/risk values, or demo/fallback records. Use `--fail-on-warnings` for candidate releases that must also have complete verification metadata:

```bash
python3 src/strategy_engine.py --check-dataset --fail-on-warnings
```

The scheduled `Yield Refresh Candidate` GitHub Actions workflow writes refreshed data to an artifact for manual review. It does not update `data/opportunities.json`, commit, push, or deploy.

Check that the frontend still includes the hidden preview QA diagnostics used during owner-only hosted QA:

```bash
python3 src/strategy_engine.py --check-frontend-qa
```

This checks for the `/frontend/?qa=1` diagnostics hooks and confirms the QA panel is not present in the default static markup.

Check that the current source review matrix covers the committed dataset snapshot:

```bash
python3 src/strategy_engine.py --check-source-review-matrix
```

This checks that the latest `docs/reviews/source-review-matrix-*.md` file mentions the current dataset timestamp, every displayed pool id, every displayed record label, and each populated primary contract anchor. It only validates documentation coverage for internal review; it is not proof that APY, TVL, protocol safety, audit scope, liquidity, redemption timing, or legal suitability have been verified.

Compare a refresh candidate against the committed dashboard snapshot:

```bash
python3 src/strategy_engine.py --compare-candidate --candidate ../data/refresh-candidate.json
```

This prints added, removed, and materially changed records. It is a review report, not proof that APY, TVL, contracts, or protocol safety have been verified.

Run backend unit tests:

```bash
python3 -m unittest discover -s tests -p "test_*.py"
```

## Data Rule

Every displayed APY and TVL value should include a source URL and update time. DeFiLlama records are third-party aggregator data and remain marked unverified until checked against original protocols.

When the source snapshot supplies APY components, records include `apy_base`, `apy_reward`, `apy_source_label`, `apy_composition`, `pool_meta`, and `reward_tokens`. These fields are used to distinguish base yield from reward or farming yield. They do not prove reward availability, reward value, sustainability, liquidity, or investment suitability.

DeFiLlama pool ids are stored as pool references, not contract addresses. Leave `contract_address` and `explorer_url` empty unless the exact chain deployment has been verified against the original protocol and a chain explorer.
