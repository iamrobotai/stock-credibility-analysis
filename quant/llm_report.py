# -*- coding: utf-8 -*-
"""
quant/llm_report.py — M4 LLM 自然语言归因
==========================================
输入 engine.run_stock() 的结构化结果，构造精炼 prompt，调用 AI 层
(ai/ai_provider.call_ai) 生成三维自然语言归因：
  维度一 数据导向 / 维度二 公司前景 / 维度三「赚了谁的钱」+ 综合摘要。

设计原则：
  - 面向接口：只依赖 ai_provider.call_ai(messages, provider) -> (text, stats)。
  - 优雅降级：AI 未配置 / 无本地服务 / 调用失败 / JSON 解析失败时，
    回退为基于既有 thesis 与量化指标拼装的模板文本，`degraded=True`。
  - 所有 AI 生成文本均带「疑似推断，非投资建议」口径，与全系统一致。

返回结构（稳定契约，供 service / web / word 复用）：
  {
    "available": bool,          # 是否成功产出（含降级也为 True，除非致命错误）
    "degraded": bool,           # 是否走了模板降级
    "provider": str,            # 实际使用的提供商 id（降级为 "template"）
    "narrative": {
        "dim1": str, "dim2": str, "dim3": str, "summary": str
    },
    "stats": dict,              # AI 调用统计（降级为空）
    "error": str,               # 仅致命错误时出现
  }
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

# 兼容既有目录约定：ai 模块在 ai/ 子目录，通过 sys.path 注入
_ROOT = Path(__file__).resolve().parents[1]
for _sub in ("ai",):
    _p = _ROOT / _sub
    if _p.exists() and str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

__all__ = ["generate", "build_prompt"]

_DISCLAIMER = "以上为基于公开数据的疑似推断，非投资建议。"


# --------------------------------------------------------------------------- #
#  数值摘要抽取（把 run_stock 结果压缩成 prompt 友好的紧凑字典）
# --------------------------------------------------------------------------- #
def _digest(res: dict) -> dict:
    td = res.get("three_dimensions", {}) or {}
    d1 = td.get("data_driven", {}) or {}
    d2 = td.get("company_outlook", {}) or {}
    d3 = td.get("who_profits", {}) or {}
    qf = res.get("quant_fund", {}) or {}
    risk = (res.get("risk") or {}).get("strategy") or {}
    pos = res.get("position", {}) or {}
    best = d1.get("best_strategy", {}) or {}
    dims = res.get("data_dimensions", {}) or {}

    def _pct(v):
        return None if v is None else round(float(v) * 100.0, 2)

    return {
        "code": res.get("code"),
        "name": res.get("name"),
        "period": f'{res.get("date_start","")}~{res.get("date_end","")}',
        "n_days": res.get("n_days"),
        "best_strategy": {
            "label": best.get("label"),
            "sharpe": best.get("sharpe"),
            "total_return_pct": _pct(best.get("total_return")),
            "max_drawdown_pct": _pct(best.get("max_drawdown")),
        },
        "quant_score": qf.get("quant_score"),
        "retail_score": qf.get("retail_score"),
        "is_retail_dominated": qf.get("is_retail_dominated"),
        "suspected_type": qf.get("suspected_type"),
        "extra_signals": qf.get("extra_signals") or {},
        "risk_grade": risk.get("risk_grade"),
        "ann_vol_pct": _pct(risk.get("ann_vol")),
        "var_95_pct": _pct(risk.get("var_95")),
        "max_drawdown_pct": _pct(risk.get("max_drawdown")),
        "holder_mix": pos.get("holder_mix"),
        "who_is_positioned": pos.get("who_is_positioned"),
        "company_outlook": {
            "net_profit_growth_pct": _pct(d2.get("net_profit_growth")),
            "report_rating_avg": d2.get("report_rating_avg"),
            "report_count": d2.get("report_count"),
            "news_sentiment": d2.get("news_sentiment"),
            "news_count": d2.get("news_count"),
        },
        "who_profits_subject": d3.get("subject"),
        "who_profits_thesis": d3.get("thesis"),
        "data_dimensions_available": sorted(dims.keys()),
    }


# --------------------------------------------------------------------------- #
#  Prompt 构造
# --------------------------------------------------------------------------- #
def build_prompt(res: dict) -> list:
    dg = _digest(res)
    system = (
        "你是严谨的 A 股量化研究助理。基于给定的结构化量化分析数据，"
        "用中文撰写客观、专业、可读的自然语言归因。"
        "严格遵守：①不得编造数据中不存在的数字；②所有判断为疑似推断，"
        "非投资建议；③口吻中性克制，避免夸张与营销词。"
        "必须只输出 JSON 对象，键为 dim1、dim2、dim3、summary，值均为中文字符串。"
        "dim1=数据导向（策略绩效+量化资金识别+风控）；"
        "dim2=公司前景（业绩增速/研报评级/新闻情绪）；"
        "dim3=赚了谁的钱（资金主体定位+持有者结构）；"
        "summary=三段综合的一段话结论。每段 80~160 字。"
    )
    user = (
        "以下是某只 A 股的量化分析结构化数据（数值单位：pct 为百分比，"
        "score 为 0-100 分，sharpe 为夏普比率）：\n"
        + json.dumps(dg, ensure_ascii=False, indent=2)
        + "\n\n请据此生成 JSON 归因。"
    )
    return [
        {"role": "system", "content": system},
        {"role": "user", "content": user},
    ]


# --------------------------------------------------------------------------- #
#  模板降级（无 AI 时的确定性回退）
# --------------------------------------------------------------------------- #
def _template_narrative(res: dict) -> dict:
    dg = _digest(res)
    bs = dg["best_strategy"]
    d2 = dg["company_outlook"]

    def _fmt(v, suffix=""):
        return "—" if v is None else f"{v}{suffix}"

    dim1 = (
        f"最优策略「{_fmt(bs['label'])}」区间收益 {_fmt(bs['total_return_pct'],'%')}，"
        f"夏普 {_fmt(bs['sharpe'])}，最大回撤 {_fmt(bs['max_drawdown_pct'],'%')}；"
        f"量化资金评分 {_fmt(dg['quant_score'])}，散户主导评分 {_fmt(dg['retail_score'])}，"
        f"疑似类型「{_fmt(dg['suspected_type'])}」；风险等级 {_fmt(dg['risk_grade'])}，"
        f"年化波动 {_fmt(dg['ann_vol_pct'],'%')}。{_DISCLAIMER}"
    )
    dim2 = (
        f"归母净利润同比 {_fmt(d2['net_profit_growth_pct'],'%')}，"
        f"研报评级均值 {_fmt(d2['report_rating_avg'])}（{_fmt(d2['report_count'])} 份），"
        f"新闻情绪 {_fmt(d2['news_sentiment'])}（{_fmt(d2['news_count'])} 条）。"
        f"以上为公司基本面与市场预期的量化侧影，需结合定性研究综合判断。{_DISCLAIMER}"
    )
    dim3 = dg.get("who_profits_thesis") or (
        f"资金主体定位为「{_fmt(dg['who_profits_subject'])}」。{_DISCLAIMER}"
    )
    if _DISCLAIMER not in dim3:
        dim3 = dim3 + _DISCLAIMER
    summary = (
        f"综合来看，{dg.get('name','')}（{dg.get('code','')}）在样本区间内"
        f"呈现「{_fmt(dg['suspected_type'])}」资金特征，"
        f"资金主体倾向为「{_fmt(dg['who_profits_subject'])}」；"
        f"策略与风控指标见维度一，公司前景见维度二。{_DISCLAIMER}"
    )
    return {"dim1": dim1, "dim2": dim2, "dim3": dim3, "summary": summary}


def _parse_ai_json(text: str) -> dict | None:
    if not text:
        return None
    s = text.strip()
    # 去除可能的 ```json 包裹
    if s.startswith("```"):
        s = s.strip("`")
        if s.lower().startswith("json"):
            s = s[4:]
    # 截取首个 { 到末个 }
    l, r = s.find("{"), s.rfind("}")
    if l >= 0 and r > l:
        s = s[l:r + 1]
    try:
        obj = json.loads(s)
    except Exception:
        return None
    if not isinstance(obj, dict):
        return None
    out = {}
    for k in ("dim1", "dim2", "dim3", "summary"):
        v = obj.get(k)
        out[k] = str(v).strip() if v is not None else ""
    # 至少 3 段非空才算有效
    if sum(1 for k in ("dim1", "dim2", "dim3") if out[k]) < 3:
        return None
    return out


# --------------------------------------------------------------------------- #
#  主入口
# --------------------------------------------------------------------------- #
def generate(res: dict, provider: str | None = None,
             timeout: int = 90) -> dict:
    """
    生成三维 LLM 归因；失败自动降级为模板文本。

    provider: None=使用 ai_config 的 active_provider；否则指定 id。
    """
    if not isinstance(res, dict) or res.get("error"):
        return {
            "available": False, "degraded": True, "provider": "template",
            "narrative": {"dim1": "", "dim2": "", "dim3": "", "summary": ""},
            "stats": {}, "error": (res or {}).get("error", "无有效分析结果"),
        }

    # 尝试真实 AI
    try:
        import ai_provider as AP  # 通过 sys.path(ai/) 注入
    except Exception:
        AP = None

    if AP is not None:
        try:
            messages = build_prompt(res)
            text, stats = AP.call_ai(
                messages, provider=provider, format_json=True,
                temperature=0.3, max_tokens=900, timeout=timeout,
            )
            parsed = _parse_ai_json(text)
            if parsed:
                # 补充免责声明
                for k in ("dim1", "dim2", "dim3", "summary"):
                    if parsed[k] and _DISCLAIMER not in parsed[k]:
                        parsed[k] = parsed[k].rstrip("。") + "。" + _DISCLAIMER
                return {
                    "available": True, "degraded": False,
                    "provider": stats.get("provider", provider or "ai"),
                    "narrative": parsed, "stats": stats, "error": "",
                }
        except Exception as e:
            # 落入降级
            return {
                "available": True, "degraded": True, "provider": "template",
                "narrative": _template_narrative(res), "stats": {},
                "error": f"AI 调用失败已降级: {str(e)[:160]}",
            }

    # AI 不可用 → 模板降级
    return {
        "available": True, "degraded": True, "provider": "template",
        "narrative": _template_narrative(res), "stats": {},
        "error": "AI 层不可用，已使用模板归因" if AP is None else "AI 未产出有效结果，已降级",
    }
