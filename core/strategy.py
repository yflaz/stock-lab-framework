from __future__ import annotations

from typing import Any

from .discipline import calc_buy_fees
from .utils import clamp, is_trading_phase, money_text, pct_change, round2, safe_float, safe_int


def grade_from_score(score: float) -> str:
    if score >= 86:
        return "S"
    if score >= 78:
        return "A"
    if score >= 68:
        return "B"
    return "C"


def planned_position_pct(confidence: str, config: dict[str, Any]) -> float:
    sizing = ((config.get("strategy") or {}).get("position_sizing") or {})
    return round2(sizing.get(confidence, 0.0))


def account_for_market(config: dict[str, Any], market: str) -> dict[str, Any]:
    accounts = config.get("accounts") or []
    for account in accounts:
        if account.get("market") == market:
            return account
    return accounts[0] if accounts else {}


def infer_setup(change_pct: float, market: str) -> str:
    if change_pct >= 5.5:
        return "overheated_pullback"
    if change_pct >= 2.0:
        return "breakout_follow"
    if change_pct >= -1.5:
        return "trend_hold"
    if change_pct >= -4.0:
        return "weak_repair"
    return "risk_avoid"


def build_candidate(item: dict[str, Any], quote: dict[str, Any], market: str, config: dict[str, Any]) -> dict[str, Any]:
    latest = safe_float(quote.get("latest"))
    prev = safe_float(quote.get("prev_close"))
    change_pct = safe_float(quote.get("change_pct")) if quote else pct_change(latest, prev)
    theme = str(item.get("theme") or "其他")
    focus_themes = set((config.get("strategy") or {}).get("focus_themes") or [])
    theme_bonus = 8 if theme in focus_themes or any(x in theme for x in focus_themes) else 2
    data_quality = 14 if latest > 0 else -18
    momentum = 0
    if -1.5 <= change_pct <= 3.8:
        momentum = 12
    elif 3.8 < change_pct <= 6.5:
        momentum = 5
    elif change_pct > 6.5:
        momentum = -8
    elif -4.0 <= change_pct < -1.5:
        momentum = -3
    else:
        momentum = -12
    market_bias = {"A": 7, "HK": 4, "US": 5}.get(market, 2)
    score = clamp(58 + theme_bonus + data_quality + momentum + market_bias, 25, 96)
    confidence = grade_from_score(score)
    setup_type = infer_setup(change_pct, market)

    if latest > 0:
        if setup_type == "overheated_pullback":
            entry_zone = [round2(latest * 0.955), round2(latest * 0.985)]
            stop_loss = round2(latest * 0.91)
            target_price = round2(latest * 1.12)
        elif setup_type == "weak_repair":
            entry_zone = [round2(latest * 0.985), round2(latest * 1.005)]
            stop_loss = round2(latest * 0.94)
            target_price = round2(latest * 1.08)
        else:
            entry_zone = [round2(latest * 0.99), round2(latest * 1.012)]
            stop_loss = round2(latest * 0.93)
            target_price = round2(latest * (1.16 if confidence in {"S", "A"} else 1.1))
    else:
        entry_zone = [0.0, 0.0]
        stop_loss = 0.0
        target_price = 0.0

    expected_return_pct = round2((target_price / latest - 1) * 100) if latest else 0.0
    reasons = []
    risks = []
    currency = {"A": "CNY", "HK": "HKD", "US": "USD"}.get(market, "CNY")
    if theme != "其他":
        reasons.append(f"主题归属：{theme}，与当前重点观察方向有交集。")
    if latest > 0:
        reasons.append(f"最新价 {money_text(latest, currency)}，当日涨跌幅 {round2(change_pct)}%。")
        reasons.append(f"计划区间 {entry_zone[0]} - {entry_zone[1]}，第一目标 {target_price}，止损 {stop_loss}。")
    else:
        risks.append("当前没有可用实时价，不能自动执行。")
    if change_pct > 6.5:
        risks.append("日内涨幅偏高，容易把好逻辑做成追高交易。")
    if change_pct < -4:
        risks.append("日内走弱明显，需要确认是否有利空或板块退潮。")
    if expected_return_pct < 6 and latest > 0:
        risks.append("第一目标空间偏薄，赔率不够宽。")

    return {
        "symbol": str(item.get("symbol") or quote.get("symbol") or ""),
        "name": item.get("name") or quote.get("name"),
        "market": market,
        "account_id": account_for_market(config, market).get("id"),
        "theme": theme,
        "latest_price": round2(latest),
        "prev_close": round2(prev),
        "change_pct": round2(change_pct),
        "score": round2(score),
        "confidence": confidence,
        "setup_type": setup_type,
        "setup_label": {
            "overheated_pullback": "强势回踩",
            "breakout_follow": "突破跟随",
            "trend_hold": "趋势持有",
            "weak_repair": "弱转修复",
            "risk_avoid": "风险回避",
        }.get(setup_type, setup_type),
        "target_position_pct": planned_position_pct(confidence, config),
        "entry_zone": entry_zone,
        "stop_loss": stop_loss,
        "target_price": target_price,
        "expected_return_pct": expected_return_pct,
        "reason": reasons,
        "risks": risks,
        "data_source": quote.get("data_source") if quote else "none",
        "status": "candidate",
    }


