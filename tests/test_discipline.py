from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from core.discipline import apply_discipline_actions, evaluate_position_discipline
from core.strategy import action_from_candidate, build_candidates, build_rotation_review


class DisciplineTests(unittest.TestCase):
    def base_config(self):
        return {
            "active_account_id": "a-share-paper",
            "daily_trade_limit": 4,
            "risk": {
                "hard_stop_enabled": True,
                "take_profit_enabled": True,
                "take_profit_fraction": 0.5,
                "max_position_pct": 0.25,
                "min_cash_pct": 0.1,
                "trailing_activation_pct": 8,
                "trailing_drawdown_pct": 4,
                "time_stop_days": 5,
                "time_stop_min_pnl_pct": -2.5,
                "volatility_shock_pct": -5,
            },
            "fees": {"commission_rate": 0.00025, "min_commission": 5, "stamp_duty_sell": 0.001},
        }

    def test_hard_stop_is_mandatory(self):
        position = {
            "symbol": "000001",
            "name": "止损样本",
            "market": "A",
            "account_id": "a-share-paper",
            "shares": 300,
            "cost_price": 10,
            "cost_basis": 3000,
            "latest_price": 8.9,
            "stop_loss": 9,
            "target_price": 12,
        }
        account = {"id": "a-share-paper", "market": "A", "currency": "CNY", "equity": 50000, "cash": 10000}
        action = evaluate_position_discipline(position, account, self.base_config(), "2026-06-23T10:30:00")
        self.assertEqual(action["action_code"], "hard_stop_sell_all")
        self.assertTrue(action["mandatory"])

    def test_mandatory_exit_does_not_count_against_daily_limit(self):
        positions = [
            {
                "symbol": "000001",
                "name": "止损样本",
                "market": "A",
                "account_id": "a-share-paper",
                "shares": 300,
                "cost_price": 10,
                "cost_basis": 3000,
                "latest_price": 8.9,
                "stop_loss": 9,
                "target_price": 12,
            }
        ]
        account = {"id": "a-share-paper", "market": "A", "currency": "CNY", "equity": 50000, "cash": 10000, "realized_pnl": 0}
        trade_log = []
        queue = apply_discipline_actions(positions, {"a-share-paper": account}, trade_log, "2026-06-23T10:30:00", self.base_config())
        self.assertEqual(len(positions), 0)
        self.assertEqual(queue[0]["action_code"], "hard_stop_sell_all")
        self.assertFalse(trade_log[0]["counts_against_daily_limit"])

    def test_take_profit_partial_marks_position(self):
        positions = [
            {
                "symbol": "000002",
                "name": "止盈样本",
                "market": "A",
                "account_id": "a-share-paper",
                "shares": 500,
                "cost_price": 10,
                "cost_basis": 5000,
                "latest_price": 12.1,
                "stop_loss": 9,
                "target_price": 12,
            }
        ]
        account = {"id": "a-share-paper", "market": "A", "currency": "CNY", "equity": 50000, "cash": 10000, "realized_pnl": 0}
        trade_log = []
        apply_discipline_actions(positions, {"a-share-paper": account}, trade_log, "2026-06-23T10:30:00", self.base_config())
        self.assertEqual(positions[0]["shares"], 300)
        self.assertTrue(positions[0]["take_profit_1_done"])
        self.assertEqual(trade_log[0]["type"], "reduce")

    def test_overheated_candidate_waits_for_pullback(self):
        config = self.base_config()
        account = {"cash": 40000, "equity": 50000}
        candidate = {"latest_price": 10, "score": 90, "setup_type": "overheated_pullback"}
        action, _ = action_from_candidate(candidate, account, config)
        self.assertEqual(action, "watch_pullback")


    def test_low_cash_candidate_is_avoided(self):
        config = self.base_config()
        config["strategy"] = {"cash_management": {"soft_cash_floor_pct": 0.18, "ideal_cash_floor_pct": 0.25}}
        account = {"cash": 2000, "equity": 50000}
        candidate = {
            "latest_price": 10,
            "score": 92,
            "expected_return_pct": 7.5,
            "setup_type": "trend_hold",
            "screen_passed": True,
            "priority_score": 90,
        }
        action, _ = action_from_candidate(candidate, account, config)
        self.assertEqual(action, "avoid_for_now")

    def test_build_candidates_filters_overheated_names(self):
        config = self.base_config()
        config["strategy"] = {
            "target_markets": ["A"],
            "max_candidates_per_market": 10,
            "max_total_candidates": 10,
            "focus_themes": ["AI"],
            "screening": {
                "min_score": 70,
                "min_expected_return_pct": 5,
                "max_heat_change_pct": 7,
                "prefer_pullback_near_entry": True,
                "focus_theme_bonus": 8,
                "non_focus_theme_bonus": 2,
            },
        }
        config["watchlists"] = {"A": [
            {"symbol": "000001", "name": "平安样本", "theme": "AI"},
            {"symbol": "000002", "name": "过热样本", "theme": "AI"},
        ]}
        market_context = {"quotes": {"A": {
            "000001": {"symbol": "000001", "name": "平安样本", "latest": 10.0, "prev_close": 9.85, "change_pct": 1.52},
            "000002": {"symbol": "000002", "name": "过热样本", "latest": 10.0, "prev_close": 9.0, "change_pct": 11.11},
        }}}
        candidates = build_candidates(config, market_context)
        self.assertEqual([c["symbol"] for c in candidates], ["000001"])

    def test_high_priority_candidate_can_be_direct_followed_more_actively(self):
        config = self.base_config()
        config["strategy"] = {"cash_management": {"soft_cash_floor_pct": 0.18, "ideal_cash_floor_pct": 0.25}}
        account = {"cash": 18000, "equity": 50000}
        candidate = {
            "latest_price": 10,
            "score": 85,
            "expected_return_pct": 7.2,
            "setup_type": "trend_hold",
            "screen_passed": True,
            "priority_score": 91,
            "entry_zone": [9.9, 10.1],
        }
        action, _ = action_from_candidate(candidate, account, config)
        self.assertEqual(action, "direct_follow")

    def test_watch_confirm_candidate_can_trigger_active_trim(self):
        config = self.base_config()
        config["risk"].update({
            "opportunity_review_days": 2,
            "rotation_min_candidate_score": 80,
            "active_trim_hold_days": 2,
            "active_trim_min_score_gap": 4,
            "active_trim_min_expected_return_gap_pct": 2,
            "rotation_underperform_pct": 3,
        })
        position = {
            "symbol": "000001",
            "name": "弱势持仓",
            "market": "A",
            "account_id": "a-share-paper",
            "shares": 600,
            "latest_price": 10,
            "target_price": 10.5,
            "unrealized_pnl_pct": 1.0,
            "today_pnl_pct": -2.0,
            "score": 76,
            "entry_date": "2026-06-20T09:30:00",
        }
        candidate = {
            "symbol": "000002",
            "name": "更强候选",
            "account_id": "a-share-paper",
            "market": "A",
            "committee_action": "watch_confirm",
            "committee_score": 84,
            "expected_return_pct": 8.5,
        }
        account = {"id": "a-share-paper", "market": "A"}
        action = build_rotation_review(position, candidate, account, "2026-06-23T10:30:00", config)
        self.assertEqual(action["action_code"], "active_rebalance_trim")
        self.assertEqual(action["sell_shares"], 300)


if __name__ == "__main__":
    unittest.main()

