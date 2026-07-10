# -*- coding: utf-8 -*-
"""
credibility_service.py — 量化多周期 × 可信度评估 融合编排
====================================================
单一入口：读取个股原始行情(kline) + 既有评分(scored.json)，
调用 TimeframeAnalyzer（多周期动态指标）与 CredibilityIntegrator
（融合 D1–D9 与量化多周期）产出综合可信度。

依赖方向：services → domain(quant/timeframe, core/credibility_integrator)
              → common.interfaces / common.registry
web 层只通过本服务获取结果，不直接依赖具体实现。
"""

import os
import json
from pathlib import Path

from common.config import DATA_DIR
from common.registry import resolve

# 确保依赖注册表已就绪（幂等；测试 / 预览路径下 __main__ 未必执行）
try:
    from common.registry import bootstrap
    bootstrap()
except Exception:
    pass


def _load_json(path: Path) -> dict | None:
    if not path.exists():
        return None
    try:
        return json.load(open(path, encoding="utf-8"))
    except Exception:
        return None


def _build_credibility_input(scored: dict | None) -> dict:
    """从 scored.json 抽取 D1–D9 内容可信度输入（0-1 量纲）。"""
    if not scored:
        return {"content_avg": 0.5, "d9": None, "ad_flag": False,
                "post_count": 0, "avg_d_by_source": {}}
    posts = scored.get("posts", [])
    vals = [p.get("avg_d") for p in posts
            if isinstance(p.get("avg_d"), (int, float))]
    content_avg = round(float(sum(vals) / len(vals)), 4) if vals else 0.5
    ad_flag = any(p.get("D8", {}).get("is_ad") for p in posts)
    # 各来源 D1-D8 均值（展示用）
    by_src = {}
    for p in posts:
        t = p.get("source_type", "?")
        by_src.setdefault(t, []).append(p.get("avg_d", 0))
    avg_by_source = {t: round(sum(s) / len(s), 3) for t, s in by_src.items()}
    d9 = scored.get("D9")
    d9 = float(d9["score"]) if isinstance(d9, dict) and "score" in d9 else (
        float(d9) if isinstance(d9, (int, float)) else None)
    return {"content_avg": content_avg, "d9": d9, "ad_flag": ad_flag,
            "post_count": len(posts), "avg_d_by_source": avg_by_source}


def analyze(code: str, kline: list | None = None) -> dict:
    """多周期量化分析 + 综合可信度融合。

    返回：
        {"ok": True, "code", "name",
         "timeframe_analysis": <TimeframeAnalyzer.analyze 输出>,
         "credibility_input": <D1–D9 抽取>,
         "comprehensive": <CredibilityIntegrator.integrate 输出>}
     或 {"ok": False, "error": ...}
    """
    raw = _load_json(DATA_DIR / f"{code}_raw.json")
    if raw is None:
        return {"ok": False, "error": f"无 {code} 数据，请先运行分析"}
    kline = kline if kline is not None else raw.get("kline", [])
    if not kline:
        return {"ok": False, "error": "K 线为空"}

    try:
        analyzer = resolve("TimeframeAnalyzer")
        integrator = resolve("CredibilityIntegrator")
    except Exception as e:
        return {"ok": False, "error": f"依赖未注册: {e}"}

    tf_analysis = analyzer.analyze(kline)
    scored = _load_json(DATA_DIR / f"{code}_scored.json")
    cred_in = _build_credibility_input(scored)
    # 若 scored 未含 D9，用 technical 现算补足（保证融合完整）
    if cred_in["d9"] is None:
        try:
            from technical import compute_technical_score
            d9 = compute_technical_score(kline[-100:])
            cred_in["d9"] = float(d9.get("score"))
        except Exception:
            cred_in["d9"] = None
    comprehensive = integrator.integrate(cred_in, tf_analysis)

    return {
        "ok": True,
        "code": code,
        "name": raw.get("name", code),
        "timeframe_analysis": tf_analysis,
        "credibility_input": cred_in,
        "comprehensive": comprehensive,
    }


def persist(code: str, ext: dict | None = None) -> bool:
    """将量化多周期(D10_quant)与综合可信度(comprehensive_credibility)
    持久化进 {code}_scored.json（供 docx/静态站点/预览消费）。"""
    ext = ext or analyze(code)
    if not ext.get("ok"):
        return False
    sp = DATA_DIR / f"{code}_scored.json"
    if not sp.exists():
        return False
    try:
        data = json.load(open(sp, encoding="utf-8"))
        data["D10_quant"] = ext["timeframe_analysis"]["composite_quant_score"]
        data["credibility"] = {
            "timeframe_analysis": ext["timeframe_analysis"],
            "comprehensive": ext["comprehensive"],
        }
        json.dump(data, open(sp, "w", encoding="utf-8"),
                  ensure_ascii=False, indent=2)
        return True
    except Exception:
        return False


__all__ = ["analyze", "persist", "_build_credibility_input"]
