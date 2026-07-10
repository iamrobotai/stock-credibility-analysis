# -*- coding: utf-8 -*-
"""
preview_service.py — 预览/图表/技术指标 数据组装
================================================
将 web 层所需的「展示数据」从路由中抽离，统一在此拼装，
返回纯 dict（不依赖 Flask 对象），便于测试与复用。
"""
import os
import json
import glob
from pathlib import Path
from datetime import datetime
from typing import List

from common.config import DATA_DIR, OUTPUT_DIR


def build_preview(code: str) -> dict:
    """组装单股结构化预览数据（原 /api/preview 逻辑）。"""
    raw_path = DATA_DIR / f"{code}_raw.json"
    scored_path = DATA_DIR / f"{code}_scored.json"
    llm_path = DATA_DIR / f"{code}_llm.json"

    if not raw_path.exists():
        return {"ok": False, "error": f"无 {code} 的数据，请先运行分析"}

    raw = json.load(open(raw_path, encoding="utf-8"))
    scored = json.load(open(scored_path, encoding="utf-8")) if scored_path.exists() else {"posts": [], "segments": []}
    llm_data = json.load(open(llm_path, encoding="utf-8")) if llm_path.exists() else {}

    kline = raw.get("kline", [])
    segments = scored.get("segments", [])
    posts = scored.get("posts", [])
    financials = raw.get("financials", [])
    news = raw.get("news", [])
    reports = raw.get("reports", [])

    kline_summary = {}
    if kline:
        last = kline[-1]
        first = kline[0]
        total_ret = (last["close"] - first["close"]) / first["close"] * 100
        highs = [b["high"] for b in kline]
        lows = [b["low"] for b in kline]
        big_days = 0
        for i in range(1, len(kline)):
            prev = kline[i - 1]["close"]
            curr = kline[i]["close"]
            if prev > 0 and abs((curr - prev) / prev * 100) >= 5:
                big_days += 1
        kline_summary = {
            "start_date": first["date"], "end_date": last["date"],
            "total_bars": len(kline), "total_return": round(total_ret, 1),
            "max_high": round(max(highs), 2), "min_low": round(min(lows), 2),
            "last_close": round(last["close"], 2),
            "big_move_days": big_days,
        }

    by_type = {}
    for p in posts:
        t = p.get("source_type", "?")
        by_type.setdefault(t, []).append(p.get("avg_d", 0))
    source_avg = {t: round(sum(s) / len(s), 2) for t, s in by_type.items()}

    ads = [p for p in posts if p.get("D8", {}).get("is_ad")]

    llm_analysis = None
    if llm_data.get("success") and llm_data.get("analysis"):
        llm_analysis = llm_data["analysis"]
        llm_analysis["stats"] = llm_data.get("stats", {})

    return {
        "ok": True,
        "data": {
            "code": code,
            "name": raw.get("name", code),
            "stock_url": raw.get("stock_url", ""),
            "guba_url": raw.get("guba_url", ""),
            "kline_summary": kline_summary,
            "segments": segments,
            "posts": posts[:50],
            "posts_total": len(posts),
            "source_avg": source_avg,
            "ads": ads[:10],
            "ads_total": len(ads),
            "news": news[:15],
            "reports": reports[:10],
            "financials": financials[:15],
            "llm": llm_analysis,
            "has_chart": (DATA_DIR / f"{code}_chart.png").exists(),
            "credibility": _load_credibility(code),
        }
    }


def _load_credibility(code: str) -> dict | None:
    """附加量化多周期 × 综合可信度融合结果（M7）。

    优先读取已持久化的 scored.json 中的 credibility 字段；
    缺失则实时计算（兜底）。失败返回 None，不影响主预览。
    """
    try:
        sp = DATA_DIR / f"{code}_scored.json"
        if sp.exists():
            d = json.load(open(sp, encoding="utf-8"))
            if isinstance(d.get("credibility"), dict):
                return d["credibility"]
        # 兜底实时计算
        from credibility_service import analyze as cred_analyze
        r = cred_analyze(code)
        return r if r.get("ok") else None
    except Exception:
        return None


def build_kline(code: str) -> dict:
    """返回完整 K 线序列 + 分段，供前端交互式图表实时标注使用。

    出参:
        {"ok": True, "code":..., "kline":[{date,open,high,low,close,volume}],
         "segments":[{id,start_date,end_date,...}]}
    """
    raw_path = DATA_DIR / f"{code}_raw.json"
    seg_path = DATA_DIR / f"{code}_segments.json"
    if not raw_path.exists():
        return {"ok": False, "error": f"无 {code} 的 K 线数据，请先运行分析"}
    raw = json.load(open(raw_path, encoding="utf-8"))
    kline = raw.get("kline", [])
    if not kline:
        return {"ok": False, "error": "K 线为空"}
    clean = []
    for b in kline:
        clean.append({
            "date": b.get("date", ""),
            "open": round(float(b.get("open", 0)), 2),
            "high": round(float(b.get("high", 0)), 2),
            "low": round(float(b.get("low", 0)), 2),
            "close": round(float(b.get("close", 0)), 2),
            "volume": float(b.get("volume", 0)),
        })
    segments = []
    if seg_path.exists():
        try:
            segments = json.load(open(seg_path, encoding="utf-8"))
        except Exception:
            segments = []
    return {"ok": True, "code": code, "name": raw.get("name", code),
            "kline": clean, "segments": segments}