def build_candidates(config: dict[str, Any], market_context: dict[str, Any]) -> list[dict[str, Any]]:
    watchlists = config.get("watchlists") or {}
    quotes_by_market = market_context.get("quotes") or {}
    target_markets = (config.get("strategy") or {}).get("target_markets") or list(watchlists)
    result: list[dict[str, Any]] = []
    for market in target_markets:
        quotes = quotes_by_market.get(market) or {}
        for item in watchlists.get(market) or []:
            symbol = str(item.get("symbol") or "")
            quote = quotes.get(symbol) or {"symbol": symbol, "name": item.get("name"), "market": market}
            result.append(build_candidate(item, quote, market, config))
    result.sort(key=lambda x: (x.get("market") != "A", -safe_float(x.get("score")), -safe_float(x.get("expected_return_pct"))))
    max_candidates = safe_int((config.get("strategy") or {}).get("max_candidates_per_market"), 12)
    by_market: dict[str, list[dict[str, Any]]] = {}
    for candidate in result:
        by_market.setdefault(str(candidate.get("market")), []).append(candidate)
    trimmed: list[dict[str, Any]] = []
    for items in by_market.values():
        trimmed.extend(items[:max_candidates])
    return trimmed


def action_from_candidate(candidate: dict[str, Any], account: dict[str, Any], config: dict[str, Any]) -> tuple[str, str]:
    latest = safe_float(candidate.get("latest_price"))
    score = safe_float(candidate.get("score"))
    setup_type = str(candidate.get("setup_type") or "")
    cash = safe_float(account.get("cash"))
    equity = safe_float(account.get("equity") or account.get("initial_cash") or 1)
    cash_pct = cash / max(equity, 1)
    min_cash_pct = safe_float((config.get("risk") or {}).get("min_cash_pct"), 0.1)
    if latest <= 0:
        return "observe_only", "没有可用价格，不能交易。"
    if setup_type == "risk_avoid":
        return "avoid_for_now", "价格已经明显走弱，先确认风险来源。"
    if cash_pct < min_cash_pct:
        return "watch_confirm", "现金缓冲偏低，新增仓位要等更强确认。"
    if setup_type == "overheated_pullback":
        return "watch_pullback", "涨幅偏高，纪律要求等回踩到计划区间。"
    if score >= 86 and setup_type in {"breakout_follow", "trend_hold"}:
        return "direct_follow", "评分和位置同时满足，允许按计划区间执行。"
    if score >= 78:
        return "watch_confirm", "逻辑不错，但还需要量价或板块确认。"
    return "observe_only", "当前更适合观察，不主动占用交易机会。"


def build_committee_review(candidate: dict[str, Any], account: dict[str, Any], config: dict[str, Any]) -> dict[str, Any]:
    action, trader_summary = action_from_candidate(candidate, account, config)
    score = safe_float(candidate.get("score"))
    expected = safe_float(candidate.get("expected_return_pct"))
    change = safe_float(candidate.get("change_pct"))
    risk_reward = expected / max(abs((safe_float(candidate.get("latest_price")) / max(safe_float(candidate.get("stop_loss")), 0.01) - 1) * 100), 0.01)
    risk_reward = round2(risk_reward)
    debate = [
        f"宏观/市场：{candidate.get('market')} 市场先按低频纪律处理，不因单条新闻临时追涨。",
        f"技术：当日涨跌幅 {round2(change)}%，形态归类为 {candidate.get('setup_label')}。",
        f"赔率：预期空间 {round2(expected)}%，粗略收益风险比 {risk_reward}。",
        f"执行：{trader_summary}",
    ]
    return {
        "symbol": candidate.get("symbol"),
        "name": candidate.get("name"),
        "market": candidate.get("market"),
        "account_id": candidate.get("account_id"),
        "theme": candidate.get("theme"),
        "committee_score": round2(score),
        "committee_action": action,
        "conviction": "high" if action == "direct_follow" else "medium" if action in {"watch_pullback", "watch_confirm"} else "low",
        "debate": debate,
        "macro_agent": {
            "verdict": "neutral",
            "summary": "当前先用市场阶段和外部风险偏好作为背景，不把宏观单独当买点。",
        },
        "sector_agent": {
            "verdict": "positive" if candidate.get("theme") != "其他" else "neutral",
            "summary": f"主题：{candidate.get('theme')}。若同主题持仓过度集中，会被组合经理降权。",
        },
        "technical_agent": {
            "verdict": "positive" if score >= 78 else "neutral",
            "summary": f"{candidate.get('setup_label')}，当日涨跌幅 {round2(change)}%，计划区间 {candidate.get('entry_zone')}。",
        },
        "fundamental_agent": {
            "verdict": "needs_data",
            "summary": "此版本保留基本面字段入口；A股可后续接入 AKShare 财务和公告，港美股接入 Finnhub/Alpha Vantage。",
        },
        "risk_manager": {
            "verdict": "pass" if action == "direct_follow" else "warning" if action in {"watch_pullback", "watch_confirm"} else "avoid",
            "summary": trader_summary,
        },
        "portfolio_manager": {
            "action": action,
            "summary": f"建议仓位 {round2(safe_float(candidate.get('target_position_pct')) * 100)}%，先服从现金、集中度和交易机会限制。",
        },
        "discipline_gate": {
            "verdict": "allow" if action == "direct_follow" else "wait",
            "summary": "新增买入永远排在已有持仓纪律检查之后。",
        },
    }


