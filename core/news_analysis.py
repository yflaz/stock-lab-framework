from __future__ import annotations

import hashlib
import json
import os
import re
import urllib.request
from pathlib import Path
from typing import Any

from .state_store import load_json, save_json

ROOT = Path(__file__).resolve().parents[1]
NEWS_CACHE_PATH = ROOT / "news_analysis_cache.json"

POSITIVE_TERMS = {
    "订单", "中标", "签约", "扩产", "增持", "回购", "创新高", "增长", "超预期", "扭亏", "提价", "获批", "补贴", "支持", "突破",
    "订单增长", "景气", "催化", "rebound", "beat", "surge", "expansion", "approval", "support", "growth",
}
NEGATIVE_TERMS = {
    "减持", "亏损", "暴跌", "下滑", "风险", "处罚", "调查", "诉讼", "停牌", "违约", "澄清", "辟谣", "制裁", "关税", "回撤", "跳水",
    "miss", "lawsuit", "investigation", "warning", "ban", "tariff", "sanction", "recall",
}
EVENT_TYPE_KEYWORDS = {
    "policy_support": ["政策", "补贴", "支持", "刺激", "专项", "指导意见", "国务院", "工信部", "国常会", "央行"],
    "policy_pressure": ["监管", "处罚", "约谈", "限制", "禁令", "反垄断", "调查", "规范"],
    "earnings_positive": ["预增", "超预期", "增长", "扭亏", "盈利", "上修", "业绩", "利润", "beat"],
    "earnings_negative": ["预亏", "下滑", "亏损", "爆雷", "减值", "miss"],
    "industry_cycle": ["景气", "涨价", "库存", "产能", "扩产", "供需", "开工率", "价格", "运价", "油价"],
    "mna_restructure": ["并购", "重组", "收购", "注入", "借壳", "资产置换"],
    "capital_action": ["回购", "增持", "减持", "定增", "募资", "分红"],
    "geopolitics": ["制裁", "关税", "冲突", "出口管制", "制约"],
    "rumor_clarification": ["澄清", "辟谣", "传闻", "回应"],
}
SHORT_HORIZON_TERMS = {"盘中", "今日", "日内", "明日", "次日", "停复牌", "龙虎榜", "异动", "涨停", "跌停"}
MEDIUM_HORIZON_TERMS = {"订单", "中标", "业绩", "扩产", "景气", "补贴", "政策", "回购", "减持"}
LONG_HORIZON_TERMS = {"产能", "资本开支", "新产线", "长期", "三年", "五年", "规划", "战略"}
SECTOR_SCOPE_TERMS = {"板块", "行业", "赛道", "主题", "产业链", "市场", "sector", "industry"}
MARKET_SCOPE_TERMS = {"a股", "港股", "美股", "nasdaq", "s&p", "恒生", "沪深", "全市场"}

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



def _norm_text(*parts: Any) -> str:
    return " ".join(str(part or "") for part in parts).strip().lower()



def _contains_any(text: str, terms: set[str] | list[str]) -> bool:
    return any(term_matches_text(str(term), text) for term in terms)


def term_matches_text(term: str, text: str) -> bool:
    term = str(term or "").strip().lower()
    text = str(text or "").strip().lower()
    if not term or not text:
        return False
    if all(ord(ch) < 128 for ch in term) and any(ch.isalpha() for ch in term):
        pieces = re.findall(r"[a-z0-9_.+-]+", text)
        if len(term) <= 4:
            return term in pieces
        return any(term == piece or term in piece for piece in pieces)
    return term in text



def _headline_cache_key(item: dict[str, Any]) -> str:
    body = json.dumps(
        {
            "title": item.get("title") or "",
            "source": item.get("source") or "",
            "published_at": item.get("published_at") or "",
            "matched_themes": item.get("matched_themes") or [],
            "related_position_symbols": item.get("related_position_symbols") or [],
            "related_watch_symbols": item.get("related_watch_symbols") or [],
        },
        ensure_ascii=False,
        sort_keys=True,
    )
    return hashlib.sha256(body.encode("utf-8")).hexdigest()



def _load_cache() -> dict[str, Any]:
    data = load_json(NEWS_CACHE_PATH, {})
    return data if isinstance(data, dict) else {}



def _save_cache(cache: dict[str, Any]) -> None:
    save_json(NEWS_CACHE_PATH, cache)



def _first_matching_event_type(text: str) -> str:
    for event_type, terms in EVENT_TYPE_KEYWORDS.items():
        if _contains_any(text, terms):
            return event_type
    return "general_flow"



def _sentiment_from_text(text: str) -> str:
    pos = sum(1 for term in POSITIVE_TERMS if term in text)
    neg = sum(1 for term in NEGATIVE_TERMS if term in text)
    if pos > neg:
        return "bullish"
    if neg > pos:
        return "bearish"
    return "neutral"



