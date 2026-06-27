from __future__ import annotations

from datetime import datetime, time
from typing import Any
from zoneinfo import ZoneInfo

CN_TZ = ZoneInfo("Asia/Shanghai")
MARKET_TIMEZONES = {
    "A": ZoneInfo("Asia/Shanghai"),
    "HK": ZoneInfo("Asia/Hong_Kong"),
    "US": ZoneInfo("America/New_York"),
}
MARKET_LABELS = {
    "A": "A股",
    "HK": "港股",
    "US": "美股",
}
MARKET_PHASE_WINDOWS = {
    "A": {
        "premarket_wait": time(9, 15),
        "premarket_analysis": time(9, 30),
        "opening_trade": time(10, 30),
        "hourly_review_am": time(11, 30),
        "midday_break": time(13, 0),
        "hourly_review_pm1": time(14, 30),
        "closing_review": time(15, 0),
        "post_close_wait": time(16, 0),
    },
    "HK": {
        "premarket_wait": time(9, 15),
        "premarket_analysis": time(9, 30),
        "opening_trade": time(10, 30),
        "hourly_review_am": time(12, 0),
        "midday_break": time(13, 0),
        "hourly_review_pm1": time(15, 30),
        "closing_review": time(16, 0),
        "post_close_wait": time(17, 0),
    },
    "US": {
        "premarket_wait": time(9, 0),
        "premarket_analysis": time(9, 30),
        "opening_trade": time(10, 30),
        "hourly_review_am": time(12, 0),
        "midday_break": time(13, 0),
        "hourly_review_pm1": time(15, 30),
        "closing_review": time(16, 0),
        "post_close_wait": time(17, 0),
    },
}

PHASE_LABELS = {
    "non_trading_day": "非交易日",
    "before_premarket": "盘前等待",
    "premarket_analysis": "盘前研究",
    "opening_trade": "开盘决策",
    "hourly_review_am": "上午盘中复查",
    "midday_break": "午间休整",
    "hourly_review_pm1": "下午盘中复查",
    "closing_review": "尾盘纪律检查",
    "post_close_wait": "收盘等待复盘",
    "after_close_review": "盘后复盘",
}

TRADING_PHASES = {
    "opening_trade",
    "hourly_review_am",
    "hourly_review_pm1",
    "closing_review",
}


def market_timezone(market: str = "A") -> ZoneInfo:
    return MARKET_TIMEZONES.get(str(market or "A").upper(), CN_TZ)


def market_label(market: str = "A") -> str:
    return MARKET_LABELS.get(str(market or "A").upper(), str(market or "A"))


def market_now(market: str = "A") -> datetime:
    return datetime.now(market_timezone(market))


def now_cn() -> datetime:
    return datetime.now(CN_TZ)


def iso_now() -> str:
    return now_cn().replace(microsecond=0).isoformat()


def safe_float(value: Any, default: float = 0.0) -> float:
    try:
        if value is None or value == "":
            return default
        if isinstance(value, str):
            value = value.replace("%", "").replace(",", "").strip()
        return float(value)
    except (TypeError, ValueError):
        return default


def safe_int(value: Any, default: int = 0) -> int:
    try:
        return int(safe_float(value, default))
    except (TypeError, ValueError):
        return default


def round2(value: Any) -> float:
    return round(safe_float(value), 2)


def clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


def pct_change(new: Any, old: Any) -> float:
    old_f = safe_float(old)
    if old_f == 0:
        return 0.0
    return round2((safe_float(new) / old_f - 1) * 100)


def is_trading_day(moment: datetime | None = None, market: str = "A") -> bool:
    current = moment.astimezone(market_timezone(market)) if moment else market_now(market)
    return current.weekday() < 5


def current_phase(moment: datetime | None = None, market: str = "A") -> str:
    current = moment.astimezone(market_timezone(market)) if moment else market_now(market)
    if not is_trading_day(current, market):
        return "non_trading_day"
    t = current.time()
    windows = MARKET_PHASE_WINDOWS.get(str(market or "A").upper(), MARKET_PHASE_WINDOWS["A"])
    if t < windows["premarket_wait"]:
        return "before_premarket"
    if t < windows["premarket_analysis"]:
        return "premarket_analysis"
    if t < windows["opening_trade"]:
        return "opening_trade"
    if t < windows["hourly_review_am"]:
        return "hourly_review_am"
    if t < windows["midday_break"]:
        return "midday_break"
    if t < windows["hourly_review_pm1"]:
        return "hourly_review_pm1"
    if t < windows["closing_review"]:
        return "closing_review"
    if t < windows["post_close_wait"]:
        return "post_close_wait"
    return "after_close_review"


def phase_label(phase: str) -> str:
    return PHASE_LABELS.get(phase, phase)


def is_trading_phase(phase: str) -> bool:
    return phase in TRADING_PHASES


def symbol_digits(symbol: str) -> str:
    return "".join(ch for ch in str(symbol) if ch.isdigit())


def money_text(value: Any, currency: str = "CNY") -> str:
    prefix = {"CNY": "¥", "HKD": "HK$", "USD": "$"}.get(currency, "")
    return f"{prefix}{safe_float(value):,.2f}"


def unique_by_symbol(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen: set[str] = set()
    result: list[dict[str, Any]] = []
    for item in items:
        symbol = str(item.get("symbol") or "")
        key = f"{item.get('market')}:{symbol}"
        if not symbol or key in seen:
            continue
        seen.add(key)
        result.append(item)
    return result
