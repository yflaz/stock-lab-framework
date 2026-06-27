from __future__ import annotations

from datetime import datetime
from typing import Any

from .utils import money_text, round2, safe_float, safe_int


def calc_commission(gross_amount: float, fees: dict[str, Any]) -> float:
    if gross_amount <= 0:
        return 0.0
    return round2(max(gross_amount * safe_float(fees.get("commission_rate"), 0.00025), safe_float(fees.get("min_commission"), 5.0)))


def calc_sell_fees(gross_amount: float, fees: dict[str, Any], market: str) -> float:
    stamp = gross_amount * safe_float(fees.get("stamp_duty_sell"), 0.001) if market == "A" else 0.0
    return round2(calc_commission(gross_amount, fees) + stamp)


def calc_buy_fees(gross_amount: float, fees: dict[str, Any]) -> float:
    return calc_commission(gross_amount, fees)


def holding_days(position: dict[str, Any], generated_at: str) -> int:
    raw = str(position.get("entry_date") or position.get("created_at") or "")[:19]
    if not raw:
        return 0
    try:
        start = datetime.fromisoformat(raw)
        end = datetime.fromisoformat(generated_at[:19])
    except ValueError:
        return 0
    return max((end.date() - start.date()).days, 0)


def shares_for_fraction(shares: int, fraction: float) -> int:
    if shares <= 0:
        return 0
    if shares <= 100:
        return shares
    planned = int(shares * fraction / 100) * 100
    return min(max(planned, 100), shares)