def _horizon_from_text(text: str) -> str:
    if _contains_any(text, LONG_HORIZON_TERMS):
        return "long"
    if _contains_any(text, MEDIUM_HORIZON_TERMS):
        return "medium"
    if _contains_any(text, SHORT_HORIZON_TERMS):
        return "short"
    return "short"



def _scope_from_item(text: str, item: dict[str, Any]) -> str:
    related_positions = item.get("related_positions") or []
    related_watch = item.get("related_watchlist") or []
    if len(related_positions) + len(related_watch) >= 3 or _contains_any(text, MARKET_SCOPE_TERMS):
        return "market"
    if len(item.get("matched_themes") or []) >= 1 or _contains_any(text, SECTOR_SCOPE_TERMS):
        return "sector"
    return "single_stock"



def _impact_score(sentiment: str, scope: str, horizon: str, event_type: str, item: dict[str, Any]) -> int:
    score = 1
    if sentiment != "neutral":
        score += 1
    if scope == "sector":
        score += 1
    elif scope == "market":
        score += 2
    if horizon in {"medium", "long"}:
        score += 1
    if event_type in {"policy_support", "policy_pressure", "earnings_positive", "earnings_negative", "industry_cycle", "geopolitics"}:
        score += 1
    if item.get("related_positions"):
        score += 1
    return max(1, min(5, score))



def _confidence(item: dict[str, Any], sentiment: str, event_type: str) -> float:
    conf = 0.45
    if item.get("related_positions") or item.get("related_watchlist"):
        conf += 0.15
    if item.get("matched_themes"):
        conf += 0.1
    if sentiment != "neutral":
        conf += 0.1
    if event_type != "general_flow":
        conf += 0.1
    title = str(item.get("title") or "")
    if len(title) >= 18:
        conf += 0.05
    return round(min(conf, 0.95), 2)



def _why_it_matters(item: dict[str, Any], sentiment: str, scope: str, horizon: str, event_type: str) -> str:
    subjects = []
    subjects.extend([x.get("name") or x.get("symbol") for x in (item.get("related_positions") or [])[:2]])
    subjects.extend([x.get("name") or x.get("symbol") for x in (item.get("related_watchlist") or [])[:2]])
    joined = "、".join(str(x) for x in subjects if x)
    if scope == "market":
        base = "这条更像市场级/跨市场线索，容易先影响情绪和风险偏好。"
    elif scope == "sector":
        base = "这条更像板块级线索，重点看主题内强弱分化和持续性。"
    else:
        base = "这条更偏个股或局部催化，适合和技术位一起看。"
    tail = f" 当前规则判断偏{sentiment}，影响周期偏{horizon}。"
    if joined:
        tail += f" 已命中：{joined}。"
    if event_type == "rumor_clarification":
        tail += " 这类新闻最怕误把澄清当增量利好。"
    return (base + tail).strip()



def _action_hint(sentiment: str, impact_score: int, horizon: str, item: dict[str, Any]) -> str:
    on_book = bool(item.get("related_positions"))
    if sentiment == "bearish" and on_book and impact_score >= 3:
        return "优先检查持仓止损/减仓条件，不把利空全当噪音。"
    if sentiment == "bullish" and impact_score >= 4 and horizon in {"medium", "long"}:
        return "可提高跟踪优先级，但仍需等量价确认，不建议只靠标题追单。"
    if sentiment == "bullish":
        return "先纳入观察，等次日延续或回踩承接确认。"
    if sentiment == "neutral":
        return "保留在线索层，暂不单独改变交易动作。"
    return "先观察是否只是情绪扰动，再决定是否调整仓位。"



def build_rule_news_analysis(item: dict[str, Any]) -> dict[str, Any]:
    text = _norm_text(item.get("title"), item.get("source"), " ".join(item.get("matched_themes") or []))
    event_type = _first_matching_event_type(text)
    sentiment = _sentiment_from_text(text)
    horizon = _horizon_from_text(text)
    scope = _scope_from_item(text, item)
    impact_score = _impact_score(sentiment, scope, horizon, event_type, item)
    confidence = _confidence(item, sentiment, event_type)
    return {
        "event_type": event_type,
        "sentiment": sentiment,
        "impact_scope": scope,
        "impact_horizon": horizon,
        "impact_score": impact_score,
        "confidence": confidence,
        "why_it_matters": _why_it_matters(item, sentiment, scope, horizon, event_type),
        "action_hint": _action_hint(sentiment, impact_score, horizon, item),
    }



