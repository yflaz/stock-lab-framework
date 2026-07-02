from __future__ import annotations

from typing import Any

from .discipline import calc_buy_fees, calc_sell_fees, holding_days
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


def _strategy_cfg(config: dict[str, Any]) -> dict[str, Any]:
    return config.get("strategy") or {}


def _screening_cfg(config: dict[str, Any]) -> dict[str, Any]:
    return _strategy_cfg(config).get("screening") or {}


def _cash_cfg(config: dict[str, Any]) -> dict[str, Any]:
    return _strategy_cfg(config).get("cash_management") or {}


def build_candidate(item: dict[str, Any], quote: dict[str, Any], market: str, config: dict[str, Any]) -> dict[str, Any]:
    latest = safe_float(quote.get("latest"))
    prev = safe_float(quote.get("prev_close"))
    change_pct = safe_float(quote.get("change_pct")) if quote else pct_change(latest, prev)
    theme = str(item.get("theme") or "其他")
    focus_themes = set((config.get("strategy") or {}).get("focus_themes") or [])
    screening = _screening_cfg(config)
    focus_bonus = safe_float(screening.get("focus_theme_bonus"), 8.0)
    other_bonus = safe_float(screening.get("non_focus_theme_bonus"), 2.0)
    theme_bonus = focus_bonus if theme in focus_themes or any(x in theme for x in focus_themes) else other_bonus
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


def candidate_quality_gate(candidate: dict[str, Any], config: dict[str, Any]) -> tuple[bool, list[str]]:
    screening = _screening_cfg(config)
    score = safe_float(candidate.get("score"))
    expected = safe_float(candidate.get("expected_return_pct"))
    change_pct = safe_float(candidate.get("change_pct"))
    latest = safe_float(candidate.get("latest_price"))
    entry_zone = candidate.get("entry_zone") or [0, 0]
    lower = safe_float(entry_zone[0])
    upper = safe_float(entry_zone[1])
    notes: list[str] = []
    blockers = 0

    if latest <= 0:
        notes.append("无有效现价")
        blockers += 1
    if score < safe_float(screening.get("min_score"), 70.0):
        notes.append(f"评分 {round2(score)} 低于筛选线")
        blockers += 1
    if expected < safe_float(screening.get("min_expected_return_pct"), 5.0):
        notes.append(f"目标空间 {round2(expected)}% 偏薄")
        blockers += 1
    if change_pct > safe_float(screening.get("max_heat_change_pct"), 7.0):
        notes.append(f"单日涨幅 {round2(change_pct)}% 过热")
        blockers += 1
    if screening.get("prefer_pullback_near_entry", True) and latest > 0 and upper > 0 and latest > upper * 1.03:
        notes.append("价格明显脱离计划区间，不适合马上追")
        blockers += 1
    if latest > 0 and lower > 0 and upper > 0 and lower <= latest <= upper:
        notes.append("价格回到计划区间附近")
    return blockers == 0, notes


def candidate_priority_score(candidate: dict[str, Any], config: dict[str, Any]) -> float:
    score = safe_float(candidate.get("score"))
    expected = safe_float(candidate.get("expected_return_pct"))
    change_pct = safe_float(candidate.get("change_pct"))
    latest = safe_float(candidate.get("latest_price"))
    entry_zone = candidate.get("entry_zone") or [0, 0]
    lower = safe_float(entry_zone[0])
    upper = safe_float(entry_zone[1])
    setup = str(candidate.get("setup_type") or "")
    proximity_bonus = 0.0
    if latest > 0 and lower > 0 and upper > 0:
        if lower <= latest <= upper:
            proximity_bonus = 8.0
        elif latest <= upper * 1.02:
            proximity_bonus = 4.0
        elif latest > upper * 1.03:
            proximity_bonus = -7.0
    setup_bonus = {
        "breakout_follow": 5.0,
        "trend_hold": 3.0,
        "weak_repair": 1.0,
        "overheated_pullback": -5.0,
        "risk_avoid": -15.0,
    }.get(setup, 0.0)
    heat_penalty = max(change_pct - 4.0, 0.0) * 1.2
    return round2(score + expected * 1.3 + proximity_bonus + setup_bonus - heat_penalty)


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
    filtered: list[dict[str, Any]] = []
    for candidate in result:
        passed, notes = candidate_quality_gate(candidate, config)
        candidate["screen_passed"] = passed
        candidate["screen_notes"] = notes
        candidate["priority_score"] = candidate_priority_score(candidate, config)
        if not passed:
            continue
        filtered.append(candidate)
    filtered.sort(key=lambda x: (x.get("market") != "A", -safe_float(x.get("priority_score")), -safe_float(x.get("score")), -safe_float(x.get("expected_return_pct"))))
    max_candidates = safe_int((config.get("strategy") or {}).get("max_candidates_per_market"), 12)
    max_total = safe_int((config.get("strategy") or {}).get("max_total_candidates"), max_candidates * 2)
    by_market: dict[str, list[dict[str, Any]]] = {}
    for candidate in filtered:
        by_market.setdefault(str(candidate.get("market")), []).append(candidate)
    trimmed: list[dict[str, Any]] = []
    for items in by_market.values():
        trimmed.extend(items[:max_candidates])
    trimmed.sort(key=lambda x: (x.get("market") != "A", -safe_float(x.get("priority_score"))))
    return trimmed[:max_total]


