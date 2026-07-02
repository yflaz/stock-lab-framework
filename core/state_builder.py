from __future__ import annotations

import os
from copy import deepcopy
from typing import Any

from .config import load_config
from .discipline import apply_discipline_actions
from .market_data import collect_market_quotes
from .news_analysis import analyze_mapped_headlines, term_matches_text
from .state_store import load_sectors, load_state, save_json, save_state, SECTOR_PATH
from .strategy import (
    apply_entry_orders,
    apply_rotation_actions,
    build_agent_committee_snapshot,
    build_candidates,
    count_active_trade_slots,
    merge_reviews_into_orders,
)
from .utils import current_phase, iso_now, market_label, money_text, phase_label, round2, safe_float, safe_int


def infer_market(symbol: str) -> str:
    symbol = str(symbol)
    if symbol.endswith(".HK"):
        return "HK"
    if any(ch.isalpha() for ch in symbol) and not symbol.endswith(".HK"):
        return "US"
    return "A"


def account_currency(account: dict[str, Any]) -> str:
    return str(account.get("currency") or {"A": "CNY", "HK": "HKD", "US": "USD"}.get(str(account.get("market")), "CNY"))


def init_accounts(config: dict[str, Any], previous_state: dict[str, Any]) -> dict[str, dict[str, Any]]:
    previous_accounts = {str(acc.get("id")): acc for acc in previous_state.get("accounts") or [] if acc.get("id")}
    if previous_state.get("account") and config.get("active_account_id"):
        previous_accounts.setdefault(str(config.get("active_account_id")), previous_state.get("account") or {})
    previous_positions_by_account = {
        str(pos.get("account_id") or "")
        for pos in previous_state.get("positions") or []
        if pos.get("account_id") and safe_int(pos.get("shares")) > 0
    }
    previous_trades_by_account = {
        str(item.get("account_id") or "")
        for item in previous_state.get("trade_log") or []
        if item.get("account_id")
    }
    accounts_by_id: dict[str, dict[str, Any]] = {}
    for cfg in config.get("accounts") or []:
        account = deepcopy(cfg)
        account_id = str(cfg.get("id"))
        prev = previous_accounts.get(account_id) or {}
        for key in ["cash", "realized_pnl"]:
            if key in prev:
                account[key] = prev[key]
        account.setdefault("initial_cash", cfg.get("initial_cash", 0.0))
        if account_id not in previous_positions_by_account and account_id not in previous_trades_by_account:
            account["cash"] = cfg.get("initial_cash", 0.0)
            account["realized_pnl"] = 0.0
        account.setdefault("cash", cfg.get("cash", cfg.get("initial_cash", 0.0)))
        account.setdefault("realized_pnl", 0.0)
        account.setdefault("currency", account_currency(account))
        accounts_by_id[account_id] = account
    return accounts_by_id


def normalize_positions(previous_state: dict[str, Any], config: dict[str, Any]) -> list[dict[str, Any]]:
    active_account_id = str(config.get("active_account_id"))
    positions: list[dict[str, Any]] = []
    for item in previous_state.get("positions") or []:
        pos = deepcopy(item)
        symbol = str(pos.get("symbol") or "")
        market = str(pos.get("market") or infer_market(symbol))
        account_id = str(pos.get("account_id") or active_account_id)
        for account in config.get("accounts") or []:
            if account.get("market") == market and not pos.get("account_id"):
                account_id = str(account.get("id"))
                break
        pos["symbol"] = symbol
        pos["market"] = market
        pos["account_id"] = account_id
        pos["shares"] = safe_int(pos.get("shares"))
        pos["cost_price"] = round2(pos.get("cost_price"))
        pos["cost_basis"] = round2(pos.get("cost_basis") or safe_float(pos.get("cost_price")) * safe_float(pos.get("shares")))
        pos.setdefault("strategy_label", pos.get("strategy_bucket") or "AI纪律交易")
        pos.setdefault("theme", "其他")
        pos.setdefault("entry_date", pos.get("created_at") or "")
        if pos["shares"] > 0:
            positions.append(pos)
    return positions


def quote_for_position(position: dict[str, Any], market_context: dict[str, Any]) -> dict[str, Any]:
    quotes = (market_context.get("quotes") or {}).get(str(position.get("market"))) or {}
    return quotes.get(str(position.get("symbol"))) or {}


def refresh_positions(positions: list[dict[str, Any]], market_context: dict[str, Any]) -> None:
    for pos in positions:
        quote = quote_for_position(pos, market_context)
        latest = safe_float(quote.get("latest")) or safe_float(pos.get("latest_price") or pos.get("cost_price"))
        prev_close = safe_float(quote.get("prev_close")) or safe_float(pos.get("prev_close") or pos.get("latest_price"))
        shares = safe_int(pos.get("shares"))
        cost_basis = safe_float(pos.get("cost_basis") or safe_float(pos.get("cost_price")) * shares)
        market_value = round2(latest * shares)
        pos["latest_price"] = round2(latest)
        pos["prev_close"] = round2(prev_close)
        pos["change_pct"] = round2(quote.get("change_pct") or 0)
        pos["market_value"] = market_value
        pos["cost_basis"] = round2(cost_basis)
        pos["unrealized_pnl"] = round2(market_value - cost_basis)
        pos["unrealized_pnl_pct"] = round2((market_value / cost_basis - 1) * 100) if cost_basis else 0.0
        pos["today_pnl"] = round2((latest - prev_close) * shares) if prev_close else 0.0
        pos["today_pnl_pct"] = round2((latest / prev_close - 1) * 100) if prev_close else 0.0
        pos["data_source"] = quote.get("data_source") or pos.get("data_source") or "previous_state_fallback"


RULE_CHANGE_SPECS = [
    ("risk.max_position_pct", "单票上限", "pct_ratio"),
    ("risk.max_theme_pct", "主题上限", "pct_ratio"),
    ("risk.min_cash_pct", "最低现金比", "pct_ratio"),
    ("risk.trailing_activation_pct", "移动止盈启动", "pct"),
    ("risk.trailing_drawdown_pct", "移动止盈回撤", "pct"),
    ("risk.time_stop_days", "时间止损天数", "days"),
    ("risk.time_stop_min_pnl_pct", "时间止损盈亏线", "pct"),
    ("risk.opportunity_review_days", "机会成本复核天数", "days"),
    ("risk.opportunity_min_score_gap", "机会成本评分差", "score"),
    ("risk.opportunity_min_expected_return_gap_pct", "机会成本预期差", "pct"),
    ("risk.rotation_min_candidate_score", "调仓最低候选分", "score"),
    ("risk.rotation_max_hold_pnl_pct", "高浮盈不轻易换仓线", "pct"),
    ("risk.rotation_underperform_pct", "持仓落后容忍线", "pct"),
    ("strategy.screening.min_score", "候选最低分", "score"),
    ("strategy.screening.min_expected_return_pct", "候选最低预期空间", "pct"),
    ("strategy.screening.max_heat_change_pct", "过热上限", "pct"),
]


def nested_get(data: dict[str, Any], path: str) -> Any:
    current: Any = data
    for key in path.split("."):
        if not isinstance(current, dict):
            return None
        current = current.get(key)
    return current


