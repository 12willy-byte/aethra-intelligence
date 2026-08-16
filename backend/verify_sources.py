"""
Aethra Finance — cross-check snapshot opportunities against ORIGINAL protocol
official public APIs.

Discipline (same as the project's data-sources policy):
  - verified=True ONLY when an official public endpoint was reachable AND the
    returned value matches the snapshot within tolerance.
  - APY and TVL must BOTH match for verified=True. A dimension with no
    reference value, an unreachable endpoint, or an out-of-tolerance value
    keeps the record unverified with an explicit reason.
  - This script does NOT fetch a new snapshot; it only verifies the existing
    dataset entries and writes a report. It never fabricates a verification.

Tolerance policy (documented, applied uniformly):
  - APY: within 30% relative OR 0.5 percentage points absolute (protocol APY
    definitions differ: base vs rewards-inclusive, weekly vs monthly, and the
    snapshot date differs from "now", so we compare loosely but record the
    exact reference values).
  - TVL: within 25% relative (TVL moves daily; exact match is not expected).

Verified endpoints and field mappings (probed 2026-08-14):
  - Lido        : https://eth-api.lido.fi/v1/protocol/steth/apr/last  -> data.apr (%)
                  https://eth-api.lido.fi/v1/protocol/steth/stats    -> marketCap (USD)
  - AAVE V3 Eth : https://api.v3.aave.com/graphql markets(chainIds:[1])
                  APY = reserve.supplyInfo.apy.value * 100
                  TVL = reserve.borrowInfo.availableLiquidity.usd
                  (DeFiLlama Aave V3 TVL tracks official available liquidity,
                   NOT total supply; total supply is ~6x larger)
  - Maple       : https://api.maple.finance/v2/graphql poolV2(id)
                  APY = weeklyApy / 1e28 (%)
                  TVL = totalAssets / 1e6 (pool-asset basis; does NOT match
                  DeFiLlama TVL ~2.4x, so Maple TVL is recorded but fails)
  - Centrifuge  : https://api.centrifuge.io/ pools / tokenSnapshots
                  APY = latest tokenSnapshot yield7d365 / 1e27 (%)
                  TVL = token totalIssuance / 1e6 * tokenPrice / 1e18 (pool
                  level; Base spoke TVL is chain-level, so pool-level does not
                  match the Base snapshot and is recorded as a mismatch)
  - Sky / Sparklend / Ether.fi / Spark Savings: no official public API found
    during probing (403/308/404), so they stay unverified.

Usage:
  python3 backend/verify_sources.py [--dataset ../data/refresh-candidate.json]
                                    [--report ../data/verification_report_YYYYMMDD.json]
                                    [--apply]
  --apply also writes the verified/verifiedAt/verifiedSource fields back into
  the dataset file. Default: report only, dataset untouched.
"""

from __future__ import annotations

import argparse
import json
import ssl
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional
from urllib.request import Request, urlopen

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = PROJECT_ROOT / "data"
DEFAULT_DATASET = DATA_DIR / "opportunities.json"

UA = "Mozilla/5.0 (aethra-verify/0.2)"
TIMEOUT = 15
APY_REL_TOL = 0.30
APY_ABS_TOL = 0.5
TVL_REL_TOL = 0.25

LIDO_APR_URL = "https://eth-api.lido.fi/v1/protocol/steth/apr/last"
LIDO_STATS_URL = "https://eth-api.lido.fi/v1/protocol/steth/stats"
AAVE_URL = "https://api.v3.aave.com/graphql"
AAVE_MAINNET_POOL = "0x87870bca3f3fd6335c3f4ce8392d69350b4fa4e2"
MAPLE_URL = "https://api.maple.finance/v2/graphql"
CENTRIFUGE_URL = "https://api.centrifuge.io/"


def http_json(url: str, data: Optional[bytes] = None, headers: Optional[dict] = None) -> Any:
    h = {"User-Agent": UA}
    if headers:
        h.update(headers)
    req = Request(url, headers=h, data=data)
    ctx = ssl.create_default_context()
    with urlopen(req, timeout=TIMEOUT, context=ctx) as r:
        return json.loads(r.read())


