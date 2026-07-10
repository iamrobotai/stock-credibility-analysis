"""
quant/strategies.py — 5 类经典量化策略信号生成
================================================
所有策略统一接口: signal(df, ctx=None) -> pd.Series(position)
  position ∈ {-1, 0, 1}  (1=持有多头, -1=持有空头/对冲腿, 0=空仓)
  * 单个 A 股现货默认多头(1/0);配对/统计套利天然市场中性,允许 -1。
  * 信号基于当日可观测数据;backtest 层会 shift(1) 避免前视。

策略列表:
  1. TrendFollowing  趋势跟踪   (MA 交叉 / Donchian 突破)
  2. MeanReversion    均值回归   (Bollinger %B 超买超卖)
  3. Momentum        动量       (绝对动量 mom60)
  4. PairsTrading    配对交易   (与行业 peer 协整价差 z-score, 需 ctx.peer)
  5. StatArb         统计套利   (相对行业 peer 的截面 z-score)
"""

from __future__ import annotations

import numpy as np
import pandas as pd

__all__ = ["STRATEGIES", "get_strategy", "Strategy", "TrendFollowing",
           "MeanReversion", "Momentum", "PairsTrading", "StatArb"]


class Strategy:
    name: str = "base"
    label: str = "基类"
    category: str = ""
    needs_peer: bool = False
    description: str = ""

    def signal(self, df: pd.DataFrame, ctx: dict | None = None) -> pd.Series | None:
        raise NotImplementedError


# --------------------------------------------------------------------------- #
#  1. 趋势跟踪
# --------------------------------------------------------------------------- #
class TrendFollowing(Strategy):
    name = "trend"
    label = "趋势跟踪"
    category = "趋势"
    description = "快线(MA10)上穿慢线(MA60)持有多头,下穿空仓;反映中长趋势方向。"

    def __init__(self, fast: int = 10, slow: int = 60):
        self.fast = fast
        self.slow = slow

    def signal(self, df, ctx=None):
        if df.empty or f"ma{self.slow}" not in df.columns:
            return None
        fast = df[f"ma{self.fast}"]
        slow = df[f"ma{self.slow}"]
        pos = pd.Series(0, index=df.index, dtype=float)
        pos[fast > slow] = 1
        # 慢线缺失处保持空仓
        pos[slow.isna()] = 0
        return pos.fillna(0)


# --------------------------------------------------------------------------- #
#  2. 均值回归
# --------------------------------------------------------------------------- #
class MeanReversion(Strategy):
    name = "meanrev"
    label = "均值回归"
    category = "反转"
    description = "布林带 %B < 0.15 视为超卖建仓,> 0.6 视为回归平仓;捕捉均值回复。"

    def __init__(self, lower: float = 0.15, upper: float = 0.6):
        self.lower = lower
        self.upper = upper

    def signal(self, df, ctx=None):
        if df.empty or "bb_pctb" not in df.columns:
            return None
        pctb = df["bb_pctb"]
        target = pd.Series(np.nan, index=df.index)
        target[pctb < self.lower] = 1
        target[pctb > self.upper] = 0
        pos = target.ffill().fillna(0)
        return pos.astype(float)


# --------------------------------------------------------------------------- #
#  3. 动量
# --------------------------------------------------------------------------- #
class Momentum(Strategy):
    name = "momentum"
    label = "动量"
    category = "动量"
    description = "60 日绝对动量>0 持有,反映中期价格惯性;截面动量由 engine 在行业内排序实现。"

    def __init__(self, lookback: int = 60, threshold: float = 0.0):
        self.lookback = lookback
        self.threshold = threshold

    def signal(self, df, ctx=None):
        col = f"mom{self.lookback}"
        if df.empty or col not in df.columns:
            return None
        mom = df[col]
        pos = pd.Series(0, index=df.index, dtype=float)
        pos[mom > self.threshold] = 1
        pos[mom.isna()] = 0
        return pos.fillna(0)


