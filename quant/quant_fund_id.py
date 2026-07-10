"""
quant/quant_fund_id.py — 量化资金识别 + 散户主导判定
========================================================
基于现有 raw.json 三类可消费维度,对个股做"疑似量化/机构资金介入"推断,
并识别"是否为散户主导交易"。

输入维度:
  1) 龙虎榜 lhb       机构席位净买、上榜解读(机构买入/游资/散户)、上榜后表现
  2) 资金流 sina_fund  超大单+大单累计净买(inst_cum)、主力净流
  3) 行情 kline        价量模式:高换手 + 低回撤(疑似量化做市/高频特征)

输出:
  quant_score      0-100(越高越疑似量化/机构资金主导)
  retail_score     0-100(越高越疑似散户主导)
  is_retail_dominated  bool
  suspected_type   高频做市/中低频趋势/指数增强·市场中性/统计套利(疑似)/机构量化混合/无明显量化特征
  evidence         推断依据列表
  sub_scores       各子项评分(透明可解释)

重要:所有结论为"疑似/推测"级别,基于公开量价数据的启发式推断,
不构成任何确定性归因或投资建议。
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from . import features as F

__all__ = ["identify"]

# 评分权重
W = {"seat": 0.30, "flow": 0.30, "pattern": 0.25, "persist": 0.15}


def _clip(x, lo=0.0, hi=100.0):
    return float(min(max(x, lo), hi))


def _num(x):
    if x is None:
        return np.nan
    if isinstance(x, (int, float)):
        return float(x)
    s = str(x).strip().replace(",", "").replace("%", "")
    if s in ("", "-", "--", "None", "nan", "NaN"):
        return np.nan
    try:
        return float(s)
    except Exception:
        return np.nan


def _parse_lhb(raw: dict):
    """解析龙虎榜,返回聚合特征。"""
    out = {
        "count": 0, "net": 0.0, "inst_buy": False, "retail_flag": False,
        "post_mean": 0.0, "post_n": 0,
    }
    for r in (raw.get("lhb") or []):
        if not isinstance(r, dict):
            continue
        out["count"] += 1
        nv = _num(r.get("龙虎榜净买额"))
        out["net"] += 0.0 if np.isnan(nv) else nv
        note = str(r.get("解读") or "")
        if "机构买入" in note or "机构买" in note or "机构专用" in note:
            out["inst_buy"] = True
        if "游资" in note or "散户" in note or "拉萨" in note:
            out["retail_flag"] = True
        for k in ("上榜后1日", "上榜后2日", "上榜后5日", "上榜后10日"):
            v = _num(r.get(k))
            if not np.isnan(v):
                out["post_mean"] += v
                out["post_n"] += 1
    if out["post_n"]:
        out["post_mean"] /= out["post_n"]
    return out


# --------------------------------------------------------------------------- #
#  M3.1 新数据维度解析与微调
# --------------------------------------------------------------------------- #
def _parse_extra(raw: dict) -> dict:
    """解析北向/两融/股东户数三类新维度, 仅抽取数值信号。"""
    out = {"north_fund": {}, "margin": {}, "holder_num": {}}
    n = raw.get("north_fund") or {}
    if isinstance(n, dict) and n.get("available"):
        out["north_fund"] = {
            "available": True,
            "chg_1d_pct": _num(n.get("chg_1d_pct")),
            "chg_5d_pct": _num(n.get("chg_5d_pct")),
            "chg_10d_pct": _num(n.get("chg_10d_pct")),
            "hold_pct": _num(n.get("hold_pct")),
        }
    m = raw.get("margin") or {}
    if isinstance(m, dict) and m.get("available"):
        out["margin"] = {
            "available": True,
            "fin_balance": _num(m.get("fin_balance")),
            "fin_balance_chg": _num(m.get("fin_balance_chg")),
        }
    h = raw.get("holder_num") or {}
    if isinstance(h, dict) and h.get("available"):
        out["holder_num"] = {
            "available": True,
            "change_pct": _num(h.get("change_pct")),
            "holder_count": _num(h.get("holder_count")),
        }
    return out

def _fold_extra(seat: float, flow: float, retail_flow: float, extra: dict):
    """将新维度信号折算为 seat / flow / retail_flow 的微调增量。

    规则(仅当数据 available 时生效, 否则完全不影响基线):
      - 北向 5 日增持  → 机构席位分 +, 散户分 -
      - 融资余额增长    → 杠杆资金(偏散户/游资) → 散户分 +
      - 股东户数下降    → 筹码集中(机构吸筹) → 机构分 +, 散户分 -
    """
    n = extra.get("north_fund", {})
    if n.get("available"):
        d5 = n.get("chg_5d_pct"); d1 = n.get("chg_1d_pct")
        d = d5 if not np.isnan(d5) else d1
        if not np.isnan(d):
            seat += 7.0 * np.sign(d) * min(abs(d) / 0.5, 1.0)
            if d > 0:
                retail_flow -= 4.0
    m = extra.get("margin", {})
    if m.get("available"):
        chg = m.get("fin_balance_chg"); bal = m.get("fin_balance") or 1.0
        if not np.isnan(chg) and abs(bal) > 1e-9:
            retail_flow += 6.0 * np.sign(chg) * min(abs(chg) / abs(bal) * 100.0, 1.0)
    h = extra.get("holder_num", {})
    if h.get("available"):
        d = h.get("change_pct")
        if not np.isnan(d):
            seat += -6.0 * np.sign(d) * min(abs(d) / 5.0, 1.0)
            if d < 0:
                retail_flow -= 3.0
    return seat, flow, retail_flow

def _extra_evidence(extra: dict) -> list:
    ev = []
    n = extra.get("north_fund", {})
    if n.get("available"):
        d5 = n.get("chg_5d_pct")
        ev.append(f"北向资金:持股占流通 {n.get('hold_pct','?')}%"
                  f"{', 5日增持' + format(d5,'.3f') + '%' if (isinstance(d5,(int,float)) and not np.isnan(d5) and d5>0) else (', 5日减持' + format(d5,'.3f') + '%' if isinstance(d5,(int,float)) and not np.isnan(d5) else '')}"
                  " → 机构/外资动向信号")
    m = extra.get("margin", {})
    if m.get("available"):
        ev.append(f"融资融券:融资余额 {m.get('fin_balance','?')} 万"
                  f"{', 余额增长' if (m.get('fin_balance_chg') or 0) > 0 else (', 余额下降' if (m.get('fin_balance_chg') or 0) < 0 else '')}"
                  " → 杠杆资金(偏散户/游资)方向")
    h = extra.get("holder_num", {})
    if h.get("available"):
        d = h.get("change_pct")
        ev.append(f"股东户数:{int(m.get('holder_count',0)) if isinstance(m.get('holder_count'),(int,float)) and not np.isnan(m.get('holder_count',float('nan'))) else '?'} 户"
                  f"{', 较上期' + format(d,'.2f') + '%(筹码集中)' if (isinstance(d,(int,float)) and not np.isnan(d) and d<0) else (', 较上期' + format(d,'.2f') + '%' if isinstance(d,(int,float)) and not np.isnan(d) else '')}"
                  " → 筹码集中度信号")
    if not (n.get("available") or m.get("available") or h.get("available")):
        ev.append("北向/两融/股东户数:当前 raw 未含(需 M3.1 采集), 维持基准推断")
    return ev

def identify(raw: dict, feat: pd.DataFrame | None = None) -> dict:
    code = raw.get("code", "")
    name = raw.get("name", "")

    if feat is None:
        feat = F.build_feature_frame(raw)

    lhb = _parse_lhb(raw)

    # ---- 资金流累计 ----
    inst_cum = 0.0
    main_cum = 0.0
    if not feat.empty and "inst_cum_net_cum" in feat.columns:
        inst_cum = float(feat["inst_cum_net_cum"].iloc[-1])
        main_cum = float(feat["main_cum"].iloc[-1]) if "main_cum" in feat.columns else 0.0
    # 用资金流窗口成交额归一,得到净流占比
    flow_window_amt = 0.0
    if not feat.empty and "amount" in feat.columns:
        flow_window_amt = float(feat["amount"].fillna(0).tail(10).sum())
    inst_net_pct = (inst_cum / flow_window_amt * 100.0) if flow_window_amt > 1e-9 else 0.0

    # ---- 价量模式:高换手 + 低回撤 ----
    turn_score = 0.0
    lowdd_score = 0.0
    min_dd = -1.0
    vol20 = 0.0
    mom60 = 0.0
    if not feat.empty:
        vr = feat["vol_ratio"].replace([np.inf, -np.inf], np.nan).dropna()
        if len(vr):
            turn = float(vr.tail(60).mean())
            turn_score = _clip(min(turn / 2.0, 1.0) * 100.0)
        if "drawdown" in feat.columns:
            min_dd = float(feat["drawdown"].min())
            lowdd_score = _clip((1.0 - abs(min_dd) / 0.30) * 100.0)
        if "vol20" in feat.columns:
            vol20 = float(feat["vol20"].tail(20).mean())
        if "mom60" in feat.columns:
            mom60 = float(feat["mom60"].iloc[-1]) if feat["mom60"].notna().any() else 0.0

    # =================== 子项评分 =================== #
    # A) 机构席位分
    if lhb["count"] == 0:
        seat = 40.0
    elif lhb["net"] > 0 and lhb["inst_buy"]:
        seat = 88.0
    elif lhb["net"] > 0:
        seat = 62.0
    elif lhb["net"] < 0:
        seat = 30.0
    else:
        seat = 45.0
    if lhb["retail_flag"]:
        seat = _clip(seat - 28.0)

    # B) 大资金净流分
    if flow_window_amt <= 1e-9:
        flow = 40.0
    elif inst_net_pct > 1.0:
        flow = 85.0
    elif inst_cum > 0:
        flow = 65.0
    elif inst_cum < 0:
        flow = 33.0
    else:
        flow = 50.0

    # C) 价量模式分(高频做市/日内均值回归特征)
    pattern = _clip(0.6 * turn_score + 0.4 * lowdd_score)

    # D) 持续性与胜率分
    if lhb["count"] == 0 or lhb["post_n"] == 0:
        persist = 50.0
    else:
        persist = _clip(50.0 + np.sign(lhb["post_mean"]) * min(abs(lhb["post_mean"]) * 120.0, 45.0))

    # =================== 散户主导分(先算, 供统一 fold) =================== #
    # 资金流视角:超大+大单净流出且主力净流出 → 散户/游资接盘
    if flow_window_amt <= 1e-9:
        flow_retail = 45.0
    elif inst_cum < 0 and main_cum < 0:
        flow_retail = 82.0
    elif inst_cum > 0:
        flow_retail = 30.0
    else:
        flow_retail = 52.0
    if lhb["retail_flag"]:
        flow_retail = _clip(flow_retail + 25.0)
    # 价量视角:极高换手 + 深回撤(追涨杀跌) → 散户
    retail_pattern = _clip(0.5 * _clip(min(turn_score / 100.0 * 1.6, 1.0) * 100.0) +
                          0.5 * _clip(max((abs(min_dd) - 0.10) / 0.40, 0.0) * 100.0))

    # =================== M3.1 新维度微调(仅当数据可用) =================== #
    extra = _parse_extra(raw)
    seat, flow, flow_retail = _fold_extra(seat, flow, flow_retail, extra)
    seat = _clip(seat); flow = _clip(flow); flow_retail = _clip(flow_retail)

    quant_score = _clip(np.nan_to_num(
        W["seat"] * seat + W["flow"] * flow +
        W["pattern"] * pattern + W["persist"] * persist, nan=50.0))

    retail_score = _clip(0.6 * flow_retail + 0.4 * retail_pattern)

    is_retail = bool(retail_score >= 55.0 and quant_score <= 45.0)

    # =================== 疑似类型推断 =================== #
    suspected = _infer_type(
        quant_score, pattern, seat, flow, lhb, mom60, vol20, turn_score, min_dd
    )

    evidence = _build_evidence(lhb, inst_cum, inst_net_pct, turn_score,
                               min_dd, quant_score, retail_score, suspected, is_retail)
    evidence += _extra_evidence(extra)

    return {
        "code": code,
        "name": name,
        "quant_score": round(quant_score, 1),
        "retail_score": round(retail_score, 1),
        "is_retail_dominated": is_retail,
        "suspected_type": suspected,
        "evidence": evidence,
        "extra_signals": extra,
        "sub_scores": {
            "institution_seat": round(seat, 1),
            "inst_flow": round(flow, 1),
            "pattern_hft": round(pattern, 1),
            "persistence": round(persist, 1),
            "turnover_score": round(turn_score, 1),
            "low_drawdown_score": round(lowdd_score, 1),
            "inst_net_amount": round(inst_cum, 1),
            "inst_net_pct_of_turnover": round(inst_net_pct, 2),
            "lhb_count": lhb["count"],
            "lhb_net": round(lhb["net"], 1),
            "lhb_post_mean_ret": round(lhb["post_mean"], 4),
            "min_drawdown": round(min_dd, 4),
            "ann_vol": round(vol20, 4),
            "mom60": round(mom60, 4),
        },
    }


def _infer_type(quant, pattern, seat, flow, lhb, mom60, vol20, turn, min_dd) -> str:
    if quant < 35:
        return "无明显量化特征"
    # 高频做市/日内均值回归:高换手 + 低回撤
    if pattern >= 60 and turn >= 55 and abs(min_dd) < 0.25:
        return "高频做市 / 日内均值回归(疑似)"
    # 机构/量化混合:龙虎榜机构买入且持续为正
    if lhb["inst_buy"] and lhb["post_mean"] > 0:
        return "指数增强 / 市场中性(机构,疑似)"
    # 中低频趋势:动量正、波动适中
    if mom60 > 0 and 0.25 <= vol20 <= 0.70:
        return "中低频趋势跟踪(疑似)"
    # 统计套利(疑似):价量平稳、量化分高但非高频特征
    if quant >= 60 and pattern < 55:
        return "统计套利(疑似)"
    return "机构 / 量化混合(疑似)"


def _build_evidence(lhb, inst_cum, inst_net_pct, turn, min_dd,
                    quant, retail, suspected, is_retail) -> list:
    ev = []
    if lhb["count"]:
        ev.append(f"龙虎榜上榜 {lhb['count']} 次,净买额 {lhb['net']/1e8:.2f} 亿;"
                  f"机构买入解读={'有' if lhb['inst_buy'] else '无'};"
                  f"上榜后平均收益 {lhb['post_mean']*100:.2f}%")
    else:
        ev.append("近窗无龙虎榜数据")
    ev.append(f"超大单+大单累计净买 {inst_cum/1e8:.2f} 亿,"
              f"占区间成交额约 {inst_net_pct:.2f}%")
    ev.append(f"换手比率评分 {turn:.0f}/100,区间最大回撤 {min_dd*100:.1f}%"
              f"→ 价量模式{'偏量化做市/高频' if turn>=55 and abs(min_dd)<0.25 else '不典型'}")
    ev.append(f"量化资金评分 {quant:.0f}/100,散户主导评分 {retail:.0f}/100"
              f"→ 疑似类型:【{suspected}】")
    if is_retail:
        ev.append("⚠ 散户主导特征显著:大资金净流出而散户/游资接盘概率高")
    return ev
