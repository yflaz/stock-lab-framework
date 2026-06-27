from __future__ import annotations

import json
import os
from copy import deepcopy
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]

DEFAULT_CONFIG: dict[str, Any] = {
    "system_name": "Stock Lab New",
    "timezone": "Asia/Shanghai",
    "execution_mode": "paper",
    "active_account_id": "a-share-paper",
    "daily_trade_limit": 4,
    "auto_enter_paper_positions": True,
    "accounts": [
        {
            "id": "a-share-paper",
            "label": "A股模拟账户",
            "market": "A",
            "currency": "CNY",
            "initial_cash": 50000.0,
            "cash": 50000.0,
            "broker": "paper",
        },
        {
            "id": "hk-paper",
            "label": "港股模拟账户",
            "market": "HK",
            "currency": "HKD",
            "initial_cash": 50000.0,
            "cash": 50000.0,
            "broker": "paper",
        },
        {
            "id": "us-paper",
            "label": "美股模拟账户",
            "market": "US",
            "currency": "USD",
            "initial_cash": 20000.0,
            "cash": 20000.0,
            "broker": "paper",
        },
    ],
    "risk": {
        "max_position_pct": 0.25,
        "max_theme_pct": 0.45,
        "min_cash_pct": 0.10,
        "hard_stop_enabled": True,
        "take_profit_enabled": True,
        "take_profit_fraction": 0.5,
        "trailing_activation_pct": 8.0,
        "trailing_drawdown_pct": 4.0,
        "time_stop_days": 5,
        "time_stop_min_pnl_pct": -2.5,
        "volatility_shock_pct": -5.0,
    },
    "fees": {
        "commission_rate": 0.00025,
        "min_commission": 5.0,
        "stamp_duty_sell": 0.001,
        "slippage_bps": 8,
    },
    "strategy": {
        "candidate_source": "watchlist",
        "max_candidates_per_market": 12,
        "target_markets": ["A", "HK", "US"],
        "focus_themes": [
            "Technology",
            "Healthcare",
            "Industrials",
            "Energy",
            "Consumer",
            "Financials",
            "Index/ETF",
        ],
        "position_sizing": {
            "S": 0.18,
            "A": 0.12,
            "B": 0.06,
            "C": 0.0,
        },
    },
    "watchlists": {
        "A": [],
        "HK": [],
        "US": [],
    },
}


def deep_merge(base: dict[str, Any], incoming: dict[str, Any]) -> dict[str, Any]:
    merged = deepcopy(base)
    for key, value in incoming.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = deep_merge(merged[key], value)
        else:
            merged[key] = value
    return merged


def load_config(path: Path | None = None) -> dict[str, Any]:
    config_path = path or ROOT / "config.json"
    config = deepcopy(DEFAULT_CONFIG)
    if config_path.exists():
        config = deep_merge(config, json.loads(config_path.read_text(encoding="utf-8")))
    configured_keys = dict(config.get("api_keys") or {})
    config["api_keys"] = {
        "twelve_data": os.getenv("TWELVE_DATA_API_KEY") or configured_keys.get("twelve_data", ""),
        "alpha_vantage": os.getenv("ALPHA_VANTAGE_API_KEY") or configured_keys.get("alpha_vantage", ""),
        "finnhub": os.getenv("FINNHUB_API_KEY") or configured_keys.get("finnhub", ""),
        "news_api": os.getenv("NEWS_API_KEY") or configured_keys.get("news_api", ""),
        "fred": os.getenv("FRED_API_KEY") or configured_keys.get("fred", ""),
    }
    return config