def evaluate_position_discipline(
    position: dict[str, Any],
    account: dict[str, Any],
    config: dict[str, Any],
    generated_at: str,
) -> dict[str, Any]:
    risk = config.get("risk") or {}
    shares = safe_int(position.get("shares"))
    latest = safe_float(position.get("latest_price") or position.get("cost_price"))
    cost_price = safe_float(position.get("cost_price"))
    stop = safe_float(position.get("stop_loss"))
    target = safe_float(position.get("target_price"))
    market = str(position.get("market") or account.get("market") or "A")
    currency = str(account.get("currency") or "CNY")
    market_value = round2(latest * shares)
    equity = safe_float(account.get("equity") or account.get("initial_cash") or 1.0, 1.0)
    position_pct = round2(market_value / max(equity, 1.0))
    pnl_pct = round2((latest / cost_price - 1) * 100) if cost_price else 0.0
    today_pct = safe_float(position.get("today_pnl_pct") or position.get("change_pct"))
    high_watermark = max(safe_float(position.get("high_watermark")), latest, cost_price)
    position["high_watermark"] = round2(high_watermark)

    checks = [
        f"现价 {money_text(latest, currency)}，成本 {money_text(cost_price, currency)}，浮盈亏 {pnl_pct}%。",
        f"止损 {money_text(stop, currency) if stop else '未设置'}，目标 {money_text(target, currency) if target else '未设置'}。",
        f"当前占账户约 {round2(position_pct * 100)}%，规则上限 {round2(safe_float(risk.get('max_position_pct'), 0.25) * 100)}%。",
    ]

    if shares <= 0 or latest <= 0:
        return {
            "symbol": position.get("symbol"),
            "name": position.get("name"),
            "account_id": position.get("account_id") or account.get("id"),
            "market": market,
            "action": "数据不足",
            "action_code": "data_missing",
            "mandatory": False,
            "severity": "warning",
            "sell_shares": 0,
            "reason": "没有足够价格或股数信息，不能给出纪律动作。",
            "checks": checks,
        }

    if risk.get("hard_stop_enabled", True) and stop > 0 and latest <= stop:
        return {
            "symbol": position.get("symbol"),
            "name": position.get("name"),
            "account_id": position.get("account_id") or account.get("id"),
            "market": market,
            "action": "强制止损",
            "action_code": "hard_stop_sell_all",
            "mandatory": True,
            "severity": "critical",
            "sell_shares": shares,
            "reason": f"现价 {money_text(latest, currency)} 已触及/跌破止损 {money_text(stop, currency)}，纪律优先于主观判断。",
            "checks": checks,
        }

    if risk.get("take_profit_enabled", True) and target > 0 and latest >= target and not position.get("take_profit_1_done"):
        sell_shares = shares_for_fraction(shares, safe_float(risk.get("take_profit_fraction"), 0.5))
        return {
            "symbol": position.get("symbol"),
            "name": position.get("name"),
            "account_id": position.get("account_id") or account.get("id"),
            "market": market,
            "action": "到达目标分批止盈",
            "action_code": "take_profit_partial",
            "mandatory": True,
            "severity": "important",
            "sell_shares": sell_shares,
            "reason": f"现价 {money_text(latest, currency)} 已达到目标 {money_text(target, currency)}，先兑现一部分收益，剩余仓位再用移动止盈保护。",
            "checks": checks,
        }

    if (
        high_watermark > cost_price * (1 + safe_float(risk.get("trailing_activation_pct"), 8.0) / 100)
        and latest <= high_watermark * (1 - safe_float(risk.get("trailing_drawdown_pct"), 4.0) / 100)
    ):
        return {
            "symbol": position.get("symbol"),
            "name": position.get("name"),
            "account_id": position.get("account_id") or account.get("id"),
            "market": market,
            "action": "移动止盈触发",
            "action_code": "trailing_reduce",
            "mandatory": True,
            "severity": "important",
            "sell_shares": shares_for_fraction(shares, 0.5),
            "reason": f"曾经涨到 {money_text(high_watermark, currency)}，现在回撤超过移动止盈阈值，避免把盈利完整还回去。",
            "checks": checks,
        }

    days = holding_days(position, generated_at)
    if days >= safe_int(risk.get("time_stop_days"), 5) and pnl_pct <= safe_float(risk.get("time_stop_min_pnl_pct"), -2.5):
        return {
            "symbol": position.get("symbol"),
            "name": position.get("name"),
            "account_id": position.get("account_id") or account.get("id"),
            "market": market,
            "action": "时间止损复核",
            "action_code": "time_stop_review",
            "mandatory": False,
            "severity": "warning",
            "sell_shares": shares_for_fraction(shares, 0.5),
            "reason": f"持有 {days} 天仍未兑现预期且浮亏 {pnl_pct}%，需要复核是否占用更好的机会。",
            "checks": checks,
        }

    if today_pct <= safe_float(risk.get("volatility_shock_pct"), -5.0):
        return {
            "symbol": position.get("symbol"),
            "name": position.get("name"),
            "account_id": position.get("account_id") or account.get("id"),
            "market": market,
            "action": "日内异常波动复核",
            "action_code": "volatility_shock_review",
            "mandatory": False,
            "severity": "warning",
            "sell_shares": 0,
            "reason": f"今日跌幅 {round2(today_pct)}%，虽然未必触发止损，但必须确认是否有突发利空或板块退潮。",
            "checks": checks,
        }

    if position_pct > safe_float(risk.get("max_position_pct"), 0.25):
        return {
            "symbol": position.get("symbol"),
            "name": position.get("name"),
            "account_id": position.get("account_id") or account.get("id"),
            "market": market,
            "action": "单票集中度过高",
            "action_code": "concentration_trim_review",
            "mandatory": False,
            "severity": "warning",
            "sell_shares": shares_for_fraction(shares, 0.25),
            "reason": f"单票仓位约 {round2(position_pct * 100)}%，超过规则上限，下一次调仓优先考虑降集中度。",
            "checks": checks,
        }

    return {
        "symbol": position.get("symbol"),
        "name": position.get("name"),
        "account_id": position.get("account_id") or account.get("id"),
        "market": market,
        "action": "继续持有",
        "action_code": "hold",
        "mandatory": False,
        "severity": "pass",
        "sell_shares": 0,
        "reason": "价格没有触发强制纪律动作，继续按原计划跟踪。",
        "checks": checks,
    }