def _llm_settings(config: dict[str, Any]) -> dict[str, Any]:
    settings = dict((config.get("news_analysis") or {}).get("llm") or {})
    api_key = (
        os.getenv("STOCK_LAB_NEWS_LLM_API_KEY")
        or os.getenv("OPENAI_API_KEY")
        or settings.get("api_key")
        or ""
    )
    endpoint = (
        os.getenv("STOCK_LAB_NEWS_LLM_ENDPOINT")
        or settings.get("endpoint")
        or "https://api.openai.com/v1/chat/completions"
    )
    model = (
        os.getenv("STOCK_LAB_NEWS_LLM_MODEL")
        or settings.get("model")
        or "gpt-4.1-mini"
    )
    enabled = bool((config.get("news_analysis") or {}).get("enable_llm", True))
    max_items = int((config.get("news_analysis") or {}).get("max_llm_items_per_run") or 3)
    return {
        "enabled": enabled and bool(api_key),
        "api_key": api_key,
        "endpoint": endpoint,
        "model": model,
        "max_items": max(0, max_items),
    }



def _extract_json_block(text: str) -> dict[str, Any] | None:
    text = (text or "").strip()
    if not text:
        return None
    if text.startswith("```"):
        parts = text.split("```")
        for part in parts:
            part = part.strip()
            if part.startswith("json"):
                part = part[4:].strip()
            if part.startswith("{") and part.endswith("}"):
                try:
                    return json.loads(part)
                except Exception:
                    pass
    if text.startswith("{") and text.endswith("}"):
        try:
            return json.loads(text)
        except Exception:
            return None
    start = text.find("{")
    end = text.rfind("}")
    if start >= 0 and end > start:
        try:
            return json.loads(text[start : end + 1])
        except Exception:
            return None
    return None



def _call_llm_for_news(item: dict[str, Any], settings: dict[str, Any]) -> dict[str, Any]:
    prompt = {
        "headline": item.get("title") or "",
        "source": item.get("source") or "",
        "published_at": item.get("published_at") or "",
        "matched_themes": item.get("matched_themes") or [],
        "related_position_symbols": item.get("related_position_symbols") or [],
        "related_watch_symbols": item.get("related_watch_symbols") or [],
    }
    payload = {
        "model": settings["model"],
        "temperature": 0.1,
        "response_format": {"type": "json_object"},
        "messages": [
            {
                "role": "system",
                "content": (
                    "You classify trading-news headlines for a rule-based stock dashboard. "
                    "Return compact JSON only with keys: event_type, sentiment, impact_scope, impact_horizon, confidence, why_it_matters, action_hint. "
                    "Use sentiment in bullish|bearish|neutral, scope in single_stock|sector|market, horizon in short|medium|long."
                ),
            },
            {"role": "user", "content": json.dumps(prompt, ensure_ascii=False)},
        ],
    }
    req = urllib.request.Request(
        settings["endpoint"],
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {settings['api_key']}",
            "User-Agent": "StockLabNewsAnalysis/1.0",
        },
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=20) as resp:
        raw = json.loads(resp.read().decode("utf-8", errors="ignore"))
    content = (((raw.get("choices") or [{}])[0].get("message") or {}).get("content") or "") if isinstance(raw, dict) else ""
    parsed = _extract_json_block(content)
    if not isinstance(parsed, dict):
        raise RuntimeError("LLM returned non-JSON news analysis")
    return {
        "event_type": str(parsed.get("event_type") or "general_flow"),
        "sentiment": str(parsed.get("sentiment") or "neutral"),
        "impact_scope": str(parsed.get("impact_scope") or "sector"),
        "impact_horizon": str(parsed.get("impact_horizon") or "short"),
        "confidence": round(float(parsed.get("confidence") or 0.55), 2),
        "why_it_matters": str(parsed.get("why_it_matters") or ""),
        "action_hint": str(parsed.get("action_hint") or ""),
    }



