from __future__ import annotations

from typing import Any

from .config import load_config
from .market_data import fetch_a_share_quotes, fetch_news_and_macro, fetch_tencent_a_quotes
from .news_analysis import build_symbol_news_context
from .utils import round2, safe_float


def _symbol_for_hist(symbol: str) -> str:
    return f"sh{symbol}" if symbol.startswith("6") else f"sz{symbol}"


def _safe_import_akshare():
    import akshare as ak  # type: ignore

    return ak


def _fetch_fast_a_share_quote(symbol: str) -> tuple[dict[str, Any], dict[str, Any]]:
    """Single-symbol analysis should prefer low-latency quotes.

    AKShare stock_zh_a_spot_em pulls a broad market snapshot and can take minutes,
    which is unacceptable for interactive per-symbol analysis. Use Tencent single-quote
    first, then fall back to the existing broader quote fetcher if needed.
    """
    quotes, health = fetch_tencent_a_quotes([symbol])
    if quotes.get(symbol):
        return quotes[symbol], health
    quotes, health = fetch_a_share_quotes([symbol])
    return quotes.get(symbol) or {}, health


def _to_float_rows(df) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for _, row in df.iterrows():
        rows.append(
            {
                "date": str(row.get("date") or row.get("日期") or ""),
                "open": safe_float(row.get("open") or row.get("开盘")),
                "close": safe_float(row.get("close") or row.get("收盘")),
                "high": safe_float(row.get("high") or row.get("最高")),
                "low": safe_float(row.get("low") or row.get("最低")),
                "amount": safe_float(row.get("amount") or row.get("成交额")),
            }
        )
    return [row for row in rows if row.get("close")]


def _window_stats(rows: list[dict[str, Any]], window: int) -> dict[str, Any]:
    subset = rows[-window:]
    if not subset:
        return {
            "window": window,
            "close": 0.0,
            "min_low": 0.0,
            "max_high": 0.0,
            "deviation_from_low_pct": 0.0,
            "range_span_pct": 0.0,
            "up_days": 0,
            "down_days": 0,
        }
    close = safe_float(subset[-1].get("close"))
    min_low = min(safe_float(x.get("low")) for x in subset)
    max_high = max(safe_float(x.get("high")) for x in subset)
    up_days = 0
    down_days = 0
    for idx in range(1, len(subset)):
        diff = safe_float(subset[idx].get("close")) - safe_float(subset[idx - 1].get("close"))
        if diff > 0:
            up_days += 1
        elif diff < 0:
            down_days += 1
    return {
        "window": window,
        "close": round2(close),
        "min_low": round2(min_low),
        "max_high": round2(max_high),
        "deviation_from_low_pct": round2((close / min_low - 1) * 100) if min_low else 0.0,
        "range_span_pct": round2((max_high / min_low - 1) * 100) if min_low else 0.0,
        "up_days": up_days,
        "down_days": down_days,
    }


def _ma(rows: list[dict[str, Any]], window: int) -> float:
    subset = rows[-window:]
    if len(subset) < window:
        return 0.0
    return round2(sum(safe_float(x.get("close")) for x in subset) / window)


def _average_amount(rows: list[dict[str, Any]], window: int) -> float:
    subset = rows[-window:]
    if len(subset) < max(1, min(window, 3)):
        return 0.0
    amounts = [safe_float(x.get("amount")) for x in subset if safe_float(x.get("amount")) > 0]
    return round2(sum(amounts) / len(amounts)) if amounts else 0.0


