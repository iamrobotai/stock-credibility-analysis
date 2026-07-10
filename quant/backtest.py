"""
quant/backtest.py — 轻量向量化回测引擎
========================================
设计:
- 全向量化 (pandas / numpy),无第三方重依赖,支持本地一键。
- 防前视:以 t-1 收盘信号决定 t 日持仓(对应 A 股 T+1)。
- 交易成本:持仓变动 |Δpos| * cost 从收益中扣除。
- A 股约束:现货默认多头(allow_short=False 时 clip 到 >=0);
  配对/统计套利为市场中性,allow_short=True 允许 -1。
- 绩效:总收益/CAGR/年化波动/Sharpe/最大回撤/Calmar/胜率/交易次数,
  并给出买入持有(benchmark)对照。
"""

from __future__ import annotations

import numpy as np
import pandas as pd

__all__ = ["backtest", "BacktestResult"]

TRADING_DAYS = 252


class BacktestResult:
    """回测结果(可 JSON 序列化)。"""

    def __init__(self, label: str, metrics: dict, equity, bench_equity, dates,
                 returns=None, positions=None, bench_returns=None):
        self.label = label
        self.metrics = metrics
        self.equity = list(map(float, equity))
        self.bench_equity = list(map(float, bench_equity))
        self.dates = list(map(str, dates))
        # 下游分析(风控/持仓)复用:策略日收益、仓位、基准日收益
        self.returns = list(map(float, returns)) if returns is not None else []
        self.positions = list(map(float, positions)) if positions is not None else []
        self.bench_returns = list(map(float, bench_returns)) if bench_returns is not None else []

    def to_dict(self) -> dict:
        return {
            "label": self.label,
            "metrics": self.metrics,
            "equity": self.equity,
            "bench_equity": self.bench_equity,
            "dates": self.dates,
            "returns": self.returns,
            "positions": self.positions,
            "bench_returns": self.bench_returns,
        }


def backtest(close, position, cost: float = 0.001,
             allow_short: bool = False, label: str = "strategy",
             dates=None) -> BacktestResult:
    """
    close:     收盘价序列 (list/Series)
    position:   目标仓位序列 (-1/0/1),与 close 等长
    cost:       单边变动成本(默认 0.1%)
    allow_short:是否允许空头(配对/套利=True)
    """
    close = pd.Series(close, dtype="float64").reset_index(drop=True)
    pos = pd.Series(position, dtype="float64").reset_index(drop=True)
    n = len(close)
    if n < 3:
        return BacktestResult(label, _empty_metrics(), [1.0], [1.0], dates or [])

    if not allow_short:
        pos = pos.clip(lower=0.0)
    pos = pos.fillna(0.0)

    ret = close.pct_change().fillna(0.0)
    held = pos.shift(1).fillna(0.0)            # t-1 信号决定 t 持仓
    strat_ret = held * ret
    turnover = pos.diff().abs().fillna(pos.abs())
    strat_ret = strat_ret - turnover * cost      # 扣除交易成本

    equity = (1.0 + strat_ret).cumprod()
    bench_equity = (1.0 + ret).cumprod()

    m = _metrics(strat_ret, equity)
    bm = _metrics(ret, bench_equity)
    m["bench_total_return"] = float(bench_equity.iloc[-1] - 1.0)
    m["excess_return"] = m["total_return"] - m["bench_total_return"]
    m["bench_sharpe"] = bm["sharpe"]
    m["bench_max_drawdown"] = bm["max_drawdown"]
    m["cost_paid"] = float((turnover * cost).sum())
    m["trades"] = int((turnover > 1e-9).sum())
    m["invested_ratio"] = float((pos > 0.5).mean())
    m["allow_short"] = bool(allow_short)

    dts = dates if dates is not None else list(range(n))
    return BacktestResult(label, m, equity.values, bench_equity.values, dts,
                          returns=strat_ret.values,
                          positions=pos.values,
                          bench_returns=ret.values)


def _metrics(ret: pd.Series, equity: pd.Series) -> dict:
    n = len(ret)
    if n == 0:
        return _empty_metrics()
    total = float(equity.iloc[-1] - 1.0)
    years = max(n / TRADING_DAYS, 1e-9)
    cagr = float(equity.iloc[-1] ** (1.0 / years) - 1.0) if equity.iloc[-1] > 0 else -1.0
    vol = float(ret.std() * np.sqrt(TRADING_DAYS)) if ret.std() == ret.std() else 0.0
    mean = float(ret.mean())
    std = float(ret.std())
    sharpe = float(mean / std * np.sqrt(TRADING_DAYS)) if std > 1e-12 else 0.0
    dd = equity / equity.cummax() - 1.0
    max_dd = float(dd.min())
    calmar = float(cagr / abs(max_dd)) if abs(max_dd) > 1e-9 else 0.0
    win = float((ret > 0).mean()) if n else 0.0
    return {
        "total_return": total,
        "cagr": cagr,
        "ann_vol": vol,
        "sharpe": sharpe,
        "max_drawdown": max_dd,
        "calmar": calmar,
        "win_rate": win,
        "n_days": int(n),
    }


def _empty_metrics() -> dict:
    return {
        "total_return": 0.0, "cagr": 0.0, "ann_vol": 0.0, "sharpe": 0.0,
        "max_drawdown": 0.0, "calmar": 0.0, "win_rate": 0.0, "n_days": 0,
        "bench_total_return": 0.0, "excess_return": 0.0, "bench_sharpe": 0.0,
        "bench_max_drawdown": 0.0, "cost_paid": 0.0, "trades": 0,
        "invested_ratio": 0.0, "allow_short": False,
    }