def build_technical(code: str) -> dict:
    """组装技术指标与 K 线形态数据（原 /api/technical 逻辑）。"""
    raw_path = DATA_DIR / f"{code}_raw.json"
    if not raw_path.exists():
        return {"ok": False, "error": "无数据"}
    raw = json.load(open(raw_path, encoding="utf-8"))
    kline = raw.get("kline", [])
    if not kline:
        return {"ok": False, "error": "无K线数据"}
    from technical import (
        compute_macd, compute_kdj, compute_rsi, compute_boll,
        compute_cci, compute_wr, compute_atr, compute_technical_score,
        detect_patterns,
    )
    closes = [b["close"] for b in kline]
    highs = [b["high"] for b in kline]
    lows = [b["low"] for b in kline]

    tail = min(100, len(kline))
    kline_tail = kline[-tail:]
    closes_tail = closes[-tail:]

    indicators = {
        "MACD": compute_macd(closes_tail),
        "KDJ": compute_kdj(highs[-tail:], lows[-tail:], closes_tail),
        "RSI": compute_rsi(closes_tail),
        "BOLL": compute_boll(closes_tail),
        "CCI": compute_cci(highs[-tail:], lows[-tail:], closes_tail) if len(closes_tail) >= 14 else None,
        "WR": compute_wr(highs[-tail:], lows[-tail:], closes_tail) if len(closes_tail) >= 10 else None,
        "ATR": compute_atr(highs[-tail:], lows[-tail:], closes_tail) if len(closes_tail) >= 14 else None,
    }
    patterns = detect_patterns(kline_tail)
    recent_patterns = [p for p in patterns if p["index"] >= len(kline_tail) - 20]
    d9 = compute_technical_score(kline_tail)

    return {
        "ok": True,
        "data": {
            "indicators": indicators,
            "patterns_total": len(patterns),
            "recent_patterns": recent_patterns[-15:],
            "d9_score": d9,
        }
    }


def render_chart(code: str) -> dict:
    """确保价格曲线 PNG 存在并返回访问路径（按需生成）。"""
    chart_path = DATA_DIR / f"{code}_chart.png"
    if not chart_path.exists():
        raw_path = DATA_DIR / f"{code}_raw.json"
        seg_path = DATA_DIR / f"{code}_segments.json"
        if raw_path.exists():
            raw = json.load(open(raw_path, encoding="utf-8"))
            segs = json.load(open(seg_path, encoding="utf-8")) if seg_path.exists() else []
            try:
                from chart_gen import gen_stock_chart
                gen_stock_chart(code, raw.get("kline", []), segs, outdir=str(DATA_DIR))
            except Exception:
                pass
    if chart_path.exists():
        return {"ok": True, "chart": f"{code}_chart.png"}
    return {"ok": False, "error": "Chart not found"}


def build_industry_chart(stock_codes: List[str], industry_name: str) -> dict:
    """行业多股走势叠加图（原 /api/industry/chart 逻辑）。"""
    if not stock_codes:
        return {"ok": False, "error": "请提供股票代码列表"}
    stocks_data = []
    for code in stock_codes:
        raw_path = DATA_DIR / f"{code}_raw.json"
        if raw_path.exists():
            raw = json.load(open(raw_path, encoding="utf-8"))
            stocks_data.append({
                "code": code,
                "name": raw.get("name", code),
                "kline": raw.get("kline", []),
            })
    if not stocks_data:
        return {"ok": False, "error": "无可用数据，请先运行分析"}
    from chart_gen import gen_industry_chart
    path = gen_industry_chart(stocks_data, industry_name, outdir=str(DATA_DIR))
    if path:
        safe_name = industry_name.replace("/", "_").replace(" ", "")
        return {"ok": True, "chart": f"industry_{safe_name}_chart.png"}
    return {"ok": False, "error": "图表生成失败"}


def build_industry_preview() -> dict:
    """行业对比预览：返回所有已分析股票列表（原 /api/industry/preview）。"""
    raw_files = sorted(DATA_DIR.glob("*_raw.json"), key=os.path.getmtime, reverse=True)
    stocks = []
    for f in raw_files[:200]:
        code = f.stem.replace("_raw", "")
        try:
            raw = json.load(open(f, encoding="utf-8"))
            kline = raw.get("kline", [])
            if kline:
                stocks.append({
                    "code": code,
                    "name": raw.get("name", code),
                    "last_close": kline[-1]["close"],
                    "total_return": round((kline[-1]["close"] - kline[0]["close"]) / kline[0]["close"] * 100, 1),
                })
        except Exception:
            continue
    return {"ok": True, "stocks": stocks}


__all__ = [
    "build_preview", "build_kline", "build_technical",
    "render_chart", "build_industry_chart", "build_industry_preview",
]