# --------------------------------------------------------------------------- #
#  4. 配对交易 (需 peer)
# --------------------------------------------------------------------------- #
class PairsTrading(Strategy):
    name = "pairs"
    label = "配对交易"
    category = "套利"
    needs_peer = True
    description = "与行业 peer 价格做 OLS 对冲得价差,价差 z-score 越低越便宜→做多该标的(同时对冲 peer)。市场中性。"

    def __init__(self, window: int = 60, entry: float = 1.5, exit_z: float = 0.3):
        self.window = window
        self.entry = entry
        self.exit_z = exit_z

    def _beta(self, y: pd.Series, x: pd.Series) -> float:
        m = y.notna() & x.notna()
        if m.sum() < 30:
            return np.nan
        Y = y[m].values; X = x[m].values
        if np.std(X) < 1e-9:        # 协变量近似常数
            return np.nan
        try:
            b = np.polyfit(X, Y, 1)[0]
        except Exception:
            return np.nan
        return b if np.isfinite(b) else np.nan

    def signal(self, df, ctx=None):
        if df.empty or ctx is None or "peer" not in ctx or ctx["peer"] is None:
            return None
        peer = ctx["peer"]
        if not isinstance(peer, pd.Series) or len(peer) != len(df):
            return None
        y = df["close"]
        beta = self._beta(y, peer)
        if not np.isfinite(beta):
            return None
        spread = y - beta * peer
        mu = spread.rolling(self.window).mean()
        sd = spread.rolling(self.window).std()
        with np.errstate(divide="ignore", invalid="ignore"):
            z = (spread - mu) / sd
        z = z.replace([np.inf, -np.inf], np.nan)
        if z.notna().sum() == 0:        # 价差平稳/无背离,无交易信号
            return None
        target = pd.Series(np.nan, index=df.index)
        target[z < -self.entry] = 1     # 价差偏便宜 -> 做多
        target[z > self.entry] = -1      # 价差偏贵   -> 做空(对冲)
        target[z.abs() < self.exit_z] = 0
        pos = target.ffill().fillna(0)
        return pos.astype(float)


# --------------------------------------------------------------------------- #
#  5. 统计套利 (相对行业截面 z-score, 需 peer)
# --------------------------------------------------------------------------- #
class StatArb(Strategy):
    name = "statarb"
    label = "统计套利"
    category = "套利"
    needs_peer = True
    description = "计算个股相对行业 peer 比价的滚动 z-score,做多相对便宜者、做空相对昂贵者;截面相对价值。"

    def __init__(self, window: int = 60, entry: float = 1.5, exit_z: float = 0.3):
        self.window = window
        self.entry = entry
        self.exit_z = exit_z

    def signal(self, df, ctx=None):
        if df.empty or ctx is None or "peer" not in ctx or ctx["peer"] is None:
            return None
        peer = ctx["peer"]
        if not isinstance(peer, pd.Series) or len(peer) != len(df):
            return None
        rel = df["close"] / peer.replace(0, np.nan)
        rel = rel.replace([np.inf, -np.inf], np.nan)
        mu = rel.rolling(self.window).mean()
        sd = rel.rolling(self.window).std()
        with np.errstate(divide="ignore", invalid="ignore"):
            z = (rel - mu) / sd
        z = z.replace([np.inf, -np.inf], np.nan)
        if z.notna().sum() == 0:        # 相对比价平稳/无背离,无交易信号
            return None
        target = pd.Series(np.nan, index=df.index)
        target[z < -self.entry] = 1
        target[z > self.entry] = -1
        target[z.abs() < self.exit_z] = 0
        pos = target.ffill().fillna(0)
        return pos.astype(float)


# --------------------------------------------------------------------------- #
#  注册表
# --------------------------------------------------------------------------- #
STRATEGIES = {
    "trend": TrendFollowing(),
    "meanrev": MeanReversion(),
    "momentum": Momentum(),
    "pairs": PairsTrading(),
    "statarb": StatArb(),
}


def get_strategy(name: str, **kwargs) -> Strategy:
    if name not in STRATEGIES:
        raise KeyError(f"未知策略: {name}")
    base = STRATEGIES[name]
    if kwargs:
        return base.__class__(**kwargs)
    return base
