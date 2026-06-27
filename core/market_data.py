from __future__ import annotations

import json
import urllib.parse
import urllib.request
from typing import Any

from .utils import pct_change, round2, safe_float, symbol_digits


def fetch_json_url(url: str, timeout: int = 8) -> Any:
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 StockLabNew/1.0"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8", errors="ignore"))


def quote_symbol_for_tencent(symbol: str) -> str:
    digits = symbol_digits(symbol)
    if not digits:
        return symbol
    return f"sh{digits}" if digits.startswith("6") else f"sz{digits}"


def fetch_akshare_a_quotes(symbols: list[str]) -> tuple[dict[str, dict[str, Any]], dict[str, Any]]:
    health = {"source": "AKShare stock_zh_a_spot_em", "ok": True, "message": ""}
    if not symbols:
        return {}, health
    try:
        import akshare as ak  # type: ignore

        spot = ak.stock_zh_a_spot_em()
    except Exception as exc:
        health.update({"ok": False, "message": str(exc)})
        return {}, health
    wanted = {symbol_digits(s) for s in symbols}
    quotes: dict[str, dict[str, Any]] = {}
    try:
        for _, row in spot.iterrows():
            symbol = str(row.get("代码") or "")
            if symbol not in wanted:
                continue
            latest = safe_float(row.get("最新价"))
            prev_close = safe_float(row.get("昨收"))
            quotes[symbol] = {
                "symbol": symbol,
                "name": str(row.get("名称") or symbol),
                "market": "A",
                "latest": round2(latest),
                "prev_close": round2(prev_close),
                "open": round2(row.get("今开")),
                "high": round2(row.get("最高")),
                "low": round2(row.get("最低")),
                "amount": round2(row.get("成交额")),
                "change_pct": round2(row.get("涨跌幅")) if row.get("涨跌幅") is not None else pct_change(latest, prev_close),
                "data_source": health["source"],
            }
    except Exception as exc:
        health.update({"ok": False, "message": str(exc)})
        return {}, health
    if not quotes:
        health.update({"ok": False, "message": "AKShare returned no requested symbols"})
    return quotes, health


def fetch_tencent_a_quotes(symbols: list[str]) -> tuple[dict[str, dict[str, Any]], dict[str, Any]]:
    health = {"source": "Tencent qt.gtimg.cn fallback", "ok": True, "message": ""}
    if not symbols:
        return {}, health
    joined = ",".join(quote_symbol_for_tencent(s) for s in symbols)
    url = f"https://qt.gtimg.cn/q={joined}"
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 StockLabNew/1.0"})
        raw = urllib.request.urlopen(req, timeout=8).read().decode("gbk", errors="ignore")
    except Exception as exc:
        health.update({"ok": False, "message": str(exc)})
        return {}, health

    quotes: dict[str, dict[str, Any]] = {}
    for line in raw.split(";"):
        line = line.strip()
        if not line or '="' not in line:
            continue
        body = line.split('="', 1)[1].rstrip('"')
        parts = body.split("~")
        if len(parts) < 6:
            continue
        symbol = parts[2].strip()
        latest = safe_float(parts[3])
        prev_close = safe_float(parts[4])
        open_price = safe_float(parts[5])
        high = safe_float(parts[33] if len(parts) > 33 else 0)
        low = safe_float(parts[34] if len(parts) > 34 else 0)
        amount = safe_float(parts[37] if len(parts) > 37 else 0)
        if symbol:
            quotes[symbol] = {
                "symbol": symbol,
                "name": parts[1].strip(),
                "market": "A",
                "latest": round2(latest),
                "prev_close": round2(prev_close),
                "open": round2(open_price),
                "high": round2(high),
                "low": round2(low),
                "amount": round2(amount),
                "change_pct": pct_change(latest, prev_close),
                "data_source": health["source"],
            }
    if not quotes:
        health.update({"ok": False, "message": "Tencent quote returned no usable rows"})
    return quotes, health


def fetch_a_share_quotes(symbols: list[str]) -> tuple[dict[str, dict[str, Any]], dict[str, Any]]:
    quotes, health = fetch_akshare_a_quotes(symbols)
    if quotes:
        return quotes, health
    fallback_quotes, fallback_health = fetch_tencent_a_quotes(symbols)
    if fallback_quotes:
        fallback_health["message"] = f"AKShare failed first: {health.get('message')}"
        return fallback_quotes, fallback_health
    return {}, health


