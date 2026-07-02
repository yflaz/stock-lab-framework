from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from core.config import load_config
from core.state_builder import build_profit_analysis_by_account, build_trade_activity, initial_state


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
        self.assertIn("trade_activity", state)
        self.assertIn("news_processing", state["market_context"])
        self.assertIn("news_summary", state["market_context"])
        self.assertIn("today_actions", state["learning_center"])
        self.assertIn("today_action_summary", state["learning_center"])

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

    def test_build_trade_activity_marks_discipline_and_amount(self):
        activity = build_trade_activity(
            [
                {
                    "timestamp": "2026-07-02T09:31:00+08:00",
                    "account_id": "a-share-paper",
                    "symbol": "000100",
                    "name": "TCL科技",
                    "type": "reduce",
                    "shares": 100,
                    "price": 5.73,
                    "amount": 0,
                    "reason": "纪律减仓",
                    "discipline_action": True,
                    "counts_against_daily_limit": False,
                },
                {
                    "timestamp": "2026-07-02T09:57:00+08:00",
                    "account_id": "a-share-paper",
                    "symbol": "600378",
                    "name": "昊华科技",
                    "type": "buy",
                    "shares": 100,
                    "price": 83.85,
                    "reason": "主动买入",
                    "counts_against_daily_limit": True,
                    "opportunity_label": "第 1 次机会",
                },
            ],
            "2026-07-02T10:00:10+08:00",
            "a-share-paper",
        )
        self.assertEqual(activity["discipline_count"], 1)
        self.assertEqual(activity["active_buy_count"], 1)
        self.assertEqual(activity["items"][0]["action_label"], "主动买入")
        self.assertEqual(activity["items"][1]["action_label"], "纪律减仓")
        self.assertEqual(activity["items"][1]["amount"], 573.0)
        self.assertTrue(any("不占用主动交易机会" in line for line in activity["summary_lines"]))


if __name__ == "__main__":
    unittest.main()
