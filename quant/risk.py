"""
quant/risk.py — 风险控制分析
========================
输入:策略日收益序列 strat_ret、基准日收益 ret、收盘价 close。
纯 pandas / numpy 实现,零重依赖。

输出风险档案:
  var_95 / var_99       历史模拟法 VaR (95% / 99% 单日分位损失)
  cvar_95              条件 VaR (95% 期望短缺)
  ann_vol              年化波动(沿用 backtest 口径)
  downside_dev / sortino 下行波动 / Sortino
  max_drawdown / dd_days 最大回撤及持续交易日
  vol_target_weight    波动目标仓位(目标年化 vol 默认 20%)
  kelly_fraction      保守 Kelly 仓位 (0.5 * 经典 Kelly)
  stress               压力情景(单日 -5%/-10% / 连5日 -20% / 历史最差20日)
  risk_grade          低 / 中 / 高 / 极高(综合 VaR 与回撤)

所有结果为历史统计,不代表未来,不构成投资建议。
"""

from __future__ import annotations

import numpy as np
import pandas as pd

__all__ = ["analyze", "grade"]

TRADING_DAYS = 252
TARGET_ANN_VOL = 0.20  # 波动目标默认 20% 年化


def _safe(x, default=0.0):
    return float(x) if (x is not None and np.isfinite(x)) else default


def _max_drawdown(equity: pd.Series):
    """返回 (max_dd, dd_days)。"""
    eq = pd.Series(equity, dtype="float64").reset_index(drop=True)
    if eq.empty:
        return 0.0, 0
    peak = eq.cummax()
    dd = eq / peak - 1.0
    max_dd = float(dd.min())
    # 持续天数:从创纪录高点到最低点
    dd_days = 0
    run = 0
    for v in dd.values:
        if v < 0:
            run += 1
            dd_days = max(dd_days, run)
        else:
            run = 0
    return max_dd, dd_days


def _var_cvar(ret: pd.Series, conf: float):
    """历史模拟法 VaR / CVaR(正数表示损失幅度)。"""
    r = pd.Series(ret, dtype="float64").dropna()
    if len(r) < 5:
        return 0.0, 0.0
    q = np.percentile(r.values, (1.0 - conf) * 100.0)
    tail = r[r <= q]
    cvar = float(tail.mean()) if len(tail) else q
    # 返回损失为正
    return max(-q, 0.0), max(-cvar, 0.0)


def _stress(ret: pd.Series, close: pd.Series) -> dict:
    r = pd.Series(ret, dtype="float64").dropna()
    out = {}
    # 单日极端情景(直接给定损失幅度,与历史分布无关,作为硬性压力)
    out["single_day_-5%"] = -0.05
    out["single_day_-10%"] = -0.10
    # 连续 5 日各 -20% 复合：(0.8)^5 - 1 ≈ -67.2%
    _5d = (1.0 - 0.20) ** 5.0 - 1.0
    out["five_day_-20%"] = float(_5d)
    out["five_day_-20%_compound"] = float(_5d)
    # 历史最差 20 日累计收益
    if len(r) >= 20:
        roll = r.rolling(20).sum().min()
        out["worst_20d"] = _safe(roll)
    else:
        out["worst_20d"] = _safe(r.sum()) if len(r) else 0.0
    # 历史上最差单日
    out["worst_1d"] = _safe(r.min()) if len(r) else 0.0
    return out


def analyze(strat_ret, bench_ret=None, close=None) -> dict:
    """
    strat_ret: 策略日收益序列
    bench_ret: 基准(买入持有)日收益序列,可选
    close:     收盘价序列,可选(当前未强制使用)
    """
    sr = pd.Series(strat_ret, dtype="float64").dropna()
    n = len(sr)
    if n < 5:
        return {
            "var_95": 0.0, "var_99": 0.0, "cvar_95": 0.0,
            "ann_vol": 0.0, "downside_dev": 0.0, "sortino": 0.0,
            "max_drawdown": 0.0, "dd_days": 0,
            "vol_target_weight": 0.0, "kelly_fraction": 0.0,
            "stress": {}, "risk_grade": "数据不足",
            "n_days": int(n),
        }

    var95, _ = _var_cvar(sr, 0.95)
    var99, cvar95 = _var_cvar(sr, 0.99)

    ann_vol = _safe(sr.std() * np.sqrt(TRADING_DAYS))
    # 下行偏差
    down = sr[sr < 0]
    downside_dev = _safe(down.std() * np.sqrt(TRADING_DAYS))
    mean = sr.mean()
    sortino = float(mean / downside_dev * np.sqrt(TRADING_DAYS)) if downside_dev > 1e-12 else 0.0

    # 权益曲线回撤
    equity = (1.0 + sr).cumprod()
    max_dd, dd_days = _max_drawdown(equity)

    # 波动目标仓位:目标年化 vol / 实际年化 vol,截断 [0,1]
    vol_target = _safe(TARGET_ANN_VOL / ann_vol, 0.0) if ann_vol > 1e-9 else 0.0
    vol_target = float(min(max(vol_target, 0.0), 1.0))

    # 保守 Kelly: p=胜率, b=盈亏比(平均盈利/平均亏损)
    wins = sr[sr > 0]
    loss = sr[sr < 0]
    p = len(wins) / n if n else 0.0
    avg_w = wins.mean() if len(wins) else 0.0
    avg_l = abs(loss.mean()) if len(loss) else 0.0
    if avg_l > 1e-12 and avg_w > 0:
        b = avg_w / avg_l
        kelly = p - (1.0 - p) / b
        kelly = 0.5 * kelly  # 保守半 Kelly
    else:
        kelly = 0.0
    kelly = float(min(max(kelly, 0.0), 1.0))

    stress = _stress(sr, close)

    grade_str = grade(var95, abs(max_dd))

    return {
        "var_95": round(var95, 4),
        "var_99": round(var99, 4),
        "cvar_95": round(cvar95, 4),
        "ann_vol": round(ann_vol, 4),
        "downside_dev": round(downside_dev, 4),
        "sortino": round(float(sortino), 3),
        "max_drawdown": round(max_dd, 4),
        "dd_days": int(dd_days),
        "vol_target_weight": round(vol_target, 3),
        "kelly_fraction": round(kelly, 3),
        "stress": {k: round(float(v), 4) for k, v in stress.items()},
        "risk_grade": grade_str,
        "n_days": int(n),
    }


def grade(var95: float, max_dd_abs: float) -> str:
    """
    综合单日 VaR(95%) 与最大回撤幅度评级。
    var95 / max_dd_abs 均为正数(损失幅度)。
    """
    v = _safe(var95)
    d = _safe(max_dd_abs)
    # 高波动/深回撤 → 高风险
    if v >= 0.05 or d >= 0.35:
        return "极高"
    if v >= 0.035 or d >= 0.22:
        return "高"
    if v >= 0.02 or d >= 0.12:
        return "中"
    return "低"


def analyze_both(strat_ret, bench_ret=None, close=None) -> dict:
    """同时对策略与买入持有做风险分析,便于对照。"""
    return {
        "strategy": analyze(strat_ret, bench_ret, close),
        "buyhold": analyze(bench_ret, None, close) if bench_ret is not None else None,
    }