def fetch_twelve_data_quotes(symbols: list[str], market: str, api_key: str) -> tuple[dict[str, dict[str, Any]], dict[str, Any]]:
    health = {"source": "Twelve Data", "ok": bool(api_key), "message": ""}
    if not symbols:
        return {}, health
    if not api_key:
        health["message"] = "TWELVE_DATA_API_KEY is not configured"
        return {}, health
    quotes: dict[str, dict[str, Any]] = {}
    for symbol in symbols:
        query = urllib.parse.urlencode({"symbol": symbol, "apikey": api_key})
        try:
            data = fetch_json_url(f"https://api.twelvedata.com/quote?{query}", timeout=8)
        except Exception as exc:
            health.update({"ok": False, "message": str(exc)})
            continue
        if not isinstance(data, dict) or data.get("code"):
            health.update({"ok": False, "message": str(data.get("message") or "quote error")[:160]})
            continue
        latest = safe_float(data.get("close") or data.get("price"))
        prev_close = safe_float(data.get("previous_close"))
        quotes[symbol] = {
            "symbol": symbol,
            "name": data.get("name") or symbol,
            "market": market,
            "latest": round2(latest),
            "prev_close": round2(prev_close),
            "open": round2(data.get("open")),
            "high": round2(data.get("high")),
            "low": round2(data.get("low")),
            "amount": 0.0,
            "change_pct": pct_change(latest, prev_close),
            "data_source": health["source"],
        }
    if quotes:
        health.update({"ok": True, "message": ""})
    return quotes, health


def fetch_alpha_quote(symbol: str, api_key: str) -> dict[str, Any] | None:
    if not api_key:
        return None
    query = urllib.parse.urlencode({"function": "GLOBAL_QUOTE", "symbol": symbol, "apikey": api_key})
    data = fetch_json_url(f"https://www.alphavantage.co/query?{query}", timeout=8)
    quote = data.get("Global Quote") if isinstance(data, dict) else None
    if not quote:
        return None
    latest = safe_float(quote.get("05. price"))
    prev = latest - safe_float(quote.get("09. change"))
    return {
        "symbol": symbol,
        "name": symbol,
        "market": "US",
        "latest": round2(latest),
        "prev_close": round2(prev),
        "change_pct": round2(quote.get("10. change percent")),
        "data_source": "Alpha Vantage",
    }


def fetch_yahoo_quote(symbol: str, market: str) -> dict[str, Any] | None:
    url = f"https://query1.finance.yahoo.com/v8/finance/chart/{urllib.parse.quote(symbol)}?interval=1d&range=5d"
    data = fetch_json_url(url, timeout=8)
    chart = ((data or {}).get("chart") or {}).get("result") or []
    if not chart:
        return None
    meta = chart[0].get("meta") or {}
    indicators = ((chart[0].get("indicators") or {}).get("quote") or [{}])[0]
    closes = indicators.get("close") or []
    highs = indicators.get("high") or []
    lows = indicators.get("low") or []
    opens = indicators.get("open") or []
    latest = safe_float(meta.get("regularMarketPrice") or next((x for x in reversed(closes) if x is not None), 0))
    prev_close = safe_float(meta.get("chartPreviousClose") or meta.get("previousClose") or 0)
    if latest <= 0:
        return None
    return {
        "symbol": symbol,
        "name": meta.get("shortName") or meta.get("symbol") or symbol,
        "market": market,
        "latest": round2(latest),
        "prev_close": round2(prev_close),
        "open": round2(opens[-1] if opens else 0),
        "high": round2(highs[-1] if highs else 0),
        "low": round2(lows[-1] if lows else 0),
        "amount": 0.0,
        "change_pct": pct_change(latest, prev_close),
        "data_source": "Yahoo Finance chart API",
    }


def fetch_global_quotes(symbols: list[str], market: str, api_keys: dict[str, str]) -> tuple[dict[str, dict[str, Any]], dict[str, Any]]:
    twelve_quotes, health = fetch_twelve_data_quotes(symbols, market, api_keys.get("twelve_data", ""))
    if twelve_quotes:
        return twelve_quotes, health
    if market == "US" and api_keys.get("alpha_vantage"):
        quotes: dict[str, dict[str, Any]] = {}
        alpha_health = {"source": "Alpha Vantage", "ok": True, "message": ""}
        for symbol in symbols[:5]:
            try:
                quote = fetch_alpha_quote(symbol, api_keys["alpha_vantage"])
            except Exception as exc:
                alpha_health.update({"ok": False, "message": str(exc)})
                continue
            if quote:
                quotes[symbol] = quote
        if quotes:
            return quotes, alpha_health
    yahoo_quotes: dict[str, dict[str, Any]] = {}
    yahoo_health = {"source": "Yahoo Finance chart API", "ok": True, "message": ""}
    for symbol in symbols:
        try:
            quote = fetch_yahoo_quote(symbol, market)
        except Exception as exc:
            yahoo_health.update({"ok": False, "message": str(exc)})
            continue
        if quote:
            yahoo_quotes[symbol] = quote
    if yahoo_quotes:
        if health.get("message"):
            yahoo_health["message"] = f"Primary source unavailable: {health.get('message')}"
        return yahoo_quotes, yahoo_health
    return {}, yahoo_health if yahoo_health.get("message") else health