def action_from_candidate(candidate: dict[str, Any], account: dict[str, Any], config: dict[str, Any]) -> tuple[str, str]:
    latest = safe_float(candidate.get("latest_price"))
    score = safe_float(candidate.get("score"))
    setup_type = str(candidate.get("setup_type") or "")
    cash = safe_float(account.get("cash"))
    equity = safe_float(account.get("equity") or account.get("initial_cash") or 1)
    cash_pct = cash / max(equity, 1)
    min_cash_pct = safe_float((config.get("risk") or {}).get("min_cash_pct"), 0.1)
    cash_cfg = _cash_cfg(config)
    soft_cash_floor = safe_float(cash_cfg.get("soft_cash_floor_pct"), max(min_cash_pct, 0.18))
    ideal_cash_floor = safe_float(cash_cfg.get("ideal_cash_floor_pct"), max(soft_cash_floor, 0.25))
    expected = safe_float(candidate.get("expected_return_pct"))
    priority_score = safe_float(candidate.get("priority_score") or candidate.get("score"))
    screen_passed = candidate.get("screen_passed") is not False
    entry_zone = candidate.get("entry_zone") or [0, 0]
    lower = safe_float(entry_zone[0])
    upper = safe_float(entry_zone[1])
    near_entry = latest > 0 and lower > 0 and upper > 0 and latest <= upper * 1.02
    if latest <= 0:
        return "observe_only", "没有可用价格，不能交易。"
    if not screen_passed:
        return "avoid_for_now", "今天不在优先观察名单里，先不浪费注意力。"
    if setup_type == "risk_avoid":
        return "avoid_for_now", "价格已经明显走弱，先确认风险来源。"
    if cash_pct < min_cash_pct:
        if priority_score >= 96 and expected >= 9:
            return "watch_confirm", "机会本身不错，但现金已跌破硬缓冲，优先等腾仓或更好确认。"
        return "avoid_for_now", "现金缓冲过低，今天新增仓位不划算。"
    if setup_type == "overheated_pullback":
        return "watch_pullback", "涨幅偏高，纪律要求等回踩到计划区间。"
    if cash_pct < soft_cash_floor and priority_score < 95:
        return "watch_confirm", "手里现金不算宽裕，只有更高把握机会才值得出手。"
    if score >= 88 and expected >= 8 and setup_type in {"breakout_follow", "trend_hold", "weak_repair"}:
        return "direct_follow", "评分和位置同时满足，允许按计划区间执行。"
    if score >= 84 and expected >= 7 and priority_score >= 90 and near_entry and setup_type in {"breakout_follow", "trend_hold", "weak_repair"}:
        return "direct_follow", "虽然不是最极致强势，但位置、赔率和优先级都够，允许更主动一些。"
    if score >= 80 and expected >= 6 and priority_score >= 92 and cash_pct >= soft_cash_floor and setup_type in {"breakout_follow", "trend_hold"}:
        return "direct_follow", "板块和位置都不差，允许把等确认提升为可执行观察。"
    if score >= 80 and expected >= 6:
        return "watch_confirm", "逻辑不错，但更适合继续等位置、量价或板块确认。"
    if cash_pct >= ideal_cash_floor and score >= 76 and expected >= 6.5 and setup_type == "weak_repair":
        return "watch_pullback", "可以继续盯，但先等更舒服的位置，不急着抢。"
    return "observe_only", "当前更适合观察，不主动占用交易机会。"