def _direction_streak(rows: list[dict[str, Any]], window: int = 10) -> dict[str, Any]:
    subset = rows[-window:]
    if len(subset) < 2:
        return {"days": 0, "direction": "flat", "label": "样本不足"}
    current_direction = "flat"
    streak = 0
    for idx in range(len(subset) - 1, 0, -1):
        diff = safe_float(subset[idx].get("close")) - safe_float(subset[idx - 1].get("close"))
        direction = "up" if diff > 0 else "down" if diff < 0 else "flat"
        if current_direction == "flat":
            current_direction = direction
            streak = 1 if direction != "flat" else 0
            continue
        if direction == current_direction and direction != "flat":
            streak += 1
        else:
            break
    label = {"up": f"连续{streak}天收涨", "down": f"连续{streak}天收跌", "flat": "近端横盘"}.get(current_direction, "近端横盘")
    return {"days": streak, "direction": current_direction, "label": label}


def _volume_consistency(rows: list[dict[str, Any]], window: int = 10) -> dict[str, Any]:
    subset = rows[-window:]
    if len(subset) < 3:
        return {"ratio": 0.0, "label": "样本不足"}
    up_amounts: list[float] = []
    down_amounts: list[float] = []
    for idx in range(1, len(subset)):
        curr = safe_float(subset[idx].get("close"))
        prev = safe_float(subset[idx - 1].get("close"))
        amt = safe_float(subset[idx].get("amount"))
        if amt <= 0:
            continue
        if curr >= prev:
            up_amounts.append(amt)
        else:
            down_amounts.append(amt)
    up_avg = sum(up_amounts) / len(up_amounts) if up_amounts else 0.0
    down_avg = sum(down_amounts) / len(down_amounts) if down_amounts else 0.0
    ratio = round2(up_avg / down_avg) if down_avg else 0.0
    if ratio >= 1.2:
        label = "上涨放量更一致"
    elif ratio and ratio <= 0.9:
        label = "下跌放量更明显"
    else:
        label = "量能一致性一般"
    return {"ratio": ratio, "label": label}


def _action_bias(close: float, ma5: float, ma10: float, ma20: float, triggered_count: int, volume_ratio: float, consistency_ratio: float) -> dict[str, Any]:
    if close >= ma5 >= ma10 >= ma20 > 0 and triggered_count <= 1 and volume_ratio >= 1.0 and consistency_ratio >= 1.0:
        return {"code": "hold_or_buy_pullback", "label": "强势，偏持有/等回踩", "summary": "趋势和量能一致性都不差，别追高，等靠近 5/10 日线更舒服。"}
    if close >= ma10 > 0 and triggered_count <= 2:
        return {"code": "watch_confirm", "label": "观察确认", "summary": "结构还在，但还没强到可以忽略位置，优先等次日确认。"}
    if close < ma10 or triggered_count >= 3:
        return {"code": "reduce_or_avoid", "label": "偏减仓/回避", "summary": "趋势和异动条件已经变差，不宜把波动全当成噪音。"}
    return {"code": "neutral", "label": "中性观察", "summary": "位置与强度都一般，先看后续量价是否继续改善。"}