def build_agent_committee_snapshot(
    candidates: list[dict[str, Any]],
    accounts_by_id: dict[str, dict[str, Any]],
    config: dict[str, Any],
) -> dict[str, Any]:
    reviews = []
    for candidate in candidates:
        account = accounts_by_id.get(str(candidate.get("account_id"))) or {}
        reviews.append(build_committee_review(candidate, account, config))
    priority = {"direct_follow": 0, "watch_pullback": 1, "watch_confirm": 2, "observe_only": 3, "avoid_for_now": 4}
    reviews.sort(key=lambda x: (priority.get(str(x.get("committee_action")), 9), -safe_float(x.get("committee_score"))))
    direct = [x for x in reviews if x.get("committee_action") == "direct_follow"]
    pullback = [x for x in reviews if x.get("committee_action") == "watch_pullback"]
    avoid = [x for x in reviews if x.get("committee_action") == "avoid_for_now"]
    summary = []
    if reviews:
        summary = [
            f"本轮审议 {len(reviews)} 个候选：可直接跟随 {len(direct)} 个，等回踩 {len(pullback)} 个，明确回避 {len(avoid)} 个。",
            "新增买入必须排在持仓纪律检查之后；止损、止盈和移动止盈先执行。",
            "候选不是越多越好，观察池会按市场、主题、赔率和现金约束分层。",
        ]
    return {
        "mode": "multi_market_committee_v3",
        "reviewed_count": len(reviews),
        "summary": summary,
        "portfolio_plan": {
            "new_entry_bias": "attack_selectively" if direct else "wait_for_better_trigger",
            "direct_follow_symbols": [x.get("symbol") for x in direct[:4]],
            "watch_pullback_symbols": [x.get("symbol") for x in pullback[:4]],
            "avoid_symbols": [x.get("symbol") for x in avoid[:4]],
        },
        "candidate_reviews": reviews,
    }


def merge_reviews_into_orders(candidates: list[dict[str, Any]], committee: dict[str, Any]) -> list[dict[str, Any]]:
    review_by_symbol = {str(item.get("symbol")): item for item in committee.get("candidate_reviews") or []}
    orders: list[dict[str, Any]] = []
    for candidate in candidates:
        review = review_by_symbol.get(str(candidate.get("symbol"))) or {}
        order = dict(candidate)
        order.update(
            {
                "committee_action": review.get("committee_action"),
                "committee_score": review.get("committee_score"),
                "committee_conviction": review.get("conviction"),
                "committee_summary": ((review.get("risk_manager") or {}).get("summary")) or "",
                "status": "planned",
            }
        )
        orders.append(order)
    priority = {"direct_follow": 0, "watch_pullback": 1, "watch_confirm": 2, "observe_only": 3, "avoid_for_now": 4}
    orders.sort(key=lambda x: (str(x.get("market")) != "A", priority.get(str(x.get("committee_action")), 9), -safe_float(x.get("committee_score"))))
    for idx, order in enumerate(orders, start=1):
        order["opportunity_slot"] = idx
        order["opportunity_label"] = f"候选交易机会 {idx}"
    return orders


def count_active_trade_slots(trade_log: list[dict[str, Any]], trade_date: str) -> int:
    opportunity_ids = {
        str(item.get("opportunity_id") or "")
        for item in trade_log
        if str(item.get("timestamp") or "")[:10] == trade_date
        and item.get("counts_against_daily_limit") is not False
        and str(item.get("opportunity_id") or "")
    }
    return len(opportunity_ids)