def execute_sell_action(
    position: dict[str, Any],
    account: dict[str, Any],
    action: dict[str, Any],
    trade_log: list[dict[str, Any]],
    generated_at: str,
    config: dict[str, Any],
) -> dict[str, Any] | None:
    sell_shares = min(safe_int(action.get("sell_shares")), safe_int(position.get("shares")))
    if sell_shares <= 0:
        return None
    latest = safe_float(position.get("latest_price") or position.get("cost_price"))
    if latest <= 0:
        return None
    market = str(position.get("market") or account.get("market") or "A")
    currency = str(account.get("currency") or "CNY")
    fees_cfg = config.get("fees") or {}
    gross = round2(latest * sell_shares)
    fees = calc_sell_fees(gross, fees_cfg, market)
    net = round2(gross - fees)
    old_shares = safe_int(position.get("shares"))
    old_cost_basis = safe_float(position.get("cost_basis") or old_shares * safe_float(position.get("cost_price")))
    avg_cost = old_cost_basis / old_shares if old_shares else latest
    realized = round2(net - avg_cost * sell_shares)

    account["cash"] = round2(safe_float(account.get("cash")) + net)
    account["realized_pnl"] = round2(safe_float(account.get("realized_pnl")) + realized)

    remaining = old_shares - sell_shares
    position["shares"] = remaining
    position["cost_basis"] = round2(avg_cost * remaining)
    position["market_value"] = round2(latest * remaining)
    position["unrealized_pnl"] = round2(position["market_value"] - position["cost_basis"])
    position["unrealized_pnl_pct"] = round2((position["market_value"] / position["cost_basis"] - 1) * 100) if position["cost_basis"] else 0.0
    if action.get("action_code") == "take_profit_partial":
        position["take_profit_1_done"] = True

    trade = {
        "timestamp": generated_at,
        "type": "sell" if remaining == 0 else "reduce",
        "symbol": position.get("symbol"),
        "name": position.get("name"),
        "account_id": position.get("account_id") or account.get("id"),
        "market": market,
        "currency": currency,
        "price": round2(latest),
        "shares": sell_shares,
        "gross_amount": gross,
        "fees": fees,
        "net_amount": net,
        "realized_pnl": realized,
        "cash_after": account["cash"],
        "reason": action.get("reason"),
        "discipline_action": True,
        "counts_against_daily_limit": False,
        "opportunity_id": f"RISK-{generated_at[:10]}-{position.get('symbol')}-{action.get('action_code')}",
        "opportunity_label": action.get("action"),
        "risk_note": "纪律动作不占用主动交易机会，避免因为额度用完而错过风险控制。",
    }
    trade_log.append(trade)
    return trade


def apply_discipline_actions(
    positions: list[dict[str, Any]],
    accounts_by_id: dict[str, dict[str, Any]],
    trade_log: list[dict[str, Any]],
    generated_at: str,
    config: dict[str, Any],
    active_markets: set[str] | None = None,
) -> list[dict[str, Any]]:
    queue: list[dict[str, Any]] = []
    existing_ids = {
        str(item.get("opportunity_id") or "")
        for item in trade_log
        if str(item.get("timestamp") or "")[:10] == generated_at[:10]
    }
    allowed_markets = {str(m) for m in (active_markets or set()) if m}
    for position in list(positions):
        market = str(position.get("market") or "")
        if allowed_markets and market not in allowed_markets:
            continue
        account_id = str(position.get("account_id") or config.get("active_account_id"))
        account = accounts_by_id.get(account_id)
        if not account:
            continue
        action = evaluate_position_discipline(position, account, config, generated_at)
        queue.append(action)
        trade_id = f"RISK-{generated_at[:10]}-{position.get('symbol')}-{action.get('action_code')}"
        if action.get("mandatory") and trade_id not in existing_ids:
            trade = execute_sell_action(position, account, action, trade_log, generated_at, config)
            if trade:
                action["executed"] = True
                action["trade"] = trade
                existing_ids.add(trade_id)
    positions[:] = [p for p in positions if safe_int(p.get("shares")) > 0]
    return queue