def _build_alerts(quote: dict[str, Any], rows: list[dict[str, Any]], stats3: dict[str, Any], stats10: dict[str, Any], stats30: dict[str, Any]) -> list[dict[str, Any]]:
    close = safe_float(quote.get("latest") or stats30.get("close"))
    change_pct = safe_float(quote.get("change_pct"))
    ma5 = _ma(rows, 5)
    avg_amt_5 = _average_amount(rows, 5)
    latest_amount = safe_float((quote.get("amount") or (rows[-1].get("amount") if rows else 0)))
    volume_ratio = latest_amount / avg_amt_5 if avg_amt_5 else 0.0
    ma_gap_pct = (close / ma5 - 1) * 100 if ma5 else 0.0
    breakout_pct = (close / stats10.get("max_high") - 1) * 100 if stats10.get("max_high") else 0.0
    intraday_high = max(safe_float(quote.get("high")), close)
    intraday_reversal_pct = ((intraday_high / close - 1) * 100) if close and intraday_high else 0.0

    checks = [
        {
            "key": "change_pct",
            "label": "单日涨幅",
            "current": round2(change_pct),
            "threshold": 7.0,
            "unit": "%",
            "triggered": change_pct >= 7.0,
            "direction": "high",
            "reference": round2(stats3.get("range_span_pct")),
            "reference_label": "3日振幅",
        },
        {
            "key": "deviation_3d",
            "label": "3日偏离",
            "current": round2(stats3.get("deviation_from_low_pct")),
            "threshold": 12.0,
            "unit": "%",
            "triggered": safe_float(stats3.get("deviation_from_low_pct")) >= 12.0,
            "direction": "high",
            "reference": round2(stats10.get("deviation_from_low_pct")),
            "reference_label": "10日偏离",
        },
        {
            "key": "deviation_10d",
            "label": "10日偏离",
            "current": round2(stats10.get("deviation_from_low_pct")),
            "threshold": 25.0,
            "unit": "%",
            "triggered": safe_float(stats10.get("deviation_from_low_pct")) >= 25.0,
            "direction": "high",
            "reference": round2(stats30.get("deviation_from_low_pct")),
            "reference_label": "30日偏离",
        },
        {
            "key": "ma5_gap",
            "label": "5日均线乖离",
            "current": round2(ma_gap_pct),
            "threshold": 8.0,
            "unit": "%",
            "triggered": ma_gap_pct >= 8.0,
            "direction": "high",
            "reference": ma5,
            "reference_label": "MA5",
        },
        {
            "key": "volume_ratio",
            "label": "放量程度",
            "current": round2(volume_ratio),
            "threshold": 1.8,
            "unit": "x",
            "triggered": volume_ratio >= 1.8,
            "direction": "high",
            "reference": round2(avg_amt_5),
            "reference_label": "5日均额",
        },
        {
            "key": "breakout_10d",
            "label": "10日新高突破",
            "current": round2(breakout_pct),
            "threshold": 0.0,
            "unit": "%",
            "triggered": breakout_pct >= 0.0,
            "direction": "high",
            "reference": round2(stats10.get("max_high")),
            "reference_label": "10日高点",
        },
        {
            "key": "intraday_reversal",
            "label": "日内冲高回落",
            "current": round2(intraday_reversal_pct),
            "threshold": 3.0,
            "unit": "%",
            "triggered": intraday_reversal_pct >= 3.0,
            "direction": "high",
            "reference": round2(intraday_high),
            "reference_label": "日内高点",
        },
    ]
    for item in checks:
        threshold = abs(safe_float(item.get("threshold"))) or 1.0
        item["progress_pct"] = max(0.0, min(100.0, round2(abs(safe_float(item.get("current"))) / threshold * 100)))
    return checks


def _risk_level(triggered_count: int) -> tuple[str, str, str]:
    if triggered_count >= 4:
        return "异动明显", "warn", "短线异动已达到多条件共振，优先防追高和次日冲高回落。"
    if triggered_count >= 2:
        return "轻度异动", "info", "已经有部分异动信号，适合等回踩或次日确认，不宜情绪化追单。"
    return "状态正常", "good", "暂未出现明显过热异动，更多是常规波动。"


