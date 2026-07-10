"""
quant/features.py — 特征工程
================================
从 {code}_raw.json 中解析行情与资金流，构造量化分析所需的特征因子。

设计原则：
- 零重依赖（仅 pandas / numpy），支持本地一键执行。
- 所有解析对空字符串、缺失字段做容错，缺失维度返回空 DataFrame 而非崩溃。
- 技术指标与资金特征分离，便于策略层与识别层分别调用。
"""

from __future__ import annotations

import numpy as np
import pandas as pd

__all__ = [
    "load_kline", "load_fundflow", "add_technicals", "add_fund_features",
    "build_feature_frame", "MA_WINDOWS",
]


# 常用均线窗口
MA_WINDOWS = (5, 10, 20, 60)


def _num(x):
    """把各种形态的数值字段转成 float，失败返回 NaN。"""
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


# --------------------------------------------------------------------------- #
#  数据加载
# --------------------------------------------------------------------------- #
def load_kline(raw: dict) -> pd.DataFrame:
    """
    解析 raw.json 的 kline 列表为 DataFrame。
    返回列: date, open, high, low, close, volume, amount, pct
    按日期升序，丢弃 close 为空的行。无数据返回空 DataFrame。
    """
    rows = []
    for r in (raw.get("kline") or []):
        if not isinstance(r, dict):
            continue
        rows.append({
            "date": str(r.get("date") or "")[:10],
            "open": _num(r.get("open")),
            "high": _num(r.get("high")),
            "low": _num(r.get("low")),
            "close": _num(r.get("close")),
            "volume": _num(r.get("volume")),
            "amount": _num(r.get("amount")),
            "pct": _num(r.get("pct")),
        })
    df = pd.DataFrame(rows)
    if df.empty:
        return df
    df = df.dropna(subset=["close"]).copy()
    df = df[df["date"] != ""].sort_values("date").reset_index(drop=True)
    # 去重同日（保留最后一条）
    df = df.drop_duplicates(subset=["date"], keep="last").reset_index(drop=True)
    return df


def load_fundflow(raw: dict) -> pd.DataFrame:
    """
    解析 raw.json 的 sina_fund（主力/超大单/大单资金流）。
    返回列: date, main_net, main_pct, super_net, big_net
    """
    rows = []
    for r in (raw.get("sina_fund") or []):
        if not isinstance(r, dict):
            continue
        rows.append({
            "date": str(r.get("date") or "")[:10],
            "main_net": _num(r.get("main_net")),
            "main_pct": _num(r.get("main_pct")),
            "super_net": _num(r.get("super_net")),
            "big_net": _num(r.get("big_net")),
        })
    df = pd.DataFrame(rows)
    if df.empty:
        return df
    df = df[df["date"] != ""].sort_values("date").reset_index(drop=True)
    df = df.drop_duplicates(subset=["date"], keep="last").reset_index(drop=True)
    return df


# --------------------------------------------------------------------------- #
#  技术指标
# --------------------------------------------------------------------------- #
def _rsi(close: pd.Series, n: int = 14) -> pd.Series:
    d = close.diff()
    up = d.clip(lower=0.0)
    dn = -d.clip(upper=0.0)
    roll_up = up.rolling(n).mean()
    roll_dn = dn.rolling(n).mean()
    rs = roll_up / roll_dn.replace(0, np.nan)
    return (100 - 100 / (1 + rs)).fillna(50.0)


def _atr(high: pd.Series, low: pd.Series, close: pd.Series, n: int = 14) -> pd.Series:
    pc = close.shift(1)
    tr = pd.concat(
        [(high - low), (high - pc).abs(), (low - pc).abs()], axis=1
    ).max(axis=1)
    return tr.rolling(n).mean()


def add_technicals(df: pd.DataFrame) -> pd.DataFrame:
    """
    在 kline DataFrame 上追加技术指标因子。
    新增列: ret, logret, ma5/10/20/60, ema20, rsi14, bb_*, atr14,
            vol20(年化波动), mom20, mom60, drawdown, vol_ma20, vol_ratio
    """
    if df.empty:
        return df
    close = df["close"]
    high = df["high"]
    low = df["low"]
    vol = df["volume"]

    df["ret"] = close.pct_change().fillna(0.0)
    df["logret"] = np.log(close / close.shift(1)).fillna(0.0)

    for n in MA_WINDOWS:
        df[f"ma{n}"] = close.rolling(n).mean()
    df["ema20"] = close.ewm(span=20, adjust=False).mean()

    df["rsi14"] = _rsi(close, 14)

    m = close.rolling(20).mean()
    s = close.rolling(20).std()
    df["bb_mid"] = m
    df["bb_std"] = s
    df["bb_up"] = m + 2 * s
    df["bb_dn"] = m - 2 * s
    with np.errstate(divide="ignore", invalid="ignore"):
        df["bb_pctb"] = ((close - m) / (2 * s)).replace([np.inf, -np.inf], np.nan)
        df["bb_width"] = ((df["bb_up"] - df["bb_dn"]) / m).replace([np.inf, -np.inf], np.nan)

    df["atr14"] = _atr(high, low, close, 14)

    df["vol20"] = df["ret"].rolling(20).std() * np.sqrt(252)
    df["mom20"] = close / close.shift(20) - 1
    df["mom60"] = close / close.shift(60) - 1

    running_max = close.cummax()
    df["drawdown"] = close / running_max - 1.0

    df["vol_ma20"] = vol.rolling(20).mean()
    with np.errstate(divide="ignore", invalid="ignore"):
        df["vol_ratio"] = (vol / df["vol_ma20"]).replace([np.inf, -np.inf], np.nan)

    return df


def add_fund_features(df: pd.DataFrame) -> pd.DataFrame:
    """在资金流 DataFrame 上追加累计净买与机构(超大+大单)净买特征。"""
    if df.empty:
        return df
    for col in ("main_net", "super_net", "big_net"):
        df[col] = df[col].fillna(0.0)
    df["super_cum"] = df["super_net"].cumsum()
    df["big_cum"] = df["big_net"].cumsum()
    df["main_cum"] = df["main_net"].cumsum()
    df["inst_cum_net"] = df["super_net"] + df["big_net"]  # 机构级(超大+大单)累计净买
    df["inst_cum_net_cum"] = df["inst_cum_net"].cumsum()
    return df


def build_feature_frame(raw: dict) -> pd.DataFrame:
    """
    一站式：返回带技术指标 + 资金特征的合并 DataFrame（按日期左接 kline）。
    回测/识别统一从此取数。
    """
    k = add_technicals(load_kline(raw))
    f = add_fund_features(load_fundflow(raw))
    if k.empty:
        return k
    if not f.empty:
        # 资金流按日期 merge 到行情
        k = k.merge(f, on="date", how="left")
        for col in ("super_net", "big_net", "main_net",
                    "super_cum", "big_cum", "main_cum",
                    "inst_cum_net", "inst_cum_net_cum"):
            if col in k.columns:
                k[col] = k[col].fillna(0.0)
    return k
