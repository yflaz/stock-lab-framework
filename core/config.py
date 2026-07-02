from __future__ import annotations

import json
import os
from copy import deepcopy
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]

DEFAULT_CONFIG: dict[str, Any] = {
    "system_name": "Stock Lab v2.0",
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
        "opportunity_review_days": 2,
        "opportunity_min_score_gap": 5.0,
        "opportunity_min_expected_return_gap_pct": 2.5,
        "rotation_min_candidate_score": 80.0,
        "rotation_max_hold_pnl_pct": 9.0,
        "rotation_underperform_pct": 3.0,
        "active_trim_hold_days": 2,
        "active_trim_min_score_gap": 4.0,
        "active_trim_min_expected_return_gap_pct": 2.0,
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
        "max_total_candidates": 18,
        "target_markets": ["A", "HK", "US"],
        "technical_trading_mode": "rotation_first",
        "screening": {
            "min_score": 68.0,
            "min_expected_return_pct": 5.0,
            "max_heat_change_pct": 8.5,
            "prefer_pullback_near_entry": True,
            "focus_theme_bonus": 8.0,
            "non_focus_theme_bonus": 2.0,
        },
        "cash_management": {
            "soft_cash_floor_pct": 0.18,
            "ideal_cash_floor_pct": 0.25,
            "allow_rotation_when_better_setup": True,
        },
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
    "news_analysis": {
        "enable_llm": True,
        "max_llm_items_per_run": 3,
        "llm": {
            "endpoint": "https://api.openai.com/v1/chat/completions",
            "model": "gpt-4.1-mini",
            "api_key": "",
        },
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
    }
    news_analysis = dict(config.get("news_analysis") or {})
    llm_cfg = dict(news_analysis.get("llm") or {})
    llm_cfg["endpoint"] = os.getenv("STOCK_LAB_NEWS_LLM_ENDPOINT") or llm_cfg.get("endpoint", "https://api.openai.com/v1/chat/completions")
    llm_cfg["model"] = os.getenv("STOCK_LAB_NEWS_LLM_MODEL") or llm_cfg.get("model", "gpt-4.1-mini")
    llm_cfg["api_key"] = (
        os.getenv("STOCK_LAB_NEWS_LLM_API_KEY")
        or os.getenv("OPENAI_API_KEY")
        or llm_cfg.get("api_key", "")
    )
    news_analysis["llm"] = llm_cfg
    config["news_analysis"] = news_analysis
    return config
