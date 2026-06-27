from __future__ import annotations

import sys
import unittest
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from core.discipline import apply_discipline_actions
from core.strategy import apply_entry_orders
from core.utils import current_phase


class MarketSessionTests(unittest.TestCase):
    def test_us_market_phase_uses_new_york_clock(self):
        moment = datetime(2026, 6, 29, 13, 45, tzinfo=ZoneInfo("America/New_York"))
        self.assertEqual(current_phase(moment, market="US"), "hourly_review_pm1")

    def test_weekend_is_non_trading_day(self):
        moment = datetime(2026, 6, 28, 10, 0, tzinfo=ZoneInfo("Asia/Shanghai"))
        self.assertEqual(current_phase(moment, market="A"), "non_trading_day")

    def test_entry_orders_only_execute_for_active_market(self):
        positions = []
        orders = [
            {
                "symbol": "TESTHK1.HK",
                "name": "HK Test Asset 1",
                "market": "HK",
                "account_id": "hk-paper",
                "committee_action": "direct_follow",
                "latest_price": 50,
                "entry_zone": [49.5, 50.5],
                "theme": "互联网/AI",
                "confidence": "A",
                "target_position_pct": 0.12,
                "reason": ["测试"],
                "risks": [],
                "stop_loss": 470,
                "target_price": 560,
                "score": 85,
            },
            {
                "symbol": "USTEST1",
                "name": "US Test Asset 1",
                "market": "US",
                "account_id": "us-paper",
                "committee_action": "direct_follow",
                "latest_price": 150,
                "entry_zone": [149, 151],
                "theme": "AI/算力",
                "confidence": "A",
                "target_position_pct": 0.12,
                "reason": ["测试"],
                "risks": [],
                "stop_loss": 140,
                "target_price": 168,
                "score": 88,
            },
        ]
        accounts = {
            "hk-paper": {"id": "hk-paper", "market": "HK", "currency": "HKD", "cash": 50000, "equity": 50000},
            "us-paper": {"id": "us-paper", "market": "US", "currency": "USD", "cash": 20000, "equity": 20000},
        }
        config = {
            "auto_enter_paper_positions": True,
            "daily_trade_limit": 4,
            "fees": {"commission_rate": 0.00025, "min_commission": 1, "slippage_bps": 8},
        }
        trade_log = []
        fills = apply_entry_orders(
            positions,
            orders,
            accounts,
            trade_log,
            "2026-06-29T09:30:00+08:00",
            "opening_trade",
            config,
            active_markets={"HK"},
        )
        self.assertEqual(len(fills), 1)
        self.assertEqual(fills[0]["market"], "HK")
        self.assertEqual(len(positions), 1)
        self.assertEqual(positions[0]["market"], "HK")

    def test_discipline_only_runs_for_active_market(self):
        positions = [
            {
                "symbol": "TESTHK1.HK",
                "name": "HK Test Asset 1",
                "market": "HK",
                "account_id": "hk-paper",
                "shares": 200,
                "cost_price": 500,
                "cost_basis": 100000,
                "latest_price": 480,
                "stop_loss": 490,
                "target_price": 560,
            },
            {
                "symbol": "USTEST1",
                "name": "US Test Asset 1",
                "market": "US",
                "account_id": "us-paper",
                "shares": 10,
                "cost_price": 150,
                "cost_basis": 1500,
                "latest_price": 130,
                "stop_loss": 140,
                "target_price": 170,
            },
        ]
        accounts = {
            "hk-paper": {"id": "hk-paper", "market": "HK", "currency": "HKD", "equity": 50000, "cash": 50000, "realized_pnl": 0},
            "us-paper": {"id": "us-paper", "market": "US", "currency": "USD", "equity": 20000, "cash": 20000, "realized_pnl": 0},
        }
        config = {
            "active_account_id": "hk-paper",
            "risk": {"hard_stop_enabled": True, "take_profit_enabled": True, "take_profit_fraction": 0.5, "max_position_pct": 0.25, "min_cash_pct": 0.1, "trailing_activation_pct": 8, "trailing_drawdown_pct": 4, "time_stop_days": 5, "time_stop_min_pnl_pct": -2.5, "volatility_shock_pct": -5},
            "fees": {"commission_rate": 0.00025, "min_commission": 1, "stamp_duty_sell": 0.001},
        }
        trade_log = []
        queue = apply_discipline_actions(
            positions,
            accounts,
            trade_log,
            "2026-06-29T09:30:00+08:00",
            config,
            active_markets={"HK"},
        )
        self.assertEqual(len(queue), 1)
        self.assertEqual(queue[0]["market"], "HK")
        self.assertEqual(len(trade_log), 1)
        self.assertEqual(trade_log[0]["market"], "HK")


if __name__ == "__main__":
    unittest.main()