def within_tolerance(snapshot: float, reference: float, rel: float, abs_tol: float = 0.0) -> bool:
    if snapshot is None or reference is None:
        return False
    if abs(snapshot - reference) <= abs_tol:
        return True
    if reference == 0:
        return False
    return abs(snapshot - reference) / abs(reference) <= rel


def graphql(url: str, query: str) -> dict[str, Any]:
    payload = json.dumps({"query": query}).encode()
    return http_json(url, data=payload, headers={"Content-Type": "application/json"})


def as_number(value: Any) -> Optional[float]:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


# ---------------------------------------------------------------------------
# Verifiers: each returns a dict with referenceApy / referenceTvl (None when
# unavailable), apyOk / tvlOk (both required for verified), source, note.
# ---------------------------------------------------------------------------

def verify_lido(opp: dict) -> dict:
    snapshot_apy = as_number(opp.get("apy"))
    snapshot_tvl = as_number(opp.get("tvl"))
    source = "https://docs.lido.fi/integrations/api/"
    try:
        apr = http_json(LIDO_APR_URL)
        stats = http_json(LIDO_STATS_URL)
        ref_apy = as_number(((apr.get("data") or {}).get("apr")))
        ref_tvl = as_number(stats.get("marketCap"))
        apy_ok = within_tolerance(snapshot_apy or 0, ref_apy or 0, APY_REL_TOL, APY_ABS_TOL)
        tvl_ok = within_tolerance(snapshot_tvl or 0, ref_tvl or 0, TVL_REL_TOL)
        return {
            "referenceApy": ref_apy,
            "referenceTvl": ref_tvl,
            "apyOk": bool(apy_ok),
            "tvlOk": bool(tvl_ok),
            "source": source,
            "note": (
                f"official eth-api.lido.fi APR={ref_apy}% snapshot={snapshot_apy} "
                f"| marketCap={ref_tvl:,.0f} snapshot={snapshot_tvl:,.0f}"
            ),
        }
    except Exception as e:
        return {
            "referenceApy": None,
            "referenceTvl": None,
            "apyOk": False,
            "tvlOk": False,
            "source": LIDO_APR_URL,
            "note": f"endpoint failed: {type(e).__name__}: {e}",
        }


def verify_aave(opp: dict) -> dict:
    snapshot_apy = as_number(opp.get("apy"))
    snapshot_tvl = as_number(opp.get("tvl"))
    asset = str(opp.get("asset") or "").upper()
    query = (
        '{ markets(request: { chainIds: [1] }) { address name reserves { '
        'underlyingToken { symbol } usdExchangeRate '
        'supplyInfo { apy { value } total { value } } '
        'borrowInfo { availableLiquidity { usd } } } } }'
    )
    try:
        data = graphql(AAVE_URL, query)
        if "errors" in data:
            return {
                "referenceApy": None, "referenceTvl": None,
                "apyOk": False, "tvlOk": False,
                "source": AAVE_URL,
                "note": f"GraphQL errors: {json.dumps(data['errors'])[:200]}",
            }
        market = None
        for m in (data.get("data") or {}).get("markets") or []:
            if str(m.get("address") or "").lower() == AAVE_MAINNET_POOL:
                market = m
                break
        if market is None:
            return {
                "referenceApy": None, "referenceTvl": None,
                "apyOk": False, "tvlOk": False,
                "source": AAVE_URL,
                "note": f"Aave V3 Ethereum market {AAVE_MAINNET_POOL} not found",
            }
        reserve = None
        for r in market.get("reserves") or []:
            if str((r.get("underlyingToken") or {}).get("symbol") or "").upper() == asset:
                reserve = r
                break
        if reserve is None:
            return {
                "referenceApy": None, "referenceTvl": None,
                "apyOk": False, "tvlOk": False,
                "source": AAVE_URL,
                "note": f"reserve {asset} not found in Aave V3 Ethereum",
            }
        apy_value = as_number(((reserve.get("supplyInfo") or {}).get("apy") or {}).get("value"))
        ref_apy = apy_value * 100 if apy_value is not None else None
        borrow_info = reserve.get("borrowInfo") or {}
        ref_tvl = as_number(((borrow_info.get("availableLiquidity") or {}).get("usd")))
        apy_ok = within_tolerance(snapshot_apy or 0, ref_apy or 0, APY_REL_TOL, APY_ABS_TOL)
        tvl_ok = within_tolerance(snapshot_tvl or 0, ref_tvl or 0, TVL_REL_TOL)
        return {
            "referenceApy": ref_apy,
            "referenceTvl": ref_tvl,
            "apyOk": bool(apy_ok),
            "tvlOk": bool(tvl_ok),
            "source": AAVE_URL,
            "note": (
                f"official Aave V3 GraphQL supplyAPY={ref_apy:.4f}% snapshot={snapshot_apy} "
                f"| availableLiquidity={ref_tvl:,.0f} snapshot={snapshot_tvl:,.0f} "
                "(DeFiLlama Aave TVL tracks available liquidity, not total supply)"
            ),
        }
    except Exception as e:
        return {
            "referenceApy": None, "referenceTvl": None,
            "apyOk": False, "tvlOk": False,
            "source": AAVE_URL,
            "note": f"endpoint failed: {type(e).__name__}: {e}",
        }