def build_committee_review(candidate: dict[str, Any], account: dict[str, Any], config: dict[str, Any]) -> dict[str, Any]:
    action, trader_summary = action_from_candidate(candidate, account, config)
    score = safe_float(candidate.get("score"))
    expected = safe_float(candidate.get("expected_return_pct"))
    change = safe_float(candidate.get("change_pct"))
    priority_score = safe_float(candidate.get("priority_score") or candidate.get("score"))
    screen_notes = candidate.get("screen_notes") or []
    risk_reward = expected / max(abs((safe_float(candidate.get("latest_price")) / max(safe_float(candidate.get("stop_loss")), 0.01) - 1) * 100), 0.01)
    risk_reward = round2(risk_reward)
    debate = [
        f"宏观/市场：{candidate.get('market')} 市场先按低频纪律处理，不因单条新闻临时追涨。",
        f"技术：当日涨跌幅 {round2(change)}%，形态归类为 {candidate.get('setup_label')}。",
        f"赔率：预期空间 {round2(expected)}%，粗略收益风险比 {risk_reward}。",
        f"执行：{trader_summary}",
        f"筛选：{'；'.join(screen_notes[:3]) if screen_notes else '通过优先筛选，进入今天重点观察名单。'}",
    ]
    return {
        "symbol": candidate.get("symbol"),
        "name": candidate.get("name"),
        "market": candidate.get("market"),
        "account_id": candidate.get("account_id"),
        "theme": candidate.get("theme"),
        "committee_score": round2(score),
        "priority_score": round2(priority_score),
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
    confirm = [x for x in reviews if x.get("committee_action") == "watch_confirm"]
    avoid = [x for x in reviews if x.get("committee_action") == "avoid_for_now"]
    summary = []
    if reviews:
        summary = [
            f"本轮审议 {len(reviews)} 个候选：可直接跟随 {len(direct)} 个，等回踩 {len(pullback)} 个，明确回避 {len(avoid)} 个。",
            f"其中等确认 {len(confirm)} 个，说明今天更重位置和胜率，不是看到异动就上。",
            "新增买入必须排在持仓纪律检查之后；止损、止盈和移动止盈先执行。",
            "候选不是越多越好，观察池会先筛掉不值得看的，再按市场、主题、赔率和现金约束分层。",
        ]
    return {
        "mode": "multi_market_committee_v3",
        "reviewed_count": len(reviews),
        "summary": summary,
        "portfolio_plan": {
            "new_entry_bias": "attack_selectively" if direct else "wait_for_better_trigger",
            "research_style": "screen-first-then-rotate",
            "direct_follow_symbols": [x.get("symbol") for x in direct[:4]],
            "watch_pullback_symbols": [x.get("symbol") for x in pullback[:4]],
            "watch_confirm_symbols": [x.get("symbol") for x in confirm[:4]],
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


def build_rotation_review(
    position: dict[str, Any],
    candidate: dict[str, Any],
    account: dict[str, Any],
    generated_at: str,
    config: dict[str, Any],
) -> dict[str, Any] | None:
    risk = config.get("risk") or {}
    hold_days = holding_days(position, generated_at)
    pnl_pct = safe_float(position.get("unrealized_pnl_pct"))
    today_pnl_pct = safe_float(position.get("today_pnl_pct"))
    candidate_score = safe_float(candidate.get("committee_score") or candidate.get("score"))
    held_score = safe_float(position.get("score"))
    score_gap = round2(candidate_score - held_score)
    candidate_expected = safe_float(candidate.get("expected_return_pct"))
    held_latest = safe_float(position.get("latest_price"))
    held_target = safe_float(position.get("target_price"))
    held_expected = round2((held_target / held_latest - 1) * 100) if held_latest > 0 and held_target > 0 else 0.0
    expected_gap = round2(candidate_expected - held_expected)
    candidate_action = str(candidate.get("committee_action") or "")
    min_days = safe_int(risk.get("opportunity_review_days"), 3)
    min_score_gap = safe_float(risk.get("opportunity_min_score_gap"), 8.0)
    min_expected_gap = safe_float(risk.get("opportunity_min_expected_return_gap_pct"), 4.0)
    min_candidate_score = safe_float(risk.get("rotation_min_candidate_score"), 84.0)
    max_hold_pnl = safe_float(risk.get("rotation_max_hold_pnl_pct"), 6.0)
    underperform = safe_float(risk.get("rotation_underperform_pct"), 1.5)
    trim_days = safe_int(risk.get("active_trim_hold_days"), min_days)
    trim_score_gap = safe_float(risk.get("active_trim_min_score_gap"), max(4.0, min_score_gap - 1.0))
    trim_expected_gap = safe_float(risk.get("active_trim_min_expected_return_gap_pct"), max(2.0, min_expected_gap - 1.0))
    shares = safe_int(position.get("shares"))
    lot = 100 if str(position.get("market") or account.get("market") or "A") in {"A", "HK"} else 1
    trim_shares = max((shares // 2 // lot) * lot, 0)
    if candidate_action not in {"direct_follow", "watch_confirm"}:
        return None
    if candidate_score < min_candidate_score:
        return None
    if hold_days < min(trim_days, min_days):
        return None
    if pnl_pct > max_hold_pnl and candidate_action == "direct_follow":
        return None
    if candidate_action == "direct_follow":
        if not (score_gap >= min_score_gap and expected_gap >= min_expected_gap and pnl_pct <= underperform):
            return None
        sell_shares = shares
        action = "机会成本换仓"
        action_code = "opportunity_rotation"
        reason = f"{position.get('name') or position.get('symbol')} 持有 {hold_days} 天、当前浮盈亏 {round2(pnl_pct)}%，而 {candidate.get('name') or candidate.get('symbol')} 已进入 direct_follow，评分高 {score_gap} 分、预期空间多 {expected_gap}%。为避免机会成本，优先考虑割弱换强。"
    else:
        weak_now = pnl_pct <= underperform or today_pnl_pct <= -1.5
        if trim_shares <= 0 or not weak_now:
            return None
        if not (score_gap >= trim_score_gap and expected_gap >= trim_expected_gap and hold_days >= trim_days):
            return None
        sell_shares = trim_shares
        action = "主动减仓腾挪"
        action_code = "active_rebalance_trim"
        reason = f"{position.get('name') or position.get('symbol')} 当前弹性一般（持有 {hold_days} 天、浮盈亏 {round2(pnl_pct)}%、今日 {round2(today_pnl_pct)}%），而 {candidate.get('name') or candidate.get('symbol')} 虽仍在等确认，但评分高 {score_gap} 分、预期空间多 {expected_gap}%。先减半腾一点仓位，比一直抱死更灵活。"
    return {
        "symbol": position.get("symbol"),
        "name": position.get("name"),
        "account_id": position.get("account_id") or account.get("id"),
        "market": position.get("market"),
        "action": action,
        "action_code": action_code,
        "mandatory": False,
        "severity": "important",
        "sell_shares": sell_shares,
        "candidate_symbol": candidate.get("symbol"),
        "candidate_name": candidate.get("name"),
        "candidate_account_id": candidate.get("account_id"),
        "candidate_market": candidate.get("market"),
        "candidate_score": candidate_score,
        "candidate_expected_return_pct": candidate_expected,
        "score_gap": score_gap,
        "expected_gap": expected_gap,
        "reason": reason,
        "checks": [
            f"当前持仓评分 {round2(held_score)}，候选评分 {round2(candidate_score)}。",
            f"当前持仓剩余目标空间约 {round2(held_expected)}%，候选预期空间 {round2(candidate_expected)}%。",
            f"持有 {hold_days} 天，浮盈亏 {round2(pnl_pct)}%，今日表现 {round2(today_pnl_pct)}%。",
        ],
    }


def execute_rotation_sell(
    position: dict[str, Any],
    account: dict[str, Any],
    action: dict[str, Any],
    trade_log: list[dict[str, Any]],
    generated_at: str,
    config: dict[str, Any],
) -> dict[str, Any] | None:
    sell_shares = min(safe_int(action.get("sell_shares")), safe_int(position.get("shares")))
    latest = safe_float(position.get("latest_price") or position.get("cost_price"))
    if sell_shares <= 0 or latest <= 0:
        return None
    market = str(position.get("market") or account.get("market") or "A")
    gross = round2(latest * sell_shares)
    fees = calc_sell_fees(gross, config.get("fees") or {}, market)
    net = round2(gross - fees)
    old_shares = safe_int(position.get("shares"))
    old_cost_basis = safe_float(position.get("cost_basis") or old_shares * safe_float(position.get("cost_price")))
    avg_cost = old_cost_basis / old_shares if old_shares else latest
    realized = round2(net - avg_cost * sell_shares)
    account["cash"] = round2(safe_float(account.get("cash")) + net)
    account["realized_pnl"] = round2(safe_float(account.get("realized_pnl")) + realized)
    remaining = old_shares - sell_shares
    position["shares"] = max(remaining, 0)
    position["cost_basis"] = round2(avg_cost * max(remaining, 0))
    position["market_value"] = round2(latest * max(remaining, 0))
    position["unrealized_pnl"] = round2(position["market_value"] - position["cost_basis"])
    position["unrealized_pnl_pct"] = round2((position["market_value"] / position["cost_basis"] - 1) * 100) if position["cost_basis"] else 0.0
    trade = {
        "timestamp": generated_at,
        "type": "sell" if remaining == 0 else "reduce",
        "symbol": position.get("symbol"),
        "name": position.get("name"),
        "market": market,
        "account_id": position.get("account_id") or account.get("id"),
        "price": round2(latest),
        "shares": sell_shares,
        "gross_amount": gross,
        "fees": fees,
        "net_amount": net,
        "realized_pnl": realized,
        "cash_after": account["cash"],
        "reason": action.get("reason"),
        "discipline_action": False,
        "counts_against_daily_limit": False,
        "opportunity_id": f"ROTATE-{generated_at[:10]}-{position.get('symbol')}-{action.get('candidate_symbol')}",
        "opportunity_label": "机会成本换仓",
        "risk_note": "为更强候选腾仓；卖出端不单独占用主动买入额度，买入端仍受 daily_trade_limit 约束。",
    }
    trade_log.append(trade)
    return trade


def apply_rotation_actions(
    positions: list[dict[str, Any]],
    orders: list[dict[str, Any]],
    accounts_by_id: dict[str, dict[str, Any]],
    trade_log: list[dict[str, Any]],
    generated_at: str,
    config: dict[str, Any],
    active_markets: set[str] | None = None,
) -> list[dict[str, Any]]:
    queue: list[dict[str, Any]] = []
    allowed_markets = {str(m) for m in (active_markets or set()) if m}
    candidates_by_account: dict[str, list[dict[str, Any]]] = {}
    for order in orders:
        market = str(order.get("market") or "")
        if allowed_markets and market not in allowed_markets:
            continue
        if order.get("committee_action") != "direct_follow":
            continue
        candidates_by_account.setdefault(str(order.get("account_id") or ""), []).append(order)
    for items in candidates_by_account.values():
        items.sort(key=lambda x: (-safe_float(x.get("committee_score") or x.get("score")), -safe_float(x.get("expected_return_pct"))))
    used_candidate_keys: set[str] = set()
    for position in list(positions):
        market = str(position.get("market") or "")
        if allowed_markets and market not in allowed_markets:
            continue
        account_id = str(position.get("account_id") or config.get("active_account_id"))
        account = accounts_by_id.get(account_id)
        if not account:
            continue
        candidates = candidates_by_account.get(account_id) or []
        candidate = next((item for item in candidates if item.get("symbol") != position.get("symbol") and f"{account_id}:{item.get('symbol')}" not in used_candidate_keys), None)
        if not candidate:
            continue
        action = build_rotation_review(position, candidate, account, generated_at, config)
        if not action:
            continue
        trade = execute_rotation_sell(position, account, action, trade_log, generated_at, config)
        if trade:
            action["executed"] = True
            action["trade"] = trade
            used_candidate_keys.add(f"{account_id}:{candidate.get('symbol')}")
        queue.append(action)
    positions[:] = [p for p in positions if safe_int(p.get("shares")) > 0]
    return queue


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
