"""
quant/position.py — 持仓分析
=========================
两大部分:
  A. 策略持仓画像(基于回测的仓位序列与收益序列)
     - 平均持仓天数 / 最长连续盈利·亏损
     - 盈亏比(平均盈利/平均亏损)
     - 在场占比 / 年化换手
     - 在场 vs 空仓 的收益贡献
  B. 持有者结构推断(基于 quant_fund_id 的量化/散户评分 + 龙虎榜)
     - holder_mix: 量化/机构 · 散户/游资 · 均衡 三方占比估算
     - who_is_positioned: "谁在车上"
     - position_risk_note: 量化主导+高换手 → 散户追涨易被收割提示

所有结论为疑似/推测,基于公开量价数据的启发式推断,不构成投资建议。
"""

from __future__ import annotations

import numpy as np
import pandas as pd

__all__ = ["analyze"]

# 持仓判定阈值(仓位绝对值)
EXPOSED = 0.5


def _consec_runs(mask: pd.Series):
    """返回最长连续 True 段长度。"""
    m = mask.fillna(False).astype(bool).values
    best = run = 0
    for v in m:
        if v:
            run += 1
            best = max(best, run)
        else:
            run = 0
    return int(best)


def _holding_profile(positions, returns) -> dict:
    pos = pd.Series(positions, dtype="float64").fillna(0.0).reset_index(drop=True)
    ret = pd.Series(returns, dtype="float64").fillna(0.0).reset_index(drop=True)
    n = len(pos)
    if n < 3:
        return {"avg_holding_days": 0, "max_consec_wins": 0,
                "max_consec_losses": 0, "win_loss_ratio": 0.0,
                "exposure_ratio": 0.0, "turnover_rate": 0.0,
                "pnl_in_market": 0.0, "pnl_out_market": 0.0, "n_days": int(n)}

    exposed = pos.abs() > EXPOSED
    # 平均持仓天数:连续在场段的平均长度
    runs, cur = [], 0
    for e in exposed.values:
        if e:
            cur += 1
        else:
            if cur:
                runs.append(cur)
            cur = 0
    if cur:
        runs.append(cur)
    avg_hold = float(np.mean(runs)) if runs else 0.0

    # 最长连续盈利/亏损(在场的交易日)
    r_in = ret[exposed]
    up = (r_in > 0).astype(int)
    dn = (r_in < 0).astype(int)
    max_win = _consec_runs(up == 1)
    max_loss = _consec_runs(dn == 1)

    wins = r_in[r_in > 0]
    loss = r_in[r_in < 0]
    aw = wins.mean() if len(wins) else 0.0
    al = abs(loss.mean()) if len(loss) else 0.0
    wlr = float(aw / al) if al > 1e-12 else 0.0

    exposure_ratio = float(exposed.mean())
    # 年化换手:sum(|Δpos|)/2 * 252 / n
    turnover = float(pos.diff().abs().fillna(pos.abs()).sum()) / 2.0
    turnover_rate = turnover * 252.0 / n if n else 0.0

    pnl_in = float(r_in.sum())
    pnl_out = float(ret[~exposed].sum())

    return {
        "avg_holding_days": round(avg_hold, 1),
        "max_consec_wins": max_win,
        "max_consec_losses": max_loss,
        "win_loss_ratio": round(wlr, 3),
        "exposure_ratio": round(exposure_ratio, 3),
        "turnover_rate": round(turnover_rate, 2),
        "pnl_in_market": round(pnl_in, 4),
        "pnl_out_market": round(pnl_out, 4),
        "n_days": int(n),
    }


def _holder_mix(qid: dict, extra: dict | None = None) -> dict:
    """基于量化/散户评分估算持有者结构(三方占比)。

    extra: 来自 quant_fund_id 的 extra_signals(北向/两融/股东)。
    当数据可用时, 对三方占比做温和修正:
      - 北向增持 / 股东户数下降 → 机构+量化浓度 ↑
      - 融资余额增长            → 散户/游资(杠杆)浓度 ↑
    """
    qs = float(qid.get("quant_score") or 0.0)
    rs = float(qid.get("retail_score") or 0.0)
    inst = max(0.0, qs - 20.0)        # 高于 20 才计机构/量化浓度
    retail = max(0.0, rs - 20.0)
    neutral = max(0.0, 100.0 - inst - retail)
    # ── M3.1 新维度修正(仅当 available) ──
    if isinstance(extra, dict):
        n = extra.get("north_fund", {})
        m = extra.get("margin", {})
        h = extra.get("holder_num", {})
        if n.get("available") and (n.get("chg_5d_pct") or 0) > 0:
            inst += 8.0
        if h.get("available") and (h.get("change_pct") or 0) < 0:
            inst += 6.0
        if m.get("available") and (m.get("fin_balance_chg") or 0) > 0:
            retail += 6.0
    tot = inst + retail + neutral
    if tot > 1e-9:
        inst, retail, neutral = inst / tot * 100.0, retail / tot * 100.0, neutral / tot * 100.0
    else:
        inst, retail, neutral = 33.3, 33.3, 33.4
    return {
        "institution_quant": round(inst, 1),
        "retail_retail": round(retail, 1),
        "balanced": round(neutral, 1),
    }


def _who_and_note(mix: dict, qid: dict, profile: dict) -> tuple:
    inst = mix["institution_quant"]
    ret = mix["retail_retail"]
    qs = float(qid.get("quant_score") or 0.0)
    rs = float(qid.get("retail_score") or 0.0)
    typ = qid.get("suspected_type", "")
    turn = float((qid.get("sub_scores") or {}).get("turnover_score") or 0.0)

    if inst >= ret and inst >= 45.0:
        typ_clean = typ.replace("(疑似)", "").strip()
        who = "量化/机构资金为主" + (f"(疑似 {typ_clean})" if typ_clean else "")
        note = ("量化/机构资金在车上,凭借速度、算法与资金优势在波动中更易获利;"
                "散户多为对手盘。若你方为散户,应规避与量化同侧的追涨杀跌。")
    elif ret > inst and ret >= 45.0:
        who = "散户/游资为主"
        note = ("当前以散户/游资博弈为主,信息劣势端易被阶段性收割;"
                "若你方为散户,需警惕一致预期反转与流动性踩踏。")
    else:
        who = "量化/机构 与 散户/游资 混合博弈"
        note = ("资金结构呈混合态,存量博弈特征明显;"
                "建议结合龙虎榜席位逐笔构成与北向/融资融券方向进一步确认主导方。")
    # 高换手 + 量化主导 → 散户追涨提示
    if qs >= 55.0 and turn >= 55.0:
        note += " 该股高换手且量化特征显著,散户追涨杀跌被收割的概率较高,谨慎追高。"
    return who, note


def analyze(positions, returns, qid: dict | None = None) -> dict:
    qid = qid or {"quant_score": 0.0, "retail_score": 0.0,
                   "suspected_type": "", "sub_scores": {}}
    profile = _holding_profile(positions, returns)
    mix = _holder_mix(qid, qid.get("extra_signals"))
    who, note = _who_and_note(mix, qid, profile)
    return {
        "holding_profile": profile,
        "holder_mix": mix,
        "who_is_positioned": who,
        "position_risk_note": note,
    }