def format_rule_value(value: Any, kind: str) -> str:
    if value is None or value == "":
        return "--"
    if kind == "pct_ratio":
        return f"{round2(safe_float(value) * 100)}%"
    if kind == "pct":
        return f"{round2(value)}%"
    if kind == "days":
        return f"{safe_int(value)} 天"
    if kind == "score":
        return f"{round2(value)}"
    return str(value)


def build_rule_change_bundle(config: dict[str, Any], previous_state: dict[str, Any]) -> dict[str, Any]:
    current_rules = {path: nested_get(config, path) for path, _, _ in RULE_CHANGE_SPECS}
    previous_rules = ((previous_state.get("config_snapshot") or {}).get("rules") or {})
    changes: list[dict[str, str]] = []
    for path, label, kind in RULE_CHANGE_SPECS:
        current_value = current_rules.get(path)
        previous_value = previous_rules.get(path)
        if previous_value is None:
            continue
        if format_rule_value(current_value, kind) == format_rule_value(previous_value, kind):
            continue
        changes.append(
            {
                "path": path,
                "label": label,
                "before": format_rule_value(previous_value, kind),
                "after": format_rule_value(current_value, kind),
                "text": f"{label}：{format_rule_value(previous_value, kind)} → {format_rule_value(current_value, kind)}",
            }
        )
    return {"rules": current_rules, "changes": changes[:12]}


