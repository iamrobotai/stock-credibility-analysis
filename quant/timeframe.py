# -*- coding: utf-8 -*-
"""
quant/timeframe.py — 多周期价格曲线动态分析
============================================
将单一「日 K 线」动态重采样为多个时间维度（日 K / 周 K / 月 K），
并按时间变化逐周期计算关键量化指标：
    · 均线趋势（MA5/10/20/60 多头/空头/缠绕排列）
    · 波动率（年化波动 + 近期 vs 基线波动比）
    · 成交量变化（量比 + 量能趋势）
    · 动量 / 趋势强度 / 信号 / 0-100 量化子评分

设计要点：
  - 零重依赖（仅 numpy / pandas）。
  - 重采样用「确定性分桶」（年-周 / 年-月），不依赖 pandas resample 版本差异。
  - 所有解析对空值 / 长度不足做容错，缺失维度返回安全的退化结果。
  - 实现 common.interfaces.TimeframeAnalyzer 契约，可被 registry 替换实现。

输出契约（quant contract）：
  {
    "timeframes": {tf: {period, n_bars, last_close, ma_trend,
                     volatility, volume_change, momentum, trend_strength,
                     signal, score}, ...},
    "alignment": "日周月共振·多头" | "日周月共振·空头" | "周期分化",
    "composite_quant_score": 0-100   # 月0.5 / 周0.3 / 日0.2 加权
  }
"""

from __future__ import annotations

import numpy as np
import pandas as pd
from datetime import date

from common.interfaces import TimeframeAnalyzer as _TFA  # 契约基类（仅用于 isinstance 检查/类型标注）

__all__ = ["MultiTimeframeAnalyzer", "TIMEFRAMES", "TF_WEIGHTS"]


# 参与评分的时间维度与权重（长周期趋势更具可信度指示意义，权重更高）
TIMEFRAMES = ("day", "week", "month")
TF_WEIGHTS = {"month": 0.50, "week": 0.30, "day": 0.20}
TF_LABEL = {"day": "日K", "week": "周K", "month": "月K"}
ANNUALIZE = {"day": 252, "week": 52, "month": 12}  # 年化因子