def estimate_buy_shares(order: dict[str, Any], account: dict[str, Any], config: dict[str, Any]) -> int:
    latest = safe_float(order.get("latest_price"))
    if latest <= 0:
        return 0
    target_pct = safe_float(order.get("target_position_pct"))
    budget = safe_float(account.get("equity") or account.get("initial_cash")) * target_pct
    cash_budget = max(safe_float(account.get("cash")) * 0.95, 0)
    budget = min(budget, cash_budget)
    lot = 100 if str(order.get("market")) in {"A", "HK"} else 1
    return max(int(budget / latest / lot) * lot, 0)


def apply_entry_orders(
    positions: list[dict[str, Any]],
    orders: list[dict[str, Any]],
    accounts_by_id: dict[str, dict[str, Any]],
    trade_log: list[dict[str, Any]],
    generated_at: str,
    phase: str,
    config: dict[str, Any],
    active_markets: set[str] | None = None,
) -> list[dict[str, Any]]:
    if not config.get("auto_enter_paper_positions", True) or not is_trading_phase(phase):
        return []
    allowed_markets = {str(m) for m in (active_markets or set()) if m}
    trade_date = generated_at[:10]
    used = count_active_trade_slots(trade_log, trade_date)
    limit = safe_int(config.get("daily_trade_limit"), 4)
    if used >= limit:
        return []
    held_keys = {f"{p.get('account_id')}:{p.get('symbol')}" for p in positions}
    bought_today = {
        f"{item.get('account_id')}:{item.get('symbol')}"
        for item in trade_log
        if str(item.get("timestamp") or "")[:10] == trade_date and item.get("type") == "buy"
    }
    fills: list[dict[str, Any]] = []
    opportunity_id = f"ENTRY-{trade_date}-{used + 1}"
    for order in orders:
        if allowed_markets and str(order.get("market") or "") not in allowed_markets:
            continue
        if order.get("committee_action") != "direct_follow":
            continue
        account_id = str(order.get("account_id") or "")
        key = f"{account_id}:{order.get('symbol')}"
        if key in held_keys or key in bought_today:
            continue
        account = accounts_by_id.get(account_id)
        if not account:
            continue
        latest = safe_float(order.get("latest_price"))
        entry_zone = order.get("entry_zone") or [0, 0]
        upper = safe_float(entry_zone[1])
        if upper and latest > upper * 1.015:
            continue
        shares = estimate_buy_shares(order, account, config)
        if shares <= 0:
            continue
        slippage = safe_float((config.get("fees") or {}).get("slippage_bps"), 8) / 10_000
        fill_price = round2(latest * (1 + slippage))
        gross = round2(fill_price * shares)
        fees = calc_buy_fees(gross, config.get("fees") or {})
        total = round2(gross + fees)
        if total > safe_float(account.get("cash")):
            continue
        account["cash"] = round2(safe_float(account.get("cash")) - total)
        position = {
            "symbol": order.get("symbol"),
            "name": order.get("name"),
            "market": order.get("market"),
            "account_id": account_id,
            "theme": order.get("theme"),
            "strategy_label": "AI纪律交易",
            "confidence": order.get("confidence"),
            "shares": shares,
            "cost_price": round2(total / shares),
            "latest_price": latest,
            "prev_close": order.get("prev_close"),
            "market_value": round2(latest * shares),
            "cost_basis": total,
            "unrealized_pnl": round2(latest * shares - total),
            "unrealized_pnl_pct": round2((latest * shares / total - 1) * 100) if total else 0.0,
            "entry_date": generated_at,
            "entry_zone": order.get("entry_zone"),
            "stop_loss": order.get("stop_loss"),
            "target_price": order.get("target_price"),
            "target_position_pct": round2(safe_float(order.get("target_position_pct")) * 100),
            "holding_thesis": order.get("reason") or [],
            "risk_points": order.get("risks") or [],
            "invalidation": "跌破止损、触发移动止盈、或主题逻辑明显失效时必须处理。",
            "score": order.get("score"),
            "high_watermark": latest,
        }
        positions.append(position)
        held_keys.add(key)
        bought_today.add(key)
        trade = {
            "timestamp": generated_at,
            "type": "buy",
            "symbol": order.get("symbol"),
            "name": order.get("name"),
            "market": order.get("market"),
            "account_id": account_id,
            "price": fill_price,
            "shares": shares,
            "gross_amount": gross,
            "fees": fees,
            "cash_after": account["cash"],
            "reason": order.get("committee_summary") or "委员会放行，按计划区间模拟建仓。",
            "risk_note": "买入后立刻纳入止损、止盈和移动止盈纪律。",
            "counts_against_daily_limit": True,
            "opportunity_id": opportunity_id,
            "opportunity_label": f"主动交易机会 {used + 1}",
        }
        trade_log.append(trade)
        fills.append(trade)
    return fills