def analyze_a_share_stock(symbol: str, detailed: bool = False) -> dict[str, Any]:
    digits = "".join(ch for ch in str(symbol) if ch.isdigit())
    if len(digits) != 6:
        raise ValueError("symbol must be a 6-digit A-share code")

    quote, quote_health = _fetch_fast_a_share_quote(digits)

    ak = _safe_import_akshare()
    hist = ak.stock_zh_a_hist_tx(symbol=_symbol_for_hist(digits), start_date="20260101", end_date="20261231", adjust="qfq")
    rows = _to_float_rows(hist)
    if len(rows) < 10:
        raise RuntimeError("not enough history returned for analysis")

    stats3 = _window_stats(rows, 3)
    stats10 = _window_stats(rows, 10)
    stats30 = _window_stats(rows, 30)
    streak = _direction_streak(rows, 10)
    volume_consistency = _volume_consistency(rows, 10)
    latest = rows[-1]
    close = safe_float(quote.get("latest") or latest.get("close"))
    low10 = safe_float(stats10.get("min_low"))
    high10 = safe_float(stats10.get("max_high"))
    low30 = safe_float(stats30.get("min_low"))
    high30 = safe_float(stats30.get("max_high"))
    ma5 = _ma(rows, 5)
    ma10 = _ma(rows, 10)
    ma20 = _ma(rows, 20)

    support = round2(max(low10, ma10)) if low10 and ma10 else round2(low10 or ma10)
    hard_stop = round2(min(low10, ma20) * 0.985) if (low10 or ma20) else 0.0
    resistance = round2(max(high10, close))
    take_profit = round2(max(resistance * 1.03 if resistance else 0.0, close * 1.08, high30 * 0.985 if high30 else 0.0))

    alerts = _build_alerts({**quote, **latest}, rows, stats3, stats10, stats30)
    triggered = [x for x in alerts if x.get("triggered")]
    status_text, status_kind, status_summary = _risk_level(len(triggered))
    latest_amount = safe_float(quote.get("amount") or latest.get("amount"))
    avg_amount_5 = _average_amount(rows, 5)
    volume_ratio = round2(latest_amount / avg_amount_5) if avg_amount_5 else 0.0

    trend_label = "强趋势上行" if close >= ma5 >= ma10 >= ma20 > 0 else "均线抬升中" if close >= ma5 >= ma10 > 0 else "趋势一般" if close >= ma10 > 0 else "偏弱整理"
    action_bias = _action_bias(close, ma5, ma10, ma20, len(triggered), volume_ratio, safe_float(volume_consistency.get("ratio")))
    config = load_config()
    external = fetch_news_and_macro(config)
    news_context = build_symbol_news_context(digits, quote.get("name") or latest.get("name") or digits, "", external.get("headlines") or [], config)

    result = {
        "ok": True,
        "symbol": digits,
        "name": quote.get("name") or latest.get("name") or digits,
        "market": "A",
        "detailed": bool(detailed),
        "status": {
            "text": status_text,
            "kind": status_kind,
            "summary": status_summary,
            "triggered_count": len(triggered),
            "total_checks": len(alerts),
        },
        "quote": {
            "latest": round2(close),
            "prev_close": round2(quote.get("prev_close") or latest.get("close")),
            "change_pct": round2(quote.get("change_pct") or 0),
            "open": round2(quote.get("open") or latest.get("open")),
            "high": round2(quote.get("high") or latest.get("high")),
            "low": round2(quote.get("low") or latest.get("low")),
            "amount": round2(quote.get("amount") or latest.get("amount")),
            "data_source": quote.get("data_source") or quote_health.get("source") or "A-share quote",
            "history_source": "AKShare stock_zh_a_hist_tx",
        },
        "metrics": {
            "deviation_3d_pct": round2(stats3.get("deviation_from_low_pct")),
            "deviation_10d_pct": round2(stats10.get("deviation_from_low_pct")),
            "deviation_30d_pct": round2(stats30.get("deviation_from_low_pct")),
            "same_direction_10d": streak,
            "range_10d_pct": round2(stats10.get("range_span_pct")),
            "range_30d_pct": round2(stats30.get("range_span_pct")),
            "ma5": ma5,
            "ma10": ma10,
            "ma20": ma20,
            "trend_label": trend_label,
            "volume_ratio_5d": volume_ratio,
            "volume_consistency": volume_consistency,
            "action_bias": action_bias,
        },
        "levels": {
            "support": support,
            "hard_stop": hard_stop,
            "resistance": resistance,
            "take_profit": take_profit,
            "low_10d": low10,
            "high_10d": high10,
            "low_30d": low30,
            "high_30d": high30,
        },
        "alerts": alerts,
        "analysis": [
            f"近3日价格相对区间低点偏离 {round2(stats3.get('deviation_from_low_pct'))}%，反映短线提速程度。",
            f"近10日偏离 {round2(stats10.get('deviation_from_low_pct'))}%，近30日偏离 {round2(stats30.get('deviation_from_low_pct'))}%。",
            f"{streak.get('label')}；当前趋势判断：{trend_label}；量能一致性：{volume_consistency.get('label')}。",
            f"更稳的防守位先看 {support}，硬止损参考 {hard_stop}；若继续上攻，先看 {take_profit} 一带是否出现放量滞涨。",
            f"当前动作倾向：{action_bias.get('label')}。{action_bias.get('summary')}",
        ],
        "news_context": news_context,
        "as_of": latest.get("date"),
    }
    if news_context.get("has_hits"):
        sentiment = news_context.get("dominant_sentiment") or "neutral"
        impact = news_context.get("max_impact_score") or 0
        result["analysis"].append(f"现实新闻命中 {news_context.get('hit_count')} 条，整体偏{sentiment}，最高影响分 {impact}/5；分析时已纳入考虑。")
        first = (((news_context.get("items") or [{}])[0].get("news_analysis") or {}).get("final") or {})
        if first.get("action_hint"):
            result["analysis"].append(str(first.get("action_hint")))
    else:
        result["analysis"].append("当前未命中与该股直接相关的实时新闻，暂按量价结构为主。")
    if detailed:
        result["detailed_report"] = {
            "overview": [
                f"最新价 {round2(close)}，当日区间 {round2(safe_float(latest.get('low')))} - {round2(safe_float(latest.get('high')))}，成交额 {round2(safe_float(quote.get('amount') or latest.get('amount')))}。",
                f"均线结构：MA5 {ma5}，MA10 {ma10}，MA20 {ma20}；当前判断为“{trend_label}”。",
                f"近10日振幅约 {round2(stats10.get('range_span_pct'))}%，近30日振幅约 {round2(stats30.get('range_span_pct'))}%。",
                f"新闻处理模式：{(news_context.get('processing') or {}).get('mode') or 'rule_only'}；命中 {news_context.get('hit_count') or 0} 条。",
            ],
            "thesis": [
                f"防守位优先看 {support}，因为它更贴近近10日低点和均线承接；真正结构破坏参考 {hard_stop}。",
                f"止盈优先看 {take_profit}，这是按近10/30日阻力与常规波段空间综合得出的兑现位。",
                "如果异动信号达到 2 项以上，更适合等回踩确认，不把强势直接当成追涨理由。",
            ],
            "signals": [
                f"已触发 {len(triggered)} / {len(alerts)} 项异动条件。",
                *[f"{item.get('label')}：当前 {item.get('current')}，阈值 {item.get('threshold')}。" for item in triggered[:4]],
            ],
            "action_plan": [
                f"偏稳做法：只在 {support} 附近承接，跌破 {hard_stop} 不恋战。",
                f"若已持有：靠近 {take_profit} 先考虑兑现一部分，再观察是否出现放量滞涨。",
                "若未持有：优先拿它和当前持仓/观察池里的更强票比较，再决定是否替换仓位。",
            ],
            "risk_focus": [
                "连续上涨后若量价背离，容易从强趋势切回高位震荡。",
                "若异动主要由情绪推动而非板块共振，次日回落概率会升高。",
                "若均线重新走坏且硬止损失守，说明本轮交易假设已经被破坏。",
            ],
        }
        if news_context.get("has_hits"):
            result["detailed_report"]["news"] = [
                f"{item.get('title')}｜{(((item.get('news_analysis') or {}).get('final') or {}).get('sentiment') or 'neutral')}｜影响分 {(((item.get('news_analysis') or {}).get('final') or {}).get('impact_score') or 0)}｜{((((item.get('news_analysis') or {}).get('final') or {}).get('action_hint')) or '继续观察')}"
                for item in (news_context.get("items") or [])[:4]
            ]
        else:
            result["detailed_report"]["news"] = ["当前未命中与该股直接相关的实时新闻，暂不额外上调或下调新闻权重。"]
    return result