class MultiTimeframeAnalyzer(_TFA):
    """多周期动态分析默认实现。"""

    # -------- 重采样（确定性分桶，避免 pandas resample API 差异） -------- #
    def resample(self, kline, tf):
        if tf == "day" or not kline:
            return list(kline)
        out, order, seen = {}, [], set()
        for b in kline:
            d = str(b.get("date", ""))[:10]
            if d < "2000-01-01":
                continue
            if tf == "week":
                try:
                    y, w, _ = date.fromisoformat(d).isocalendar()
                    key = (y, w)
                except Exception:
                    continue
            else:  # month
                key = d[:7]  # YYYY-MM
            if key not in seen:
                seen.add(key)
                order.append(key)
                out[key] = {
                    "open": float(b.get("open", 0) or 0),
                    "high": float(b.get("high", 0) or 0),
                    "low": float(b.get("low", 0) or 0),
                    "close": float(b.get("close", 0) or 0),
                    "volume": float(b.get("volume", 0) or 0),
                    "amount": float(b.get("amount", 0) or 0),
                    "_d": d,
                }
            else:
                o = out[key]
                o["high"] = max(o["high"], float(b.get("high", 0) or 0))
                o["low"] = min(o["low"], float(b.get("low", 0) or 0))
                o["close"] = float(b.get("close", 0) or 0)
                o["volume"] += float(b.get("volume", 0) or 0)
                o["amount"] += float(b.get("amount", 0) or 0)
        result = [{
            "date": out[k]["_d"],
            "open": out[k]["open"], "high": out[k]["high"],
            "low": out[k]["low"], "close": out[k]["close"],
            "volume": out[k]["volume"], "amount": out[k]["amount"],
        } for k in order]
        result.sort(key=lambda x: x["date"])
        return result

    # -------- 单周期指标 -------- #
    def analyze_timeframe(self, bars, tf):
        n = len(bars)
        if n < 2:
            return {
                "period": tf, "label": TF_LABEL.get(tf, tf), "n_bars": n,
                "last_close": (bars[-1]["close"] if n else None),
                "ma_trend": "数据不足", "volatility": None,
                "volume_change": None, "momentum": None,
                "trend_strength": 0.0, "signal": "中性", "score": 50.0,
            }
        close = np.array([float(b.get("close", 0) or 0) for b in bars], dtype=float)
        high = np.array([float(b.get("high", 0) or 0) for b in bars], dtype=float)
        low = np.array([float(b.get("low", 0) or 0) for b in bars], dtype=float)
        vol = np.array([float(b.get("volume", 0) or 0) for b in bars], dtype=float)

        # ---- 均线排列（自适应可用窗口：至少有 5/10/20）----
        ma = {w: pd.Series(close).rolling(w).mean().to_numpy()
             for w in (5, 10, 20, 60)}
        last = {w: ma[w][-1] for w in ma if not np.isnan(ma[w][-1])}
        ma_trend = "缠绕"
        ordered = [w for w in (5, 10, 20, 60) if w in last]
        if len(ordered) >= 3:
            vals = [last[w] for w in ordered]
            asc = all(vals[i] > vals[i + 1] for i in range(len(vals) - 1))
            desc = all(vals[i] < vals[i + 1] for i in range(len(vals) - 1))
            if asc:
                ma_trend = "多头排列"
            elif desc:
                ma_trend = "空头排列"

        # ---- 波动率 ----
        ret = close[1:] / close[:-1] - 1.0
        ann = ANNUALIZE.get(tf, 252)
        ann_vol = float(np.std(ret, ddof=1) * np.sqrt(ann) * 100) if len(ret) > 1 else 0.0
        base_vol = float(np.std(ret[-60:], ddof=1) * np.sqrt(ann) * 100) if len(ret) >= 20 else ann_vol
        vol_ratio = round((ann_vol / base_vol), 2) if base_vol > 1e-9 else 1.0
        volatility = {"ann_pct": round(ann_vol, 1),
                     "recent_vs_baseline": vol_ratio}

        # ---- 成交量变化 ----
        vma = pd.Series(vol).rolling(min(20, max(2, n))).mean().to_numpy()
        vma_last = vma[-1] if not np.isnan(vma[-1]) and vma[-1] > 0 else (vol[-1] or 1)
        vol_ratio_now = round(float(vol[-1] / vma_last), 2) if vma_last > 0 else 1.0
        # 量能趋势：近 5 根均值 / 前 5 根均值
        half = max(2, n // 6)
        if n >= half * 2 and vol[:half].sum() > 0:
            vol_trend = round(float(vol[-half:].mean() / vol[:half].mean() - 1.0), 3)
        else:
            vol_trend = 0.0
        # 价量配合：近期上涨且放量 → 健康；上涨但缩量 / 下跌放量 → 派发
        recent_ret = float(close[-1] / close[max(0, n - half)] - 1.0)
        if recent_ret > 0 and vol_trend > 0:
            vol_conf = "放量上涨(健康)"
        elif recent_ret < 0 and vol_trend > 0:
            vol_conf = "下跌放量(派发)"
        elif recent_ret > 0 and vol_trend < 0:
            vol_conf = "上涨缩量(动能不足)"
        else:
            vol_conf = "中性"
        volume_change = {"vol_ratio": vol_ratio_now,
                         "vol_trend_pct": round(vol_trend * 100, 1),
                         "confirmation": vol_conf}

        # ---- 动量 / 趋势强度 ----
        win = {"day": 20, "week": 13, "month": 6}.get(tf, 20)
        # 防止 n==2 时 win 取到 2 导致 close[-1-win] 越界(IndexError)。
        # n>=2 时 win 最多 n-1（保守下限 1），保证 close[-1-win] 索引合法。
        win = min(win, max(1, n - 1))
        momentum = float(close[-1] / close[-1 - win] - 1.0)
        ma60 = last.get(60, close.mean())
        slope = float(close[-1] / ma60 - 1.0) * 100 if ma60 > 0 else 0.0
        # 趋势强度：价格在近期高低区间的相对位置（0 底 ~ 100 顶）
        lo = float(low[-win:].min()) if n >= win else float(low.min())
        hi = float(high[-win:].max()) if n >= win else float(high.max())
        trend_strength = round(float((close[-1] - lo) / (hi - lo) * 100), 1) if hi > lo else 50.0

        # ---- 信号 + 评分 ----
        score = 50.0
        if ma_trend == "多头排列":
            score += 18.0
        elif ma_trend == "空头排列":
            score -= 18.0
        score += float(np.clip(slope, -15.0, 15.0))
        score += float(np.clip(momentum * 50.0, -10.0, 10.0))
        if ann_vol > 70.0:
            score -= 10.0          # 过度波动 = 风险折价
        elif ann_vol < 15.0:
            score += 3.0           # 低波动 = 平稳溢价
        score = float(np.clip(score, 5.0, 95.0))
        signal = "偏多" if score >= 60.0 else ("偏空" if score <= 40.0 else "中性")

        return {
            "period": tf, "label": TF_LABEL.get(tf, tf), "n_bars": n,
            "last_close": round(float(close[-1]), 2),
            "ma_trend": ma_trend,
            "volatility": volatility,
            "volume_change": volume_change,
            "momentum": round(momentum * 100, 1),
            "trend_strength": trend_strength,
            "signal": signal,
            "score": round(score, 1),
        }

    # -------- 多周期汇总 -------- #
    def analyze(self, kline, timeframes=None):
        tfs = list(timeframes or TIMEFRAMES)
        frames = {}
        for tf in tfs:
            bars = self.resample(kline, tf)
            frames[tf] = self.analyze_timeframe(bars, tf)

        # 跨周期共振
        sig = {tf: frames[tf]["score"] for tf in frames}
        if all(v >= 60 for v in sig.values()):
            alignment = "日周月共振·多头"
        elif all(v <= 40 for v in sig.values()):
            alignment = "日周月共振·空头"
        else:
            alignment = "周期分化"

        composite = 0.0
        wsum = 0.0
        for tf, w in TF_WEIGHTS.items():
            if tf in frames:
                composite += frames[tf]["score"] * w
                wsum += w
        composite = composite / wsum if wsum > 0 else 50.0

        return {
            "timeframes": frames,
            "alignment": alignment,
            "composite_quant_score": round(composite, 1),
        }