def verify_maple(opp: dict) -> dict:
    snapshot_apy = as_number(opp.get("apy"))
    snapshot_tvl = as_number(opp.get("tvl"))
    pool_id = str(opp.get("contract_address") or opp.get("contract") or "").lower()
    if not pool_id:
        return {
            "referenceApy": None, "referenceTvl": None,
            "apyOk": False, "tvlOk": False,
            "source": MAPLE_URL,
            "note": "no pool contract address in snapshot",
        }
    query = '{ poolV2(id: "%s") { id name weeklyApy monthlyApy totalAssets } }' % pool_id
    try:
        data = graphql(MAPLE_URL, query)
        pool = (data.get("data") or {}).get("poolV2") or {}
        if not pool:
            return {
                "referenceApy": None, "referenceTvl": None,
                "apyOk": False, "tvlOk": False,
                "source": MAPLE_URL,
                "note": f"poolV2 {pool_id} not found",
            }
        weekly = as_number(pool.get("weeklyApy"))
        monthly = as_number(pool.get("monthlyApy"))
        ref_apy = (weekly or monthly or 0) / 1e28
        ref_tvl = as_number(pool.get("totalAssets"))
        if ref_tvl is not None:
            ref_tvl = ref_tvl / 1e6  # 6-decimal asset basis
        apy_ok = within_tolerance(snapshot_apy or 0, ref_apy, APY_REL_TOL, APY_ABS_TOL)
        tvl_ok = within_tolerance(snapshot_tvl or 0, ref_tvl or 0, TVL_REL_TOL)
        return {
            "referenceApy": ref_apy,
            "referenceTvl": ref_tvl,
            "apyOk": bool(apy_ok),
            "tvlOk": bool(tvl_ok),
            "source": MAPLE_URL,
            "note": (
                f"official Maple GraphQL weekly={weekly / 1e28:.4f}% snapshot={snapshot_apy} "
                f"| totalAssets={ref_tvl:,.0f} snapshot={snapshot_tvl:,.0f} "
                "(totalAssets is pool-asset basis; official AUM via Maple Transparency "
                "page must be checked manually for TVL)"
            ),
        }
    except Exception as e:
        return {
            "referenceApy": None, "referenceTvl": None,
            "apyOk": False, "tvlOk": False,
            "source": MAPLE_URL,
            "note": f"endpoint failed: {type(e).__name__}: {e}",
        }


CENTRIFUGE_POOLS = (
    # (chain, asset, pool-name fragment, token symbol)
    ("Ethereum", "USDS", "Janus Henderson Treasury Fund", "JTRSY"),
    ("Base", "USDC", "Janus Henderson AAA CLO Fund", "JAAA"),
)


