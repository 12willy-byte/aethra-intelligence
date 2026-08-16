import json
import sys
import tempfile
import unittest
from pathlib import Path


sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from strategy_engine import (  # noqa: E402
    PROJECT_ROOT,
    YieldOpportunity,
    display_path,
    load_preferred_pool_ids,
    select_diverse_opportunities,
)


def opportunity(pool_id: str, chain: str, tvl: float) -> YieldOpportunity:
    return YieldOpportunity(
        id=pool_id,
        chain=chain,
        protocol="Spark",
        asset="USDS",
        strategy="Stable yield",
        apy=3.5,
        tvl=tvl,
        updated="Test snapshot",
        source="https://defillama.com/yields",
        source_label="DeFiLlama Yields",
        contract="Not provided by DeFiLlama pool snapshot",
        contract_address="",
        contract_verification="Not verified in test fixture.",
        audit="Not provided by DeFiLlama pool snapshot",
        factors=("Test fixture",),
        source_pool_id=pool_id,
        pool_reference=f"DeFiLlama pool id: {pool_id}",
        pool_verification="Test fixture.",
    )


class SelectionPolicyTest(unittest.TestCase):
    def test_display_path_uses_project_relative_path_when_possible(self) -> None:
        self.assertEqual(display_path(PROJECT_ROOT / "data" / "opportunities.json"), "data/opportunities.json")

    def test_display_path_keeps_external_paths_explicit(self) -> None:
        self.assertEqual(display_path(Path("/tmp/aethra-baseline.json")), "/tmp/aethra-baseline.json")

    def test_load_preferred_pool_ids_preserves_reviewed_order(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "opportunities.json"
            path.write_text(
                json.dumps(
                    {
                        "opportunities": [
                            {"source_pool_id": "reviewed-a"},
                            {"id": "reviewed-b"},
                            {"source_pool_id": "reviewed-a"},
                            {"source_pool_id": ""},
                        ]
                    }
                ),
                encoding="utf-8",
            )

            self.assertEqual(load_preferred_pool_ids(path), ("reviewed-a", "reviewed-b"))

    def test_chain_pick_prefers_reviewed_pool_over_higher_tvl_peer(self) -> None:
        selected = select_diverse_opportunities(
            [
                opportunity("arbitrum-raw-higher", "Arbitrum", 500),
                opportunity("arbitrum-reviewed", "Arbitrum", 100),
                opportunity("base-raw", "Base", 200),
                opportunity("ethereum-reviewed", "Ethereum", 300),
            ],
            limit=3,
            preferred_pool_ids=("arbitrum-reviewed", "ethereum-reviewed"),
        )

        self.assertEqual([item.id for item in selected], ["arbitrum-reviewed", "base-raw", "ethereum-reviewed"])

    def test_remaining_reviewed_pools_fill_before_unreviewed_tvl_ranking(self) -> None:
        selected = select_diverse_opportunities(
            [
                opportunity("ethereum-unreviewed-high", "Ethereum", 500),
                opportunity("ethereum-reviewed-one", "Ethereum", 100),
                opportunity("ethereum-reviewed-two", "Ethereum", 90),
            ],
            limit=3,
            preferred_pool_ids=("ethereum-reviewed-one", "ethereum-reviewed-two"),
        )

        self.assertEqual(
            [item.id for item in selected],
            ["ethereum-reviewed-one", "ethereum-reviewed-two", "ethereum-unreviewed-high"],
        )

    def test_unreviewed_tvl_ranking_fills_when_no_preferred_ids_match(self) -> None:
        selected = select_diverse_opportunities(
            [
                opportunity("base-high", "Base", 300),
                opportunity("ethereum-mid", "Ethereum", 200),
                opportunity("arbitrum-low", "Arbitrum", 100),
            ],
            limit=2,
            preferred_pool_ids=("missing-reviewed-id",),
        )

        self.assertEqual([item.id for item in selected], ["arbitrum-low", "base-high"])


if __name__ == "__main__":
    unittest.main()