def build_previous_position_map(previous_state: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {
        f"{item.get('account_id')}:{item.get('symbol')}": item
        for item in previous_state.get("positions") or []
        if item.get("symbol")
    }


def recompute_accounts(accounts_by_id: dict[str, dict[str, Any]], positions: list[dict[str, Any]], config: dict[str, Any], trade_log: list[dict[str, Any]], generated_at: str) -> None:
    for account in accounts_by_id.values():
        account_id = str(account.get("id"))
        account_positions = [p for p in positions if str(p.get("account_id")) == account_id]
        market_value = round2(sum(safe_float(p.get("market_value")) for p in account_positions))
        cost_basis = round2(sum(safe_float(p.get("cost_basis")) for p in account_positions))
        unrealized = round2(sum(safe_float(p.get("unrealized_pnl")) for p in account_positions))
        cash = round2(account.get("cash"))
        account["market_value"] = market_value
        account["cost_basis"] = cost_basis
        account["unrealized_pnl"] = unrealized
        account["equity"] = round2(cash + market_value)
        account["positions_count"] = len(account_positions)
        account["daily_ops_used"] = count_active_trade_slots(
            [x for x in trade_log if str(x.get("account_id") or account_id) == account_id],
            generated_at[:10],
        )
        account["daily_ops_limit"] = safe_int(config.get("daily_trade_limit"), 4)
        account["status"] = "active_paper_positions" if account_positions else "watch_only"


def build_portfolio_summary(active_account: dict[str, Any], positions: list[dict[str, Any]], orders: list[dict[str, Any]], config: dict[str, Any]) -> dict[str, Any]:
    account_id = str(active_account.get("id"))
    account_positions = [p for p in positions if str(p.get("account_id")) == account_id]
    equity = safe_float(active_account.get("equity") or active_account.get("initial_cash") or 1.0, 1.0)
    cash_pct = safe_float(active_account.get("cash")) / max(equity, 1.0)
    invested_pct = safe_float(active_account.get("market_value")) / max(equity, 1.0)
    largest_pct = 0.0
    if account_positions:
        largest_pct = max(safe_float(p.get("market_value")) for p in account_positions) / max(equity, 1.0)
    return {
        "positions_count": len(account_positions),
        "planned_orders_count": len([o for o in orders if str(o.get("account_id")) == account_id]),
        "cash_pct": round2(cash_pct * 100),
        "invested_pct": round2(invested_pct * 100),
        "largest_position_pct": round2(largest_pct * 100),
        "selection_method": "先筛掉今天不值得看的票，再比较新机会、现持仓和现金缓冲；A股优先使用 AKShare/腾讯行情，港美股使用环境变量中的海外数据源。",
        "turnover_policy": "每天固定主动交易机会；强制纪律与机会成本换仓可先卖后看，主动买入仍受机会额度约束，避免一直抱着弱票不动，也避免没有把握时硬做。",
        "activity_explanation": [
            f"当前账户持仓 {len(account_positions)} 只，计划单 {len([o for o in orders if str(o.get('account_id')) == account_id])} 个。",
            f"现金占比约 {round2(cash_pct * 100)}%，低于规则要求时会自动降低新增买入等级，高于理想水位时才更积极进攻。",
            "新增买入只允许 direct_follow；watch_pullback/watch_confirm 只进观察或挂单候选，不因为有票可看就强行出手。",
            "如果外部 direct_follow 明显强于当前弱持仓，会触发机会成本换仓复核，避免长期低换手占用资金。",
        ],
    }


def build_risk_flags(accounts_by_id: dict[str, dict[str, Any]], positions: list[dict[str, Any]], config: dict[str, Any]) -> dict[str, Any]:
    flags: list[str] = []
    risk = config.get("risk") or {}
    for account in accounts_by_id.values():
        account_id = str(account.get("id"))
        equity = safe_float(account.get("equity") or account.get("initial_cash") or 1, 1)
        cash_pct = safe_float(account.get("cash")) / max(equity, 1)
        if cash_pct < safe_float(risk.get("min_cash_pct"), 0.1):
            flags.append(f"{account.get('label')} 现金低于规则下限，新增买入会被降级。")
        theme_values: dict[str, float] = {}
        for pos in positions:
            if str(pos.get("account_id")) != account_id:
                continue
            pct = safe_float(pos.get("market_value")) / max(equity, 1)
            if pct > safe_float(risk.get("max_position_pct"), 0.25):
                flags.append(f"{account.get('label')} 的 {pos.get('name')} 单票仓位约 {round2(pct * 100)}%，超过集中度上限。")
            theme_values[str(pos.get("theme") or "其他")] = theme_values.get(str(pos.get("theme") or "其他"), 0.0) + safe_float(pos.get("market_value"))
        for theme, value in theme_values.items():
            theme_pct = value / max(equity, 1)
            if theme_pct > safe_float(risk.get("max_theme_pct"), 0.45):
                flags.append(f"{account.get('label')} 的 {theme} 主题暴露约 {round2(theme_pct * 100)}%，主题集中度偏高。")
    return {
        "headline": "纪律正常" if not flags else "存在需要优先处理的风险约束",
        "risk_flags": flags,
    }


def build_today_pnl_summary(positions: list[dict[str, Any]], active_account_id: str) -> dict[str, Any]:
    items = [
        {
            "symbol": p.get("symbol"),
            "name": p.get("name"),
            "market": p.get("market"),
            "shares": p.get("shares"),
            "latest_price": p.get("latest_price"),
            "prev_close": p.get("prev_close"),
            "today_pnl": p.get("today_pnl"),
            "today_pnl_pct": p.get("today_pnl_pct"),
            "unrealized_pnl": p.get("unrealized_pnl"),
            "unrealized_pnl_pct": p.get("unrealized_pnl_pct"),
        }
        for p in positions
        if str(p.get("account_id")) == active_account_id
    ]
    total = round2(sum(safe_float(x.get("today_pnl")) for x in items))
    prev_value = round2(sum(safe_float(x.get("prev_close")) * safe_float(x.get("shares")) for x in items))
    return {
        "total_pnl": total,
        "prev_market_value": prev_value,
        "current_market_value": round2(sum(safe_float(x.get("latest_price")) * safe_float(x.get("shares")) for x in items)),
        "total_pnl_pct": round2(total / prev_value * 100) if prev_value else 0.0,
        "rising_count": sum(1 for item in items if safe_float(item.get("today_pnl")) > 0),
        "falling_count": sum(1 for item in items if safe_float(item.get("today_pnl")) < 0),
        "flat_count": sum(1 for item in items if safe_float(item.get("today_pnl")) == 0),
        "items": sorted(items, key=lambda item: safe_float(item.get("today_pnl")), reverse=True),
    }


def build_exposure_breakdown(positions: list[dict[str, Any]], account_id: str, equity: float) -> dict[str, Any]:
    by_theme: dict[str, float] = {}
    by_market: dict[str, float] = {}
    for pos in positions:
        if str(pos.get("account_id")) != account_id:
            continue
        value = safe_float(pos.get("market_value"))
        theme = str(pos.get("theme") or "其他")
        market = str(pos.get("market") or "A")
        by_theme[theme] = by_theme.get(theme, 0.0) + value
        by_market[market] = by_market.get(market, 0.0) + value
    return {
        "by_theme": [
            {"name": key, "value": round2(value), "pct": round2(value / max(equity, 1) * 100)}
            for key, value in sorted(by_theme.items(), key=lambda item: item[1], reverse=True)
        ],
        "by_market": [
            {"name": key, "value": round2(value), "pct": round2(value / max(equity, 1) * 100)}
            for key, value in sorted(by_market.items(), key=lambda item: item[1], reverse=True)
        ],
    }


THEME_KEYWORDS = {
    "technology": ["technology", "tech", "科技", "ai", "chip", "semiconductor", "软件", "算力", "半导体", "人工智能"],
    "healthcare": ["healthcare", "medical", "biotech", "医药", "创新药", "医疗", "生物"],
    "industrials": ["industrials", "industry", "制造", "设备", "机械", "军工", "基建", "电网"],
    "energy": ["energy", "oil", "gas", "power", "coal", "光伏", "风电", "储能", "电力", "能源", "原油"],
    "finance": ["finance", "bank", "broker", "insurance", "银行", "券商", "保险", "利率", "收益率"],
    "consumer": ["consumer", "retail", "beer", "liquor", "food", "消费", "白酒", "零售", "食品"],
}


def canonical_theme_key(theme: Any) -> str:
    text = str(theme or "").strip().lower()
    return " ".join(text.split())


def theme_terms(theme: Any) -> list[str]:
    raw = str(theme or "").strip()
    if not raw:
        return []
    lowered = canonical_theme_key(raw)
    terms = {raw.lower(), lowered}
    for key, keywords in THEME_KEYWORDS.items():
        if key in lowered or lowered in key or raw.lower() in keywords:
            terms.update(keywords)
    return [term for term in terms if len(term) >= 2]


def build_mapped_headlines(
    headlines: list[dict[str, Any]],
    positions: list[dict[str, Any]],
    orders: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    subjects = []
    for item in positions:
        subjects.append({
            "kind": "position",
            "symbol": str(item.get("symbol") or ""),
            "name": str(item.get("name") or ""),
            "theme": str(item.get("theme") or "其他"),
            "account_id": str(item.get("account_id") or ""),
            "market": str(item.get("market") or "A"),
        })
    for item in orders:
        subjects.append({
            "kind": "watch",
            "symbol": str(item.get("symbol") or ""),
            "name": str(item.get("name") or ""),
            "theme": str(item.get("theme") or "其他"),
            "account_id": str(item.get("account_id") or ""),
            "market": str(item.get("market") or "A"),
        })

    mapped: list[dict[str, Any]] = []
    for headline in headlines or []:
        title = str(headline.get("title") or "").strip()
        if not title:
            continue
        haystack = f"{title} {headline.get('source') or ''}".lower()
        matched_positions: list[dict[str, Any]] = []
        matched_watch: list[dict[str, Any]] = []
        matched_themes: list[str] = []
        seen_keys: set[str] = set()
        for subject in subjects:
            symbol = subject["symbol"]
            name = subject["name"].lower()
            theme = subject["theme"]
            terms = [symbol.lower()] if symbol else []
            if len(name) >= 2:
                terms.append(name)
            terms.extend(theme_terms(theme))
            if any(term_matches_text(term, haystack) for term in terms):
                key = f"{subject['kind']}::{subject['account_id']}::{symbol}"
                if key in seen_keys:
                    continue
                seen_keys.add(key)
                row = {
                    "symbol": symbol,
                    "name": subject["name"],
                    "theme": theme,
                    "account_id": subject["account_id"],
                    "market": subject["market"],
                }
                if subject["kind"] == "position":
                    matched_positions.append(row)
                else:
                    matched_watch.append(row)
                if theme and theme not in matched_themes:
                    matched_themes.append(theme)
        if matched_positions or matched_watch:
            mapped.append({
                "title": title,
                "source": headline.get("source") or "",
                "url": headline.get("url") or "",
                "published_at": headline.get("published_at") or "",
                "matched_themes": matched_themes[:4],
                "related_positions": matched_positions[:4],
                "related_watchlist": matched_watch[:4],
                "related_position_symbols": [x.get("symbol") for x in matched_positions[:4]],
                "related_watch_symbols": [x.get("symbol") for x in matched_watch[:4]],
            })
    return mapped[:8]


def build_home_digest(
    active_account_id: str,
    learning_center: dict[str, Any],
    mapped_headlines: list[dict[str, Any]],
    news_summary: dict[str, Any],
    decision_latest: dict[str, Any],
    discipline_queue: list[dict[str, Any]],
) -> dict[str, Any]:
    position_reviews = [item for item in (learning_center.get("position_reviews") or []) if item.get("changes")]
    account_news = [
        item
        for item in (mapped_headlines or [])
        if any(str(x.get("account_id") or "") == active_account_id for x in (item.get("related_positions") or []) + (item.get("related_watchlist") or []))
    ]
    urgent = [
        item
        for item in (discipline_queue or [])
        if str(item.get("account_id") or "") == active_account_id and item.get("severity") != "pass"
    ]
    summary_items = [
        {"label": "规则改动", "value": len(learning_center.get("rule_changes") or []), "kind": "good" if learning_center.get("rule_changes") else "info", "note": "昨晚复盘后变化"},
        {"label": "持仓参数改动", "value": len(position_reviews), "kind": "good" if position_reviews else "info", "note": "止损/目标/失效条件"},
        {"label": "命中线索", "value": len(account_news), "kind": "warn" if account_news else "info", "note": f"高影响 {safe_int(news_summary.get('high_impact_count'))} 条" if account_news else "新闻映射到持仓/观察股"},
        {"label": "优先动作", "value": len(urgent), "kind": "warn" if urgent else "info", "note": "纪律与换仓先处理"},
    ]
    action_lines = [
        *[str(x.get("text") or "") for x in (learning_center.get("rule_changes") or [])[:3]],
        *[f"{item.get('name')}({item.get('symbol')})：{(item.get('changes') or [{}])[0].get('text')}" for item in position_reviews[:3]],
        *[f"{item.get('name')}({item.get('symbol')})：{item.get('reason')}" for item in urgent[:3]],
    ]
    return {
        "summary_items": summary_items,
        "action_lines": [line for line in action_lines if line][:8],
        "headline_hits": account_news[:5],
        "headline": decision_latest.get("summary") or "",
    }


def build_account_analytics(accounts_by_id: dict[str, dict[str, Any]], positions: list[dict[str, Any]], trade_log: list[dict[str, Any]]) -> dict[str, Any]:
    analytics: dict[str, Any] = {}
    for account_id, account in accounts_by_id.items():
        equity = safe_float(account.get("equity") or account.get("initial_cash") or 1, 1)
        initial = safe_float(account.get("initial_cash") or equity, equity)
        account_trades = [x for x in trade_log if str(x.get("account_id") or account_id) == account_id]
        closed_trades = [x for x in account_trades if str(x.get("type")) in {"sell", "reduce"}]
        wins = [x for x in closed_trades if safe_float(x.get("realized_pnl")) > 0]
        losses = [x for x in closed_trades if safe_float(x.get("realized_pnl")) < 0]
        account_positions = [p for p in positions if str(p.get("account_id")) == account_id]
        analytics[account_id] = {
            "account_id": account_id,
            "label": account.get("label"),
            "currency": account.get("currency"),
            "equity": round2(equity),
            "return_pct": round2((equity / max(initial, 1) - 1) * 100),
            "realized_pnl": round2(account.get("realized_pnl")),
            "unrealized_pnl": round2(account.get("unrealized_pnl")),
            "today_pnl": round2(sum(safe_float(p.get("today_pnl")) for p in account_positions)),
            "trade_count": len(account_trades),
            "closed_trade_count": len(closed_trades),
            "win_rate": round2(len(wins) / len(closed_trades) * 100) if closed_trades else 0.0,
            "avg_win": round2(sum(safe_float(x.get("realized_pnl")) for x in wins) / len(wins)) if wins else 0.0,
            "avg_loss": round2(sum(safe_float(x.get("realized_pnl")) for x in losses) / len(losses)) if losses else 0.0,
            "profit_factor": round2(
                sum(safe_float(x.get("realized_pnl")) for x in wins)
                / max(abs(sum(safe_float(x.get("realized_pnl")) for x in losses)), 0.01)
            ) if closed_trades else 0.0,
            "exposure": build_exposure_breakdown(positions, account_id, equity),
        }
    return analytics


def build_profit_analysis(
    active_account: dict[str, Any],
    positions: list[dict[str, Any]],
    trade_log: list[dict[str, Any]],
    account_analytics: dict[str, Any],
    orders: list[dict[str, Any]] | None = None,
    headlines: list[dict[str, Any]] | None = None,
    previous_positions: dict[str, dict[str, Any]] | None = None,
) -> dict[str, Any]:
    account_id = str(active_account.get("id"))
    currency = account_currency(active_account)
    account_positions = [p for p in positions if str(p.get("account_id")) == account_id]
    account_trades = [x for x in trade_log if str(x.get("account_id") or account_id) == account_id]
    sorted_positions = sorted(account_positions, key=lambda x: safe_float(x.get("unrealized_pnl")), reverse=True)
    daily: dict[str, dict[str, float]] = {}
    for trade in account_trades:
        day = str(trade.get("timestamp") or "")[:10] or "unknown"
        bucket = daily.setdefault(day, {"realized_pnl": 0.0, "turnover": 0.0, "trade_count": 0})
        bucket["realized_pnl"] += safe_float(trade.get("realized_pnl"))
        bucket["turnover"] += safe_float(trade.get("gross_amount"))
        bucket["trade_count"] += 1
    daily_items = [
        {"date": key, "realized_pnl": round2(value["realized_pnl"]), "turnover": round2(value["turnover"]), "trade_count": int(value["trade_count"])}
        for key, value in sorted(daily.items(), reverse=True)
    ]
    by_theme = (account_analytics.get(account_id) or {}).get("exposure", {}).get("by_theme", [])
    challengers = sorted(
        [x for x in (orders or []) if str(x.get("account_id")) == account_id],
        key=lambda item: (
            {"direct_follow": 0, "watch_pullback": 1, "watch_confirm": 2, "observe_only": 3, "avoid_for_now": 4}.get(str(item.get("committee_action")), 9),
            -safe_float(item.get("committee_score") or item.get("score")),
        ),
    )
    top_challenger = challengers[0] if challengers else None
    top_winners = [
        {
            "symbol": p.get("symbol"),
            "name": p.get("name"),
            "pnl": round2(p.get("unrealized_pnl")),
            "pnl_pct": round2(p.get("unrealized_pnl_pct")),
            "reason": "当前浮盈样本，复盘时判断是方向、择时还是仓位贡献。",
        }
        for p in sorted_positions[:5]
        if safe_float(p.get("unrealized_pnl")) > 0
    ]
    top_losers = [
        {
            "symbol": p.get("symbol"),
            "name": p.get("name"),
            "pnl": round2(p.get("unrealized_pnl")),
            "pnl_pct": round2(p.get("unrealized_pnl_pct")),
            "reason": "当前浮亏样本，优先检查是否接近止损、主题走弱或买点过热。",
        }
        for p in sorted(account_positions, key=lambda x: safe_float(x.get("unrealized_pnl")))[:5]
        if safe_float(p.get("unrealized_pnl")) < 0
    ]
    position_reviews = [
        build_position_review(
            position,
            top_challenger,
            headlines,
            (previous_positions or {}).get(f"{position.get('account_id')}:{position.get('symbol')}") if previous_positions else None,
        )
        for position in sorted(account_positions, key=lambda x: (safe_float(x.get("today_pnl_pct")), safe_float(x.get("unrealized_pnl_pct"))))
    ]
    review_questions = build_review_questions_from_reviews(position_reviews, top_losers, top_winners)
    return {
        "account_id": account_id,
        "currency": currency,
        "headline": "当前还没有实盘收益曲线样本，先以模拟持仓、已实现盈亏和主题暴露做归因。" if not account_trades else "收益分析已按成交、持仓和主题暴露拆解。",
        "summary": account_analytics.get(account_id) or {},
        "top_winners": top_winners,
        "top_losers": top_losers,
        "daily_realized": daily_items[:20],
        "theme_attribution": by_theme,
        "position_reviews": position_reviews[:8],
        "review_questions": review_questions,
        "questions": review_questions or [
            "今天赚/亏主要来自哪一个主题，而不是哪一只股票的噪音？",
            "浮盈是否已经达到止盈或移动止盈保护条件？",
            "亏损是否来自追高、数据缺失、还是逻辑被证伪后动作不够快？",
        ],
    }


def build_position_review(
    position: dict[str, Any],
    challenger: dict[str, Any] | None = None,
    headlines: list[dict[str, Any]] | None = None,
    previous_position: dict[str, Any] | None = None,
) -> dict[str, Any]:
    latest = safe_float(position.get("latest_price"))
    stop_loss = safe_float(position.get("stop_loss"))
    target_price = safe_float(position.get("target_price"))
    shares = safe_int(position.get("shares"))
    pnl_pct = safe_float(position.get("unrealized_pnl_pct"))
    today_pnl_pct = safe_float(position.get("today_pnl_pct"))
    market_value = safe_float(position.get("market_value"))
    support_buffer_pct = round2((latest / stop_loss - 1) * 100) if latest > 0 and stop_loss > 0 else 0.0
    target_room_pct = round2((target_price / latest - 1) * 100) if latest > 0 and target_price > 0 else 0.0
    realized_half_now = round2(max(safe_float(position.get("unrealized_pnl")), 0.0) * 0.5)
    downside_to_stop = round2(max(latest - stop_loss, 0.0) * shares) if latest > 0 and stop_loss > 0 else 0.0
    action_bias = "继续持有"
    summary = "当前逻辑尚未明显破坏，继续观察。"
    what_if = "今天没有明显的必须动作。"
    lessons: list[str] = []

    if pnl_pct >= 6 and today_pnl_pct < 0:
        action_bias = "应考虑减仓"
        summary = "已有较明显浮盈，但今天边际转弱，适合先锁一部分。"
        what_if = f"如果今天先减半，按现价大约能先锁定 {realized_half_now} 的浮盈。"
        lessons.extend([
            f"浮盈 {round2(pnl_pct)}%，已经不是只能死拿的阶段。",
            f"今日日内表现 {round2(today_pnl_pct)}%，说明强度没有继续单边增强。",
        ])
    elif stop_loss > 0 and support_buffer_pct <= 3.0:
        action_bias = "接近防守位"
        summary = "价格离止损不远，应该把防守提到第一优先级。"
        what_if = f"若继续回落到止损，按当前仓位大约还会多回撤 {downside_to_stop}。"
        lessons.extend([
            f"距离止损只剩约 {round2(support_buffer_pct)}% 缓冲。",
            "这类位置继续死扛，性价比通常不高。",
        ])
    elif target_room_pct <= 3.0 and pnl_pct > 0:
        action_bias = "逼近止盈位"
        summary = "离目标位不远，更适合盯兑现而不是只幻想继续上冲。"
        what_if = f"若靠近目标位分批落袋，可以优先把已经到手的 {round2(safe_float(position.get('unrealized_pnl')))} 浮盈转成已实现。"
        lessons.extend([
            f"距离目标位只剩约 {round2(target_room_pct)}%。",
            f"当前仓位市值约 {round2(market_value)}，适合提前规划减仓节奏。",
        ])
    else:
        lessons.extend([
            f"当前浮盈亏 {round2(pnl_pct)}%，今日涨跌 {round2(today_pnl_pct)}%。",
            f"距离止损缓冲约 {round2(support_buffer_pct)}%，距离目标位空间约 {round2(target_room_pct)}%。",
        ])

    if challenger:
        candidate_expected = safe_float(challenger.get("expected_return_pct"))
        candidate_score = safe_float(challenger.get("committee_score") or challenger.get("score"))
        current_score = safe_float(position.get("score"))
        gap_score = round2(candidate_score - current_score)
        gap_expected = round2(candidate_expected - target_room_pct)
        if gap_score >= 4 or gap_expected >= 2:
            lessons.append(
                f"外部候选 {challenger.get('name')}({challenger.get('symbol')}) 更强：评分高 {gap_score} 分，预期空间多 {gap_expected}%。"
            )
            if action_bias == "继续持有":
                action_bias = "可比较调仓"
                what_if = f"如果把一部分仓位换去 {challenger.get('name')}，当前账面上可把预期空间从 {round2(target_room_pct)}% 提到 {round2(candidate_expected)}%。"

    related_news = [
        item
        for item in (headlines or [])
        if str(position.get("symbol") or "") in (item.get("related_position_symbols") or [])
        or any(str(x.get("symbol") or "") == str(position.get("symbol") or "") for x in (item.get("related_positions") or []))
    ]
    if related_news:
        dominant = ((related_news[0].get("news_analysis") or {}).get("final") or {})
        sentiment = str(dominant.get("sentiment") or "neutral")
        impact = safe_int(dominant.get("impact_score"), 0)
        if impact >= 4:
            lessons.append(f"现实中有高影响新闻命中该股/主题，当前偏{sentiment}，别只盯 K 线。")
        else:
            lessons.append("现实中有新闻命中该股/主题，但目前更像辅助线索，先和量价一起验证。")
        if dominant.get("action_hint"):
            lessons.append(str(dominant.get("action_hint")))

    changes: list[dict[str, Any]] = []
    changed_fields = {"stop_loss": False, "target_price": False, "invalidation": False}
    if previous_position:
        currency = account_currency(position)
        previous_stop = round2(previous_position.get("stop_loss"))
        if previous_stop != round2(stop_loss):
            changed_fields["stop_loss"] = True
            changes.append({
                "field": "stop_loss",
                "label": "止损",
                "before": money_text(previous_stop, currency),
                "after": money_text(stop_loss, currency),
                "text": f"止损：{money_text(previous_stop, currency)} → {money_text(stop_loss, currency)}",
            })
        previous_target = round2(previous_position.get("target_price"))
        if previous_target != round2(target_price):
            changed_fields["target_price"] = True
            changes.append({
                "field": "target_price",
                "label": "目标",
                "before": money_text(previous_target, currency),
                "after": money_text(target_price, currency),
                "text": f"目标：{money_text(previous_target, currency)} → {money_text(target_price, currency)}",
            })
        previous_invalidation = str(previous_position.get("invalidation") or "").strip()
        current_invalidation = str(position.get("invalidation") or "").strip()
        if previous_invalidation and current_invalidation and previous_invalidation != current_invalidation:
            changed_fields["invalidation"] = True
            changes.append({
                "field": "invalidation",
                "label": "失效条件",
                "before": previous_invalidation,
                "after": current_invalidation,
                "text": f"失效条件已更新：{previous_invalidation} → {current_invalidation}",
            })

    return {
        "symbol": position.get("symbol"),
        "name": position.get("name"),
        "action_bias": action_bias,
        "summary": summary,
        "what_if": what_if,
        "lessons": lessons[:5],
        "support_buffer_pct": round2(support_buffer_pct),
        "target_room_pct": round2(target_room_pct),
        "today_pnl_pct": round2(today_pnl_pct),
        "unrealized_pnl_pct": round2(pnl_pct),
        "news_hits": [
            {
                "title": item.get("title"),
                "source": item.get("source"),
                "sentiment": ((item.get("news_analysis") or {}).get("final") or {}).get("sentiment"),
                "impact_score": ((item.get("news_analysis") or {}).get("final") or {}).get("impact_score"),
            }
            for item in related_news[:3]
        ],
        "changes": changes,
        "changed_fields": changed_fields,
    }


def build_review_questions_from_reviews(position_reviews: list[dict[str, Any]], top_losers: list[dict[str, Any]], top_winners: list[dict[str, Any]]) -> list[str]:
    questions: list[str] = []
    for item in position_reviews[:4]:
        questions.append(f"{item.get('name')}：{item.get('what_if')}")
    for item in top_losers[:2]:
        questions.append(f"{item.get('name')}：浮亏 {item.get('pnl_pct')}%，复核这是不是买点错误、减仓太慢，还是逻辑本来就不该上。")
    for item in top_winners[:2]:
        questions.append(f"{item.get('name')}：浮盈 {item.get('pnl_pct')}%，判断利润主要来自方向判断、持仓耐心，还是卖点还可以更主动。")
    return questions[:8]


def build_profit_analysis_by_account(
    accounts_by_id: dict[str, dict[str, Any]],
    positions: list[dict[str, Any]],
    trade_log: list[dict[str, Any]],
    account_analytics: dict[str, Any],
    orders: list[dict[str, Any]] | None = None,
    headlines: list[dict[str, Any]] | None = None,
    previous_positions: dict[str, dict[str, Any]] | None = None,
) -> dict[str, Any]:
    return {
        account_id: build_profit_analysis(account, positions, trade_log, account_analytics, orders, headlines, previous_positions)
        for account_id, account in accounts_by_id.items()
    }


def build_thought_process(
    decision_latest: dict[str, Any],
    committee: dict[str, Any],
    discipline_queue: list[dict[str, Any]],
    risk_flags: dict[str, Any],
    data_health: list[dict[str, Any]],
    rule_changes: list[dict[str, Any]] | None = None,
    position_change_lines: list[str] | None = None,
) -> dict[str, Any]:
    direct = [x for x in committee.get("candidate_reviews") or [] if x.get("committee_action") == "direct_follow"]
    waiting = [
        x
        for x in committee.get("candidate_reviews") or []
        if x.get("committee_action") in {"watch_pullback", "watch_confirm"}
    ]
    avoid = [x for x in committee.get("candidate_reviews") or [] if x.get("committee_action") == "avoid_for_now"]

    stock_focus: list[str] = []
    for item in direct[:3]:
        stock_focus.append(
            f"{item.get('name')}({item.get('symbol')}) 可直接跟随：评分 {round2(item.get('committee_score'))}，"
            f"预期空间 {round2(item.get('candidate_expected_return_pct') or item.get('expected_return_pct') or 0)}%，"
            f"执行意见：{((item.get('risk_manager') or {}).get('summary')) or item.get('committee_action')}"
        )
    for item in waiting[:3]:
        stock_focus.append(
            f"{item.get('name')}({item.get('symbol')}) 暂不追：{((item.get('risk_manager') or {}).get('summary')) or item.get('committee_action')}"
        )
    for item in avoid[:2]:
        stock_focus.append(
            f"{item.get('name')}({item.get('symbol')}) 先回避：{((item.get('risk_manager') or {}).get('summary')) or item.get('committee_action')}"
        )
    for item in discipline_queue[:3]:
        stock_focus.append(
            f"持仓 {item.get('name')}({item.get('symbol')}) 当前处理：{item.get('reason')}"
        )

    stages = [
        {
            "name": "纪律门",
            "status": f"{len([x for x in discipline_queue if x.get('mandatory')])} 个强制检查",
            "summary": "这里只保留会影响动作的纪律变化，不再展示后台型可信度说明。",
            "details": [
                *((position_change_lines or [])[:5]),
                *[x.get("reason") for x in discipline_queue if x.get("severity") != "pass"][:5],
            ][:8],
        },
        {
            "name": "组合风险",
            "status": f"{len(rule_changes or [])} 项规则调整" if rule_changes else risk_flags.get("headline"),
            "summary": "如果昨晚复盘改了规则，这里只标真实变动项。",
            "details": ([x.get("text") for x in (rule_changes or [])] or (risk_flags.get("risk_flags") or []))[:8],
            "changes": rule_changes or [],
        },
        {
            "name": "候选审议",
            "status": f"直接 {len(direct)} / 等待 {len(waiting)} / 回避 {len(avoid)}",
            "summary": "这里只展示具体股票的进攻、等待和回避理由，不再只给流程话术。",
            "details": stock_focus[:8] or (committee.get("summary") or []),
        },
        {
            "name": "最终动作",
            "status": decision_latest.get("phase_label"),
            "summary": decision_latest.get("summary"),
            "details": (decision_latest.get("planned_focus") or []) + (decision_latest.get("why_not_buy") or []),
        },
    ]
    top_reviews = []
    for item in (committee.get("candidate_reviews") or [])[:8]:
        top_reviews.append(
            {
                "symbol": item.get("symbol"),
                "name": item.get("name"),
                "account_id": item.get("account_id"),
                "market": item.get("market"),
                "action": item.get("committee_action"),
                "score": item.get("committee_score"),
                "conviction": item.get("conviction"),
                "stock_analysis": {
                    "summary": ((item.get("risk_manager") or {}).get("summary")) or item.get("committee_action"),
                    "debate": item.get("debate") or [],
                },
                "agents": [
                    item.get("macro_agent"),
                    item.get("sector_agent"),
                    item.get("technical_agent"),
                    item.get("fundamental_agent"),
                    item.get("risk_manager"),
                    item.get("portfolio_manager"),
                    item.get("discipline_gate"),
                ],
                "debate": item.get("debate") or [],
            }
        )
    return {
        "headline": decision_latest.get("summary") or "等待下一轮有效决策。",
        "stages": stages,
        "stock_focus": stock_focus[:10],
        "top_reviews": top_reviews,
    }


def build_learning_center(
    decision_log: list[dict[str, Any]],
    profit_analysis: dict[str, Any],
    risk_flags: dict[str, Any],
    thought_process: dict[str, Any],
) -> dict[str, Any]:
    return {
        "stable_rules": [
            "纪律动作先于观点：触发止损、止盈、移动止盈时不靠主观解释拖延。",
            "主动买入低频：机会按批次计数，不能为了让页面热闹而交易。",
            "强票过热先等回踩：好逻辑如果位置坏了，也会变成坏交易。",
            "数据源失败要显式展示：不知道就是不知道，不用模板文字补空白。",
            "复盘拆成方向、择时、个股、仓位、卖点，避免只看总盈亏。",
        ],
        "today_review_questions": profit_analysis.get("review_questions") or profit_analysis.get("questions") or [],
        "position_reviews": profit_analysis.get("position_reviews") or [],
        "risk_lessons": risk_flags.get("risk_flags") or [],
        "rule_changes": ((thought_process.get("stages") or [{}, {}])[1].get("changes") if len(thought_process.get("stages") or []) > 1 else []) or [],
        "recent_decisions": decision_log[:10],
        "process_lessons": [],
    }


def build_candidate_buckets(orders: list[dict[str, Any]]) -> list[dict[str, Any]]:
    label_map = {
        "direct_follow": ("执行池", "direct_follow"),
        "watch_pullback": ("等回踩", "watch_pullback"),
        "watch_confirm": ("等确认", "watch_confirm"),
        "observe_only": ("仅观察", "observe_only"),
        "avoid_for_now": ("回避", "avoid_for_now"),
    }
    rows: list[dict[str, Any]] = []
    for order in orders:
        label, code = label_map.get(str(order.get("committee_action")), ("观察", "observe_only"))
        row = deepcopy(order)
        row["bucket"] = label
        row["bucket_code"] = code
        row["note"] = order.get("committee_summary") or ""
        rows.append(row)
    return rows


def build_position_monitor(discipline_queue: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        {
            "symbol": item.get("symbol"),
            "name": item.get("name"),
            "account_id": item.get("account_id"),
            "market": item.get("market"),
            "status": item.get("action"),
            "severity": item.get("severity"),
            "reason": item.get("reason"),
            "bullets": item.get("checks") or [],
            "discipline_action": item.get("action_code"),
            "mandatory": item.get("mandatory"),
            "executed": item.get("executed", False),
        }
        for item in discipline_queue
    ]


def build_decision_snapshot(
    generated_at: str,
    phase: str,
    positions: list[dict[str, Any]],
    orders: list[dict[str, Any]],
    discipline_queue: list[dict[str, Any]],
    fills: list[dict[str, Any]],
    data_health: list[dict[str, Any]],
    account: dict[str, Any],
) -> dict[str, Any]:
    executed_risk = [x for x in discipline_queue if x.get("executed")]
    hold_items = [x for x in discipline_queue if x.get("action_code") == "hold"][:4]
    wait_orders = [o for o in orders if o.get("committee_action") in {"watch_pullback", "watch_confirm"}][:4]
    direct_orders = [o for o in orders if o.get("committee_action") == "direct_follow"][:3]
    if executed_risk:
        summary = "本轮先执行纪律/换仓动作，再考虑新增交易。"
    elif fills:
        summary = "本轮有主动模拟买入，已占用一次交易机会。"
    elif direct_orders:
        summary = "存在可直接跟随候选，但需要满足价格/现金/机会约束。"
    elif wait_orders:
        summary = "本轮主要是等待回踩或确认，没有强行买入。"
    else:
        summary = "本轮没有足够质量或赔率显著占优的新增交易，保持观察与等待。"
    return {
        "timestamp": generated_at,
        "date": generated_at[:10],
        "phase": phase,
        "phase_label": phase_label(phase),
        "summary": summary,
        "checks": [
            f"当前阶段：{phase_label(phase)}。",
            f"账户：{account.get('label')}，主动交易机会 {account.get('daily_ops_used', 0)}/{account.get('daily_ops_limit', 4)}。",
        ],
        "why_sell": [x.get("reason") for x in executed_risk],
        "why_buy": [x.get("reason") for x in fills],
        "why_hold": [f"{x.get('name')}：{x.get('reason')}" for x in hold_items],
        "why_not_buy": [
            f"{x.get('name')}({x.get('symbol')})：评分 {round2(x.get('committee_score') or 0)}，"
            f"预期空间 {round2(x.get('expected_return_pct') or 0)}%，{x.get('committee_summary') or x.get('committee_action')}"
            for x in wait_orders
        ],
        "planned_focus": [
            "先看强制纪律与机会成本换仓，再看 direct_follow 是否仍在计划价附近。",
            "如果现金低于下限，优先复核是否需要止盈/降仓，而不是继续加仓；现金充裕也不代表必须开仓。",
            "若手里票弱、外面票强，不默认死扛，优先比较机会成本；即使还没到全仓换票，也允许先减一点弱仓腾挪。",
        ],
    }


def append_decision_log(previous_state: dict[str, Any], latest: dict[str, Any]) -> list[dict[str, Any]]:
    log = list(previous_state.get("decision_log") or [])
    key = f"{latest.get('date')}::{latest.get('phase')}"
    log = [x for x in log if f"{x.get('date')}::{x.get('phase')}" != key]
    log.insert(0, latest)
    return log[:40]


def build_watch_pool_summary(orders: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "execution_count": len([x for x in orders if x.get("committee_action") == "direct_follow"]),
        "watch_count": len([x for x in orders if x.get("committee_action") in {"watch_pullback", "watch_confirm"}]),
        "cooldown_count": len([x for x in orders if x.get("committee_action") in {"observe_only", "avoid_for_now"}]),
        "max_watch_count": 30,
        "rotation_policy": "执行池只放 direct_follow；等回踩、等确认、仅观察和回避分层展示。先筛、再比、再动，没优势就不交易。",
    }


def ensure_sector_summary(config: dict[str, Any]) -> None:
    if SECTOR_PATH.exists():
        return
    sectors = [
        {"name": theme, "long_swing_score": 75 + idx * 2, "tactical_score": 70 + idx, "notes": "初始主题池，等待真实板块数据刷新。"}
        for idx, theme in enumerate((config.get("strategy") or {}).get("focus_themes") or [])
    ]
    save_json(SECTOR_PATH, sectors)


def resolve_session_market(config: dict[str, Any]) -> str:
    requested = str(os.getenv("STOCK_LAB_SESSION_MARKET") or "").upper()
    if requested in {"A", "HK", "US"}:
        return requested
    active_account_id = str(config.get("active_account_id") or "")
    for account in config.get("accounts") or []:
        if str(account.get("id")) == active_account_id:
            market = str(account.get("market") or "A").upper()
            if market in {"A", "HK", "US"}:
                return market
    return "A"


def build_state(config: dict[str, Any] | None = None) -> dict[str, Any]:
    config = config or load_config()
    ensure_sector_summary(config)
    previous_state = load_state()
    previous_positions = build_previous_position_map(previous_state)
    generated_at = iso_now()
    session_market = resolve_session_market(config)
    phase = current_phase(market=session_market)
    active_markets = {session_market}
    accounts_by_id = init_accounts(config, previous_state)
    positions = normalize_positions(previous_state, config)
    trade_log = list(previous_state.get("trade_log") or [])

    market_context = collect_market_quotes(config, previous_state)
    refresh_positions(positions, market_context)
    recompute_accounts(accounts_by_id, positions, config, trade_log, generated_at)

    discipline_queue = apply_discipline_actions(positions, accounts_by_id, trade_log, generated_at, config, active_markets=active_markets)
    recompute_accounts(accounts_by_id, positions, config, trade_log, generated_at)

    candidates = build_candidates(config, market_context)
    held_keys = {f"{p.get('account_id')}:{p.get('symbol')}" for p in positions}
    new_candidates = [c for c in candidates if f"{c.get('account_id')}:{c.get('symbol')}" not in held_keys]
    committee = build_agent_committee_snapshot(new_candidates, accounts_by_id, config)
    orders = merge_reviews_into_orders(new_candidates, committee)
    rotation_queue = apply_rotation_actions(positions, orders, accounts_by_id, trade_log, generated_at, config, active_markets=active_markets)
    if rotation_queue:
        discipline_queue.extend(rotation_queue)
        recompute_accounts(accounts_by_id, positions, config, trade_log, generated_at)
    fills = apply_entry_orders(positions, orders, accounts_by_id, trade_log, generated_at, phase, config, active_markets=active_markets)
    if fills:
        held_keys = {f"{p.get('account_id')}:{p.get('symbol')}" for p in positions}
        orders = [o for o in orders if f"{o.get('account_id')}:{o.get('symbol')}" not in held_keys]
    refresh_positions(positions, market_context)
    recompute_accounts(accounts_by_id, positions, config, trade_log, generated_at)

    active_account_id = str(config.get("active_account_id"))
    active_account = accounts_by_id.get(active_account_id) or next(iter(accounts_by_id.values()))
    rule_change_bundle = build_rule_change_bundle(config, previous_state)
    mapped_headlines = build_mapped_headlines(market_context.get("headlines") or [], positions, orders)
    news_pipeline = analyze_mapped_headlines(mapped_headlines, config)
    mapped_headlines = news_pipeline.get("items") or mapped_headlines
    portfolio_summary = build_portfolio_summary(active_account, positions, orders, config)
    risk_flags = build_risk_flags(accounts_by_id, positions, config)
    account_analytics = build_account_analytics(accounts_by_id, positions, trade_log)
    profit_analysis_by_account = build_profit_analysis_by_account(
        accounts_by_id,
        positions,
        trade_log,
        account_analytics,
        orders,
        mapped_headlines,
        previous_positions,
    )
    profit_analysis = profit_analysis_by_account.get(str(active_account.get("id"))) or {}
    position_change_lines = [
        f"{item.get('name')}({item.get('symbol')})：{change.get('text')}"
        for item in (profit_analysis.get("position_reviews") or [])
        for change in (item.get("changes") or [])[:2]
    ]
    decision_latest = build_decision_snapshot(
        generated_at,
        phase,
        positions,
        orders,
        discipline_queue,
        fills,
        market_context.get("data_health") or [],
        active_account,
    )
    decision_log = append_decision_log(previous_state, decision_latest)
    thought_process = build_thought_process(
        decision_latest,
        committee,
        discipline_queue,
        risk_flags,
        market_context.get("data_health") or [],
        rule_change_bundle.get("changes") or [],
        position_change_lines,
    )
    learning_center = build_learning_center(decision_log, profit_analysis, risk_flags, thought_process)
    home_digest = build_home_digest(active_account_id, learning_center, mapped_headlines, news_pipeline.get("summary") or {}, decision_latest, discipline_queue)

    state = {
        "meta": {
            "generated_at": generated_at,
            "system_name": config.get("system_name"),
            "mode": config.get("execution_mode"),
            "session_market": session_market,
            "session_market_label": market_label(session_market),
            "session_phase": phase,
            "session_phase_label": phase_label(phase),
            "data_source": "A股腾讯/AKShare + 海外轻量行情 + 公共 RSS 新闻",
            "schema_version": "stock_lab_new.v1",
            "discipline_first": True,
            "template_text_policy": "前端只渲染状态中真实存在的思考与决策字段，不展示残留模板文字。",
        },
        "config_snapshot": {"rules": rule_change_bundle.get("rules") or {}},
        "active_account_id": active_account_id,
        "accounts": list(accounts_by_id.values()),
        "account": active_account,
        "permissions": {
            "mode": "paper_only",
            "real_broker_adapter": "not_enabled",
            "note": "当前包只做模拟交易与可执行建议；接券商实盘前必须单独实现 broker_adapter 并加二次确认/熔断。",
        },
        "trading_rules": {
            "daily_trade_limit": safe_int(config.get("daily_trade_limit"), 4),
            "risk_actions_count_against_daily_limit": False,
            "active_entry_counting": "同一批主动买入可包含多只股票，但只算一次机会。",
        },
        "market_context": {
            "quotes": market_context.get("quotes") or {},
            "headlines": market_context.get("headlines") or [],
            "mapped_headlines": mapped_headlines,
            "news_summary": news_pipeline.get("summary") or {},
            "news_processing": news_pipeline.get("processing") or {},
            "macro": market_context.get("macro") or [],
            "data_health": market_context.get("data_health") or [],
        },
        "external_context": {
            "headlines": market_context.get("headlines") or [],
            "macro": market_context.get("macro") or [],
        },
        "portfolio_summary": portfolio_summary,
        "portfolio_risk_flags": risk_flags,
        "account_analytics": account_analytics,
        "profit_analysis": profit_analysis,
        "profit_analysis_by_account": profit_analysis_by_account,
        "thought_process": thought_process,
        "learning_center": learning_center,
        "home_digest": home_digest,
        "discipline_summary": {
            "mandatory_count": len([x for x in discipline_queue if x.get("mandatory")]),
            "executed_count": len([x for x in discipline_queue if x.get("executed")]),
            "queue": discipline_queue,
        },
        "positions": positions,
        "orders": orders,
        "trade_log": trade_log,
        "decision_latest": decision_latest,
        "decision_log": decision_log,
        "watchlists": config.get("watchlists") or {},
        "watch_pool_summary": build_watch_pool_summary(orders),
        "candidate_reviews": committee.get("candidate_reviews") or [],
        "candidate_buckets": build_candidate_buckets(orders),
        "agent_committee": committee,
        "position_monitor": build_position_monitor(discipline_queue),
        "today_pnl_summary": build_today_pnl_summary(positions, active_account_id),
        "sectors": load_sectors(),
    }
    return state


def save_current_state(config: dict[str, Any] | None = None) -> dict[str, Any]:
    state = build_state(config)
    save_state(state)
    return state


def initial_state(config: dict[str, Any] | None = None) -> dict[str, Any]:
    config = config or load_config()
    accounts_by_id = init_accounts(config, {})
    generated_at = iso_now()
    session_market = resolve_session_market(config)
    active_account = accounts_by_id[str(config.get("active_account_id"))]
    return {
        "meta": {
            "generated_at": generated_at,
            "system_name": config.get("system_name"),
            "mode": config.get("execution_mode"),
            "session_market": session_market,
            "session_market_label": market_label(session_market),
            "session_phase": current_phase(market=session_market),
            "session_phase_label": phase_label(current_phase(market=session_market)),
            "schema_version": "stock_lab_new.v1",
        },
        "config_snapshot": {"rules": build_rule_change_bundle(config, {}).get("rules") or {}},
        "active_account_id": config.get("active_account_id"),
        "accounts": list(accounts_by_id.values()),
        "account": active_account,
        "positions": [],
        "orders": [],
        "trade_log": [],
        "decision_log": [],
        "account_analytics": {},
        "profit_analysis": {},
        "profit_analysis_by_account": {},
        "thought_process": {"headline": "", "stages": [], "top_reviews": []},
        "learning_center": {"stable_rules": [], "today_review_questions": [], "risk_lessons": [], "recent_decisions": [], "process_lessons": []},
        "home_digest": {"summary_items": [], "action_lines": [], "headline_hits": [], "headline": ""},
        "market_context": {"quotes": {}, "headlines": [], "mapped_headlines": [], "news_summary": {}, "news_processing": {"mode": "rule_only", "llm_enabled": False, "llm_used_count": 0, "cache_hit_count": 0, "errors": []}, "macro": [], "data_health": []},
        "decision_latest": {
            "timestamp": generated_at,
            "summary": "",
            "checks": [],
            "why_sell": [],
            "why_buy": [],
            "why_hold": [],
            "why_not_buy": [],
            "planned_focus": [],
        },
    }