def verify_centrifuge(opp: dict) -> dict:
    snapshot_apy = as_number(opp.get("apy"))
    snapshot_tvl = as_number(opp.get("tvl"))
    chain = str(opp.get("chain") or "")
    asset = str(opp.get("asset") or "").upper()
    match = next((p for p in CENTRIFUGE_POOLS if p[0] == chain and p[1] == asset), None)
    if match is None:
        return {
            "referenceApy": None, "referenceTvl": None,
            "apyOk": False, "tvlOk": False,
            "source": CENTRIFUGE_URL,
            "note": f"no Centrifuge pool mapping for {chain} / {asset}",
        }
    name_fragment, token_symbol = match[2], match[3]
    query = (
        '{ pools(limit: 100) { items { id name tokens { items { symbol totalIssuance tokenPrice } } } } }'
    )
    try:
        data = graphql(CENTRIFUGE_URL, query)
        if "errors" in data:
            return {
                "referenceApy": None, "referenceTvl": None,
                "apyOk": False, "tvlOk": False,
                "source": CENTRIFUGE_URL,
                "note": f"GraphQL errors: {json.dumps(data['errors'])[:200]}",
            }
        pool = None
        for p in ((data.get("data") or {}).get("pools") or {}).get("items") or []:
            if name_fragment in str(p.get("name") or ""):
                pool = p
                break
        if pool is None:
            return {
                "referenceApy": None, "referenceTvl": None,
                "apyOk": False, "tvlOk": False,
                "source": CENTRIFUGE_URL,
                "note": f"Centrifuge pool {name_fragment!r} not found in public listing",
            }
        token = None
        for t in ((pool.get("tokens") or {}).get("items") or []):
            if str(t.get("symbol") or "") == token_symbol:
                token = t
                break
        if token is None:
            return {
                "referenceApy": None, "referenceTvl": None,
                "apyOk": False, "tvlOk": False,
                "source": CENTRIFUGE_URL,
                "note": f"token {token_symbol} not found in pool {pool.get('name')}",
            }
        issuance = as_number(token.get("totalIssuance"))
        price = as_number(token.get("tokenPrice"))
        ref_tvl = None
        if issuance is not None and price is not None:
            ref_tvl = (issuance / 1e6) * (price / 1e18)  # pool-level USD
        # Latest token snapshot keyed by the exact raw issuance value.
        snap_query = (
            '{ tokenSnapshots(limit: 5, where: { totalIssuance: "%s" }) '
            "{ items { timestamp yield7d365 } } }" % token.get("totalIssuance")
        )
        snap_data = graphql(CENTRIFUGE_URL, snap_query)
        ref_apy = None
        latest_ts = 0
        for snap in ((snap_data.get("data") or {}).get("tokenSnapshots") or {}).get("items") or []:
            ts = as_number(snap.get("timestamp")) or 0
            y = as_number(snap.get("yield7d365"))
            if y is not None and ts >= latest_ts:
                latest_ts = ts
                ref_apy = (y / 1e27) * 100  # yield fields are 1e27 precision, decimal fraction -> percent
        apy_ok = within_tolerance(snapshot_apy or 0, ref_apy or 0, APY_REL_TOL, APY_ABS_TOL)
        tvl_ok = within_tolerance(snapshot_tvl or 0, ref_tvl or 0, TVL_REL_TOL)
        return {
            "referenceApy": ref_apy,
            "referenceTvl": ref_tvl,
            "apyOk": bool(apy_ok),
            "tvlOk": bool(tvl_ok),
            "source": CENTRIFUGE_URL,
            "note": (
                f"official Centrifuge {token_symbol} yield7d365={ref_apy:.4f}% snapshot={snapshot_apy} "
                f"| pool-level TVL={ref_tvl:,.0f} snapshot={snapshot_tvl:,.0f} "
                "(pool-level TVL; Base spoke chain-level TVL may differ)"
            ),
        }
    except Exception as e:
        return {
            "referenceApy": None, "referenceTvl": None,
            "apyOk": False, "tvlOk": False,
            "source": CENTRIFUGE_URL,
            "note": f"endpoint failed: {type(e).__name__}: {e}",
        }


