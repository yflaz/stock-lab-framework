from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from core.config import load_config
from core.state_builder import build_profit_analysis_by_account, initial_state


class StateContractTests(unittest.TestCase):
    def test_initial_state_has_empty_decision_fields(self):
        state = initial_state(load_config())
        decision = state["decision_latest"]
        self.assertEqual(decision["summary"], "")
        self.assertEqual(decision["why_buy"], [])
        self.assertEqual(decision["why_sell"], [])

    def test_accounts_are_exposed_for_dashboard_selector(self):
        state = initial_state(load_config())
        self.assertGreaterEqual(len(state["accounts"]), 3)
        self.assertIn("active_account_id", state)

    def test_mobile_state_sections_exist_in_initial_state(self):
        state = initial_state(load_config())
        self.assertIn("account_analytics", state)
        self.assertIn("profit_analysis_by_account", state)
        self.assertIn("thought_process", state)
        self.assertIn("learning_center", state)

    def test_profit_analysis_is_built_for_each_account(self):
        accounts = {
            "a-share-paper": {"id": "a-share-paper", "label": "A股", "currency": "CNY", "equity": 50000, "initial_cash": 50000},
            "us-paper": {"id": "us-paper", "label": "美股", "currency": "USD", "equity": 10000, "initial_cash": 10000},
        }
        analytics = {
            "a-share-paper": {"return_pct": 0, "exposure": {"by_theme": [], "by_market": []}},
            "us-paper": {"return_pct": 0, "exposure": {"by_theme": [], "by_market": []}},
        }
        result = build_profit_analysis_by_account(accounts, [], [], analytics)
        self.assertEqual(set(result), {"a-share-paper", "us-paper"})
        self.assertEqual(result["us-paper"]["currency"], "USD")


if __name__ == "__main__":
    unittest.main()
