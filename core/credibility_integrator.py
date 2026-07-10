# -*- coding: utf-8 -*-
"""
core/credibility_integrator.py — 可信度融合器（量化 ↔ 可信度评估体系）
====================================================================
将既有「可信度评估体系」（D1–D8 内容评分 + D9 技术信号可信度）
与「量化多周期分析」（quant/timeframe.py 的输出，quant contract）
融合为统一的 **综合可信度评分**。

融合逻辑（可解释、可扩展）：
    1) 内容可信度 content_credibility (0-100)
        由 D1–D8 均值（内容质量）与 D9（技术信号质量）加权，
        命中广告/软文 (ad_flag) 时整体打折（默认 ×0.7）。
    2) 量化支持度 quant_support (0-100)
        直接取量化多周期 composite_quant_score（月/周/日加权趋势态势）。
    3) 共振项 resonance
        当「内容可信」与「价格趋势」同向（皆好 / 皆差）时为正，
        当内容被高评级但价格走坏（疑似拉高出货）时为负，体现一致性校验。
    4) 跨周期对齐项 alignment
        日周月共振·多头 → +；共振·空头 → −；分化 → 0。
    5) 综合 = 0.55·content + 0.35·quant + 15·resonance + alignment_mod
        并裁剪到 1–99。

输入契约 (credibility)：
    {"content_avg":0-1, "d9":0-1, "ad_flag":bool, "post_count":int}
输入契约 (quant)：
    MultiTimeframeAnalyzer.analyze() 输出：
    {"timeframes":{...}, "alignment":str, "composite_quant_score":0-100}

输出契约 (comprehensive contract)：
    {"comprehensive_score":0-100, "grade":str, "explanation":str,
     "components":{...}, "timeframe_detail":{...}}

实现 common.interfaces.CredibilityIntegrator，可由 registry 替换。
"""

from __future__ import annotations

import numpy as np

from common.interfaces import CredibilityIntegrator as _CI

__all__ = ["WeightedIntegrator", "GRADE_HIGH", "GRADE_MID", "GRADE_LOW",
            "W_CONTENT", "W_QUANT", "W_RESONANCE", "ALIGN_BONUS"]

# 综合评分权重（文档化，便于调参与审计）
W_CONTENT = 0.55      # 内容 + 技术信号可信度
W_QUANT = 0.35        # 量化多周期趋势支持度
W_RESONANCE = 15.0    # 共振项系数（resonance∈[-1,1] → ±15）
ALIGN_BONUS = 5.0     # 跨周期共振·多头 / 空头 修正

GRADE_HIGH = "高可信"
GRADE_MID = "中可信"
GRADE_LOW = "低可信"

# 内容可信度内部权重
W_INNER_CONTENT = 0.80   # D1–D8 内容质量
W_INNER_TECH = 0.20      # D9 技术信号质量
AD_PENALTY = 0.70          # 命中广告时内容分打折


class WeightedIntegrator(_CI):
    """加权融合默认实现。"""

    def _content_score(self, credibility: dict) -> float:
        content_avg = float(credibility.get("content_avg") or 0.0)   # 0-1
        d9 = credibility.get("d9")
        d9 = float(d9) if isinstance(d9, (int, float)) else None      # 0-1
        if d9 is not None:
            inner = W_INNER_CONTENT * content_avg + W_INNER_TECH * d9
        else:
            inner = content_avg  # 无 D9 时退化为纯内容
        content = inner * 100.0
        if credibility.get("ad_flag"):
            content *= AD_PENALTY
        return float(np.clip(content, 1.0, 99.0))

    def integrate(self, credibility: dict, quant: dict) -> dict:
        content = self._content_score(credibility)
        quant_support = float(quant.get("composite_quant_score") or 50.0)

        # 共振项：同向为正、反向为负
        c_n = (content - 50.0) / 50.0
        q_n = (quant_support - 50.0) / 50.0
        resonance = float(np.clip(c_n * q_n, -1.0, 1.0))

        # 跨周期对齐修正
        align = quant.get("alignment", "周期分化")
        if "共振·多头" in align:
            align_mod = ALIGN_BONUS
        elif "共振·空头" in align:
            align_mod = -ALIGN_BONUS
        else:
            align_mod = 0.0

        comprehensive = (W_CONTENT * content
                        + W_QUANT * quant_support
                        + W_RESONANCE * resonance
                        + align_mod)
        comprehensive = float(np.clip(comprehensive, 1.0, 99.0))

        grade = (GRADE_HIGH if comprehensive >= 70.0
                 else GRADE_MID if comprehensive >= 45.0
                 else GRADE_LOW)

        # 解释文本
        tf = quant.get("timeframes", {})
        tf_txt = "、".join(
            f"{tf[t].get('label', t)}={tf[t].get('signal', '?')}"
            for t in ("day", "week", "month") if t in tf)
        exp = (f"综合可信度 {comprehensive:.0f}/100（{grade}）。"
               f"内容可信度 {content:.0f}（D1–D9，"
               + ("含广告折扣" if credibility.get("ad_flag") else "无广告折扣") + "）；"
               f"量化多周期支持度 {quant_support:.0f}（{tf_txt or '无'}）；"
               f"周期共振：{align}。"
               + ("⚠️ 内容与价格趋势背离，需警惕叙述与走势不一致。"
                  if resonance < -0.05 else ""))
        if align_mod > 0:
            exp += "多周期共振偏多，趋势可信度增强。"
        elif align_mod < 0:
            exp += "多周期共振偏空，趋势可信度削弱。"

        return {
            "comprehensive_score": round(comprehensive, 1),
            "grade": grade,
            "explanation": exp,
            "components": {
                "content_credibility": round(content, 1),
                "quant_support": round(quant_support, 1),
                "resonance": round(resonance, 3),
                "alignment_mod": align_mod,
                "weights": {
                    "content": W_CONTENT, "quant": W_QUANT,
                    "resonance": W_RESONANCE, "alignment": ALIGN_BONUS,
                },
            },
            "timeframe_detail": {
                t: {
                    "label": tf[t].get("label", t),
                    "signal": tf[t].get("signal"),
                    "score": tf[t].get("score"),
                    "ma_trend": tf[t].get("ma_trend"),
                    "volatility_ann_pct": (tf[t].get("volatility") or {}).get("ann_pct"),
                } for t in ("day", "week", "month") if t in tf
            },
        }


__all__ = ["WeightedIntegrator", "GRADE_HIGH", "GRADE_MID", "GRADE_LOW",
            "W_CONTENT", "W_QUANT", "W_RESONANCE", "ALIGN_BONUS"]