def verify_unavailable(opp: dict, reason: str) -> dict:
    return {
        "referenceApy": None,
        "referenceTvl": None,
        "apyOk": False,
        "tvlOk": False,
        "source": None,
        "note": reason,
    }


VERIFIERS = {
    "Lido": verify_lido,
    "AAVE V3": verify_aave,
    "Maple": verify_maple,
    "Centrifuge Protocol": verify_centrifuge,
}


def verify_record(opp: dict) -> dict:
    protocol = str(opp.get("protocol") or "")
    verifier = VERIFIERS.get(protocol)
    if verifier is None:
        result = verify_unavailable(
            opp, f"no official public API endpoint confirmed for protocol {protocol!r}"
        )
    else:
        result = verifier(opp)
    result["verified"] = bool(result["apyOk"] and result["tvlOk"])
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description="Verify snapshot opportunities against official protocol APIs")
    parser.add_argument("--dataset", type=Path, default=DEFAULT_DATASET, help="Dataset JSON to verify")
    parser.add_argument("--report", type=Path, default=None, help="Report output path")
    parser.add_argument("--apply", action="store_true", help="Write verification fields back into the dataset")
    args = parser.parse_args()

    dataset_path = args.dataset
    report_path = args.report or (DATA_DIR / f"verification_report_{datetime.now(timezone.utc):%Y%m%d}.json")
    try:
        data = json.loads(dataset_path.read_text("utf-8"))
    except (OSError, json.JSONDecodeError) as e:
        print(f"cannot read dataset {dataset_path}: {e}")
        return 1
    opportunities: list = data.get("opportunities") if isinstance(data, dict) else data
    if not isinstance(opportunities, list):
        print(f"unexpected opportunities shape: {type(data)}")
        return 1

    now = datetime.now(timezone.utc).isoformat()
    report = {"verifiedAt": now, "dataset": str(dataset_path), "items": []}
    verified_count = 0

    for opp in opportunities:
        result = verify_record(opp)
        if result["verified"]:
            opp["verified"] = True
            opp["verifiedAt"] = now
            opp["verifiedSource"] = result["source"]
            verified_count += 1
        else:
            # Keep existing verification fields untouched for unverified records;
            # never carry a stale verified=True forward.
            opp["verified"] = False
        report["items"].append({
            "id": opp.get("id"),
            "protocol": opp.get("protocol"),
            "asset": opp.get("asset"),
            "chain": opp.get("chain"),
            "snapshotApy": opp.get("apy"),
            "snapshotTvl": opp.get("tvl"),
            "referenceApy": result["referenceApy"],
            "referenceTvl": result["referenceTvl"],
            "verifiedApy": bool(result["apyOk"]),
            "verifiedTvl": bool(result["tvlOk"]),
            "verified": result["verified"],
            "source": result["source"],
            "note": result["note"],
        })

    report["summary"] = {
        "verified": verified_count,
        "total": len(opportunities),
        "apyVerified": sum(1 for item in report["items"] if item["verifiedApy"]),
        "tvlVerified": sum(1 for item in report["items"] if item["verifiedTvl"]),
    }
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", "utf-8")

    if args.apply:
        dataset_path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", "utf-8")
        print(f"applied verification fields to {dataset_path}")

    print(f"verified: {verified_count}/{len(opportunities)}  (report: {report_path})")
    for item in report["items"]:
        print(
            f"  [{'V' if item['verified'] else ' '}] {item['protocol']:<22} {item['asset']:<6} "
            f"apy={item['verifiedApy']} tvl={item['verifiedTvl']} "
            f"ref_apy={item['referenceApy']} ref_tvl={item['referenceTvl']} :: {item['note'][:100]}"
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