def fetch_news_and_macro(api_keys: dict[str, str]) -> dict[str, Any]:
    headlines: list[dict[str, str]] = []
    data_health: list[dict[str, Any]] = []
    news_key = api_keys.get("news_api", "")
    if news_key:
        query = urllib.parse.urlencode(
            {
                "q": "China A-share OR Hong Kong stocks OR Nasdaq OR AI chips OR Federal Reserve",
                "language": "en",
                "pageSize": 6,
                "sortBy": "publishedAt",
                "apiKey": news_key,
            }
        )
        try:
            data = fetch_json_url(f"https://newsapi.org/v2/everything?{query}", timeout=8)
            for article in (data.get("articles") or [])[:6]:
                title = str(article.get("title") or "").strip()
                if title:
                    headlines.append(
                        {
                            "title": title,
                            "source": ((article.get("source") or {}).get("name")) or "NewsAPI",
                            "url": article.get("url") or "",
                        }
                    )
            data_health.append({"source": "NewsAPI", "ok": True, "message": ""})
        except Exception as exc:
            data_health.append({"source": "NewsAPI", "ok": False, "message": str(exc)})
    else:
        data_health.append({"source": "NewsAPI", "ok": False, "message": "NEWS_API_KEY is not configured"})

    macro: list[dict[str, Any]] = []
    fred_key = api_keys.get("fred", "")
    if fred_key:
        for series_id, label in [("DGS10", "美国10年期国债收益率"), ("DEXCHUS", "美元兑人民币")]:
            query = urllib.parse.urlencode(
                {
                    "series_id": series_id,
                    "api_key": fred_key,
                    "file_type": "json",
                    "sort_order": "desc",
                    "limit": 1,
                }
            )
            try:
                data = fetch_json_url(f"https://api.stlouisfed.org/fred/series/observations?{query}", timeout=8)
                obs = (data.get("observations") or [{}])[0]
                macro.append({"name": label, "value": obs.get("value"), "date": obs.get("date"), "source": "FRED"})
            except Exception as exc:
                data_health.append({"source": f"FRED:{series_id}", "ok": False, "message": str(exc)})
    else:
        data_health.append({"source": "FRED", "ok": False, "message": "FRED_API_KEY is not configured"})

    return {"headlines": headlines, "macro": macro, "data_health": data_health}


def collect_market_quotes(config: dict[str, Any], previous_state: dict[str, Any]) -> dict[str, Any]:
    watchlists = config.get("watchlists") or {}
    api_keys = config.get("api_keys") or {}
    health: list[dict[str, Any]] = []
    quotes_by_market: dict[str, dict[str, Any]] = {}

    previous_quotes: dict[str, dict[str, Any]] = {}
    for pos in previous_state.get("positions") or []:
        symbol = str(pos.get("symbol") or "")
        if symbol:
            previous_quotes[symbol] = {
                "symbol": symbol,
                "name": pos.get("name") or symbol,
                "market": pos.get("market") or "A",
                "latest": round2(pos.get("latest_price") or pos.get("cost_price")),
                "prev_close": round2(pos.get("prev_close") or pos.get("latest_price") or pos.get("cost_price")),
                "change_pct": round2(pos.get("today_pnl_pct") or 0),
                "data_source": "previous_state_fallback",
            }

    for market, items in watchlists.items():
        symbols = [str(item.get("symbol") or "") for item in items if item.get("symbol")]
        if market == "A":
            quotes, source_health = fetch_a_share_quotes(symbols)
        else:
            quotes, source_health = fetch_global_quotes(symbols, market, api_keys)
        health.append({"market": market, **source_health})
        merged = dict(previous_quotes)
        merged.update(quotes)
        quotes_by_market[market] = {
            symbol: quote
            for symbol, quote in merged.items()
            if quote.get("market") == market or symbol in symbols
        }

    external = fetch_news_and_macro(api_keys)
    health.extend(external.get("data_health") or [])
    return {
        "quotes": quotes_by_market,
        "headlines": external.get("headlines") or [],
        "macro": external.get("macro") or [],
        "data_health": health,
    }