def analyze_mapped_headlines(mapped_headlines: list[dict[str, Any]], config: dict[str, Any]) -> dict[str, Any]:
    settings = _llm_settings(config)
    cache = _load_cache()
    llm_budget = settings["max_items"]
    llm_used = 0
    cache_hits = 0
    enriched: list[dict[str, Any]] = []
    sentiments = {"bullish": 0, "bearish": 0, "neutral": 0}
    high_impact = 0
    errors: list[str] = []

    for item in mapped_headlines or []:
        rule = build_rule_news_analysis(item)
        final = dict(rule)
        llm_result: dict[str, Any] | None = None
        llm_meta = {"used": False, "cache_hit": False, "error": "", "model": settings["model"] if settings["enabled"] else ""}
        cache_key = _headline_cache_key(item)
        should_try_llm = settings["enabled"] and llm_budget > 0 and (
            bool(item.get("related_positions")) or int(rule.get("impact_score") or 0) >= 4
        )
        if should_try_llm:
            cached = cache.get(cache_key)
            if isinstance(cached, dict) and cached.get("llm"):
                llm_result = dict(cached.get("llm") or {})
                llm_meta["used"] = True
                llm_meta["cache_hit"] = True
                cache_hits += 1
            else:
                try:
                    llm_result = _call_llm_for_news(item, settings)
                    cache[cache_key] = {"llm": llm_result}
                    llm_meta["used"] = True
                    llm_budget -= 1
                    llm_used += 1
                except Exception as exc:
                    llm_meta["error"] = str(exc)
                    errors.append(str(exc))
        if llm_result:
            final.update({k: v for k, v in llm_result.items() if v not in {None, ""}})
            final["impact_score"] = max(int(rule.get("impact_score") or 0), 4 if final.get("impact_scope") == "market" else int(rule.get("impact_score") or 0))
        final["why_it_matters"] = str(final.get("why_it_matters") or rule.get("why_it_matters") or "")
        final["action_hint"] = str(final.get("action_hint") or rule.get("action_hint") or "")
        sentiments[str(final.get("sentiment") or "neutral")] = sentiments.get(str(final.get("sentiment") or "neutral"), 0) + 1
        if int(final.get("impact_score") or 0) >= 4:
            high_impact += 1
        enriched.append(
            {
                **item,
                "news_analysis": {
                    "mode": "hybrid" if llm_result else "rule_only",
                    "rule": rule,
                    "llm": llm_result,
                    "final": final,
                    "llm_meta": llm_meta,
                },
            }
        )
    if settings["enabled"] and llm_used:
        _save_cache(cache)
    summary = {
        "headline_count": len(enriched),
        "high_impact_count": high_impact,
        "bullish_count": sentiments.get("bullish", 0),
        "bearish_count": sentiments.get("bearish", 0),
        "neutral_count": sentiments.get("neutral", 0),
        "llm_enabled": settings["enabled"],
        "llm_used_count": llm_used + cache_hits,
        "rule_only_count": len([x for x in enriched if ((x.get("news_analysis") or {}).get("mode") == "rule_only")]),
    }
    processing = {
        "mode": "hybrid" if settings["enabled"] else "rule_only",
        "llm_enabled": settings["enabled"],
        "llm_model": settings["model"] if settings["enabled"] else "",
        "llm_used_count": llm_used,
        "cache_hit_count": cache_hits,
        "errors": errors[:5],
    }
    return {"items": enriched, "summary": summary, "processing": processing}



def map_headlines_to_symbol(headlines: list[dict[str, Any]], symbol: str, name: str = "", theme: str = "") -> list[dict[str, Any]]:
    digits = "".join(ch for ch in str(symbol) if ch.isdigit())
    terms = [digits.lower()] if digits else []
    clean_name = str(name or "").strip().lower()
    if len(clean_name) >= 2:
        terms.append(clean_name)
    terms.extend(theme_terms(theme))
    hits: list[dict[str, Any]] = []
    seen_titles: set[str] = set()
    for headline in headlines or []:
        title = str(headline.get("title") or "").strip()
        if not title or title in seen_titles:
            continue
        haystack = _norm_text(title, headline.get("source"))
        if any(term_matches_text(term, haystack) for term in terms):
            seen_titles.add(title)
            hits.append(
                {
                    "title": title,
                    "source": headline.get("source") or "",
                    "url": headline.get("url") or "",
                    "published_at": headline.get("published_at") or "",
                    "matched_themes": [theme] if theme else [],
                    "related_positions": [],
                    "related_watchlist": [],
                    "related_position_symbols": [digits] if digits else [],
                    "related_watch_symbols": [],
                }
            )
    return hits[:6]



def build_symbol_news_context(symbol: str, name: str, theme: str, headlines: list[dict[str, Any]], config: dict[str, Any]) -> dict[str, Any]:
    hits = map_headlines_to_symbol(headlines, symbol, name=name, theme=theme)
    pipeline = analyze_mapped_headlines(hits, config) if hits else {"items": [], "summary": {}, "processing": {"mode": "rule_only", "llm_enabled": False, "llm_used_count": 0, "cache_hit_count": 0, "errors": []}}
    items = pipeline.get("items") or []
    finals = [((item.get("news_analysis") or {}).get("final") or {}) for item in items]
    dominant_sentiment = "neutral"
    if sum(1 for x in finals if x.get("sentiment") == "bearish") > sum(1 for x in finals if x.get("sentiment") == "bullish"):
        dominant_sentiment = "bearish"
    elif sum(1 for x in finals if x.get("sentiment") == "bullish") > 0:
        dominant_sentiment = "bullish"
    max_impact = max([int((x.get("impact_score") or 0)) for x in finals] or [0])
    return {
        "has_hits": bool(items),
        "hit_count": len(items),
        "dominant_sentiment": dominant_sentiment,
        "max_impact_score": max_impact,
        "items": items,
        "summary": pipeline.get("summary") or {},
        "processing": pipeline.get("processing") or {},
    }
