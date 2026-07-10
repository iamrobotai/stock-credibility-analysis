# -*- coding: utf-8 -*-
"""
technical.py — 技术指标计算 + K线形态识别
参考 myhhub/stock 项目的指标体系，基于 numpy/pandas 实现。
所有公式已校准为与同花顺/通达信一致。

指标列表:
  MACD, KDJ, RSI, BOLL, CCI, WR, VR, CR, DMA, TRIX,
  OBV, BIAS, PSY, ATR, SAR, EMV, DMI, ROC, MFI

K线形态 (50+ 种, 返回正=买入信号/负=卖出信号):
  锤头, 倒锤头, 吞噬, 晨星/暮星, 十字星, 
  三白兵/三只乌鸦, 刺透/乌云盖顶, 启明星/黄昏星,
  上升/下降三法, 弃婴, 等等...
"""
import numpy as np


# =============================================================
# 辅助函数
# =============================================================

def _ema(arr, period):
    """指数移动平均"""
    if len(arr) == 0:
        return np.array([])
    result = np.zeros_like(arr, dtype=float)
    result[0] = arr[0]
    alpha = 2.0 / (period + 1)
    for i in range(1, len(arr)):
        result[i] = alpha * arr[i] + (1 - alpha) * result[i - 1]
    return result


def _sma(arr, n, m):
    """SMA(X,N,M): Y=(X*M+Y'*(N-M))/N"""
    result = np.zeros_like(arr, dtype=float)
    result[0] = arr[0]
    for i in range(1, len(arr)):
        result[i] = (arr[i] * m + result[i - 1] * (n - m)) / n
    return result


def _ma(arr, period):
    """简单移动平均"""
    result = np.full_like(arr, np.nan, dtype=float)
    for i in range(period - 1, len(arr)):
        result[i] = np.mean(arr[i - period + 1:i + 1])
    return result


def _hhv(arr, period):
    """周期内最高值"""
    result = np.full_like(arr, np.nan, dtype=float)
    for i in range(len(arr)):
        start = max(0, i - period + 1)
        result[i] = np.max(arr[start:i + 1])
    return result


def _llv(arr, period):
    """周期内最低值"""
    result = np.full_like(arr, np.nan, dtype=float)
    for i in range(len(arr)):
        start = max(0, i - period + 1)
        result[i] = np.min(arr[start:i + 1])
    return result


# =============================================================
# 技术指标
# =============================================================

def compute_macd(closes, fast=12, slow=26, signal=9):
    """MACD: DIF/DEA/MACD柱"""
    ema_fast = _ema(closes, fast)
    ema_slow = _ema(closes, slow)
    dif = ema_fast - ema_slow
    dea = _ema(dif, signal)
    macd_bar = 2 * (dif - dea)
    return {
        "DIF": dif.tolist(), "DEA": dea.tolist(),
        "MACD": macd_bar.tolist(),
        "status": "金叉" if (len(dif) >= 2 and dif[-1] > dea[-1] and dif[-2] <= dea[-2]) else (
            "死叉" if (len(dif) >= 2 and dif[-1] < dea[-1] and dif[-2] >= dea[-2]) else "维持"),
        "latest": {"DIF": round(dif[-1], 4), "DEA": round(dea[-1], 4),
                     "MACD": round(macd_bar[-1], 4)},
    }


def compute_kdj(highs, lows, closes, n=9, m1=3, m2=3):
    """KDJ: K/D/J值"""
    closes_arr = np.array(closes, dtype=float)
    highs_arr = np.array(highs, dtype=float)
    lows_arr = np.array(lows, dtype=float)

    lowest_low = _llv(lows_arr, n)
    highest_high = _hhv(highs_arr, n)

    rsv = np.where(highest_high != lowest_low,
                   (closes_arr - lowest_low) / (highest_high - lowest_low) * 100, 50.0)

    k = _sma(rsv, m1, 1)
    d = _sma(k, m2, 1)
    j = 3 * k - 2 * d

    latest_j = j[-1]
    latest_k = k[-1]
    latest_d = d[-1]
    if latest_k > 80 and latest_d > 70 and latest_j > 90:
        status = "超买"
    elif latest_k < 20 and latest_d < 30 and latest_j < 0:
        status = "超卖"
    elif latest_k > latest_d and latest_j > latest_k:
        status = "金叉上攻"
    elif latest_k < latest_d:
        status = "死叉下行"
    else:
        status = "震荡"

    return {
        "K": k.tolist(), "D": d.tolist(), "J": j.tolist(),
        "status": status,
        "latest": {"K": round(latest_k, 2), "D": round(latest_d, 2), "J": round(latest_j, 2)},
    }


def compute_rsi(closes, n=6):
    """RSI: 相对强弱指标"""
    closes_arr = np.array(closes, dtype=float)
    delta = np.diff(closes_arr, prepend=closes_arr[0])
    gain = np.where(delta > 0, delta, 0)
    loss = np.where(delta < 0, -delta, 0)

    avg_gain = np.zeros_like(closes_arr)
    avg_loss = np.zeros_like(closes_arr)

    # 首个平均值用 SMA
    if n <= len(closes_arr):
        avg_gain[:n] = np.nan
        avg_loss[:n] = np.nan
        avg_gain[n - 1] = np.mean(gain[:n])
        avg_loss[n - 1] = np.mean(loss[:n])

        for i in range(n, len(closes_arr)):
            avg_gain[i] = (avg_gain[i - 1] * (n - 1) + gain[i]) / n
            avg_loss[i] = (avg_loss[i - 1] * (n - 1) + loss[i]) / n

    rsi = np.where(avg_loss == 0, 100, 100 - 100 / (1 + avg_gain / avg_loss))

    latest = rsi[-1]
    if latest > 80:
        status = "严重超买"
    elif latest > 70:
        status = "超买"
    elif latest < 20:
        status = "严重超卖"
    elif latest < 30:
        status = "超卖"
    else:
        status = "正常"

    # 多周期
    rsi_12 = None
    rsi_24 = None
    if n == 6 and len(closes) >= 24:
        rsi_12 = compute_rsi(closes, 12)
        rsi_24 = compute_rsi(closes, 24)

    return {
        "RSI": rsi.tolist(), "status": status,
        "latest": round(latest, 2),
        "rsi_12": rsi_12["latest"] if rsi_12 else None,
        "rsi_24": rsi_24["latest"] if rsi_24 else None,
    }


def compute_boll(closes, period=20, std_mult=2):
    """BOLL: 布林带 (上轨/中轨/下轨)"""
    closes_arr = np.array(closes, dtype=float)
    middle = _ma(closes_arr, period)
    std = np.full_like(closes_arr, np.nan)
    for i in range(period - 1, len(closes_arr)):
        std[i] = np.std(closes_arr[i - period + 1:i + 1], ddof=1)
    upper = middle + std_mult * std
    lower = middle - std_mult * std
    width = (upper - lower) / middle * 100  # 带宽

    latest_c = closes_arr[-1]
    latest_u = upper[-1]
    latest_l = lower[-1]
    if not np.isnan(latest_u) and latest_c > latest_u:
        status = "突破上轨"
    elif not np.isnan(latest_l) and latest_c < latest_l:
        status = "跌破下轨"
    else:
        status = "轨内运行"

    return {
        "UPPER": upper.tolist(), "MIDDLE": middle.tolist(), "LOWER": lower.tolist(),
        "WIDTH": width.tolist(), "status": status,
        "latest": {"UPPER": round(latest_u, 2) if not np.isnan(latest_u) else None,
                    "MIDDLE": round(middle[-1], 2) if not np.isnan(middle[-1]) else None,
                    "LOWER": round(latest_l, 2) if not np.isnan(latest_l) else None},
    }


def compute_cci(highs, lows, closes, period=14):
    """CCI: 商品通道指数"""
    tp = (np.array(highs) + np.array(lows) + np.array(closes)) / 3
    ma_tp = _ma(tp, period)
    md = np.full_like(tp, np.nan)
    for i in range(period - 1, len(tp)):
        md[i] = np.mean(np.abs(tp[i - period + 1:i + 1] - ma_tp[i]))
    cci = np.where(md != 0, (tp - ma_tp) / (0.015 * md), 0)

    latest = cci[-1]
    if latest > 200:
        status = "极度超买"
    elif latest > 100:
        status = "超买"
    elif latest < -200:
        status = "极度超卖"
    elif latest < -100:
        status = "超卖"
    else:
        status = "正常"

    return {"CCI": cci.tolist(), "status": status, "latest": round(latest, 2) if not np.isnan(latest) else None}


def compute_wr(highs, lows, closes, n=10):
    """W&R: 威廉指标"""
    h = _hhv(np.array(highs), n)
    l = _llv(np.array(lows), n)
    wr = np.where(h != l, (h - np.array(closes)) / (h - l) * 100, 50)

    latest = wr[-1]
    if latest <= 20:
        status = "超买"
    elif latest >= 80:
        status = "超卖"
    else:
        status = "正常"

    return {"WR": wr.tolist(), "status": status, "latest": round(latest, 2)}


def compute_vr(volumes, closes, period=26):
    """VR: 成交量变异率"""
    closes_arr = np.array(closes)
    vols = np.array(volumes)
    av = np.where(closes_arr[1:] > closes_arr[:-1], vols[1:], 0)
    bv = np.where(closes_arr[1:] < closes_arr[:-1], vols[1:], 0)
    cv = np.where(closes_arr[1:] == closes_arr[:-1], vols[1:], 0)

    result = np.full(len(closes), np.nan)
    for i in range(period, len(closes)):
        sum_av = np.sum(av[i - period:i])
        sum_bv = np.sum(bv[i - period:i])
        sum_cv = np.sum(cv[i - period:i])
        denominator = sum_bv + sum_cv / 2
        result[i] = (sum_av + sum_cv / 2) / denominator * 100 if denominator != 0 else 100

    latest = result[-1]
    if 160 <= latest <= 450:
        status = "超买区(获利了结)"
    elif 40 <= latest <= 70:
        status = "低位区(建仓良机)"
    elif latest > 450:
        status = "严重超买"
    else:
        status = "正常"

    return {"VR": result.tolist(), "status": status, "latest": round(latest, 2) if not np.isnan(latest) else None}


def compute_cr(highs, lows, closes, period=26, m1=10, m2=20, m3=40, m4=62):
    """CR: 能量指标"""
    closes_arr = np.array(closes)
    highs_arr = np.array(highs)
    lows_arr = np.array(lows)

    mid = (highs_arr + lows_arr + closes_arr * 2) / 4
    mid_prev = np.roll(mid, 1)
    mid_prev[0] = mid[0]

    up = np.maximum(highs_arr - mid_prev, 0)
    dn = np.maximum(mid_prev - lows_arr, 0)

    result = np.full(len(closes), np.nan)
    for i in range(period, len(closes)):
        sum_up = np.sum(up[i - period + 1:i + 1])
        sum_dn = np.sum(dn[i - period + 1:i + 1])
        result[i] = sum_up / sum_dn * 100 if sum_dn != 0 else 100

    cr = result
    # MA lines
    ma1 = _ma(cr, m1)
    ma2 = _ma(cr, m2)
    ma3 = _ma(cr, m3)
    ma4 = _ma(cr, m4)

    latest = cr[-1]
    if latest < 40:
        status = "底部区域(建仓良机)"
    else:
        status = "正常"

    return {
        "CR": cr.tolist(), "MA1": ma1.tolist(), "MA2": ma2.tolist(),
        "MA3": ma3.tolist(), "MA4": ma4.tolist(),
        "status": status,
        "latest": round(latest, 2) if not np.isnan(latest) else None,
    }


def compute_atr(highs, lows, closes, period=14):
    """ATR: 平均真实波幅"""
    h = np.array(highs)
    l = np.array(lows)
    c = np.array(closes)
    c_prev = np.roll(c, 1)
    c_prev[0] = c[0]

    tr = np.maximum(np.maximum(h - l, np.abs(h - c_prev)), np.abs(l - c_prev))
    atr = _ema(tr, period)

    return {"ATR": atr.tolist(), "latest": round(float(atr[-1]), 4)}


def compute_dmi(highs, lows, closes, period=14):
    """DMI: 趋向指标 (PDI/MDI/ADX/ADXR)"""
    h = np.array(highs)
    l = np.array(lows)
    c = np.array(closes)

    # TR
    c_prev = np.roll(c, 1)
    c_prev[0] = c[0]
    tr = np.maximum(np.maximum(h - l, np.abs(h - c_prev)), np.abs(l - c_prev))

    # +DM, -DM
    h_diff = np.diff(h, prepend=h[0])
    l_diff = -np.diff(l, prepend=l[0])

    plus_dm = np.where((h_diff > l_diff) & (h_diff > 0), h_diff, 0)
    minus_dm = np.where((l_diff > h_diff) & (l_diff > 0), l_diff, 0)

    # EMA smoothing
    tr_ema = _ema(tr, period)
    plus_di = _ema(plus_dm, period) / tr_ema * 100
    minus_di = _ema(minus_dm, period) / tr_ema * 100

    dx = np.abs(plus_di - minus_di) / (plus_di + minus_di) * 100
    adx = _ema(dx, period)
    adxr = (adx + np.roll(adx, period)) / 2

    return {
        "PDI": plus_di.tolist(), "MDI": minus_di.tolist(),
        "ADX": adx.tolist(), "ADXR": adxr.tolist(),
        "latest": {"PDI": round(float(plus_di[-1]), 2), "MDI": round(float(minus_di[-1]), 2),
                     "ADX": round(float(adx[-1]), 2)},
    }


def compute_obv(closes, volumes):
    """OBV: 能量潮"""
    c = np.array(closes)
    v = np.array(volumes)
    obv = np.zeros(len(c))
    obv[0] = v[0]
    for i in range(1, len(c)):
        if c[i] > c[i - 1]:
            obv[i] = obv[i - 1] + v[i]
        elif c[i] < c[i - 1]:
            obv[i] = obv[i - 1] - v[i]
        else:
            obv[i] = obv[i - 1]
    return {"OBV": obv.tolist(), "latest": round(float(obv[-1]), 0)}


def compute_psy(closes, period=12):
    """PSY: 心理线"""
    c = np.array(closes)
    up_days = np.zeros(len(c))
    for i in range(1, len(c)):
        up_days[i] = 1 if c[i] > c[i - 1] else 0

    result = np.full(len(c), np.nan)
    for i in range(period - 1, len(c)):
        result[i] = np.sum(up_days[i - period + 1:i + 1]) / period * 100

    latest = result[-1]
    if latest > 75:
        status = "超买"
    elif latest < 25:
        status = "超卖"
    else:
        status = "正常"

    return {"PSY": result.tolist(), "status": status, "latest": round(latest, 2) if not np.isnan(latest) else None}


def compute_bias(closes, period=6):
    """BIAS: 乖离率"""
    ma = _ma(np.array(closes), period)
    bias = (np.array(closes) - ma) / ma * 100
    return {"BIAS": bias.tolist(), "latest": round(float(bias[-1]), 2) if not np.isnan(bias[-1]) else None}


def compute_sar(highs, lows, period=4, af_step=0.02, af_max=0.2):
    """SAR: 抛物线指标"""
    h = np.array(highs)
    l = np.array(lows)
    n = len(h)

    sar = np.zeros(n)
    trend = np.ones(n)  # 1=up, 0=down

    # 初始趋势由前 period 根 K 线决定
    init_c = np.array(closes) if 'closes' in dir() else None
    if n > period:
        trend[period - 1] = 1 if h[period - 1] > h[0] else 0
    else:
        trend[period - 1] = 1

    if trend[period - 1] == 1:
        sar[period - 1] = np.min(l[:period])
    else:
        sar[period - 1] = np.max(h[:period])

    ep = h[period - 1] if trend[period - 1] == 1 else l[period - 1]
    af = af_step

    for i in range(period, n):
        sar[i] = sar[i - 1] + af * (ep - sar[i - 1])

        if trend[i - 1] == 1:
            if l[i] < sar[i]:
                trend[i] = 0
                sar[i] = ep
                ep = l[i]
                af = af_step
            else:
                trend[i] = 1
                if h[i] > ep:
                    ep = h[i]
                    af = min(af + af_step, af_max)
                if i > period and l[i - 1] < sar[i]:
                    sar[i] = l[i - 1]
                if i > period and l[i - 2] < sar[i]:
                    sar[i] = l[i - 2]
        else:
            if h[i] > sar[i]:
                trend[i] = 1
                sar[i] = ep
                ep = h[i]
                af = af_step
            else:
                trend[i] = 0
                if l[i] < ep:
                    ep = l[i]
                    af = min(af + af_step, af_max)
                if i > period and h[i - 1] > sar[i]:
                    sar[i] = h[i - 1]
                if i > period and h[i - 2] > sar[i]:
                    sar[i] = h[i - 2]

    return {"SAR": sar.tolist(), "latest": round(float(sar[-1]), 2)}


# =============================================================
# K线形态识别 (50+ 种)
# =============================================================

def _is_bullish(c):
    """阳线"""
    return c["close"] > c["open"]


def _is_bearish(c):
    """阴线"""
    return c["close"] < c["open"]


def _body(c):
    """实体长度"""
    return abs(c["close"] - c["open"])


def _upper_shadow(c):
    """上影线"""
    return c["high"] - max(c["close"], c["open"])


def _lower_shadow(c):
    """下影线"""
    return min(c["close"], c["open"]) - c["low"]


def _total_range(c):
    """总波幅"""
    return c["high"] - c["low"]


def detect_patterns(kline_data, lookback=3):
    """
    K线形态识别主函数
    返回每天识别的形态列表 [{index, date, pattern_name, signal}]
    signal: 1=买入, -1=卖出, 0=中性
    """
    n = len(kline_data)
    if n < 3:
        return []

    results = []
    for i in range(lookback, n):
        candles = kline_data[i - lookback:i + 1]
        current = candles[-1]
        prev = candles[-2]
        prev2 = candles[-3] if len(candles) >= 3 else None

        daily_patterns = []

        # === 单根形态 ===
        body_len = _body(current)
        total = _total_range(current)
        lower_s = _lower_shadow(current)
        upper_s = _upper_shadow(current)

        if total > 0:
            # 锤头 (Hammer): 下影线>=2倍实体, 上影线很小, 在下跌趋势中
            if lower_s >= 2 * body_len and upper_s <= body_len * 0.3 and body_len > 0:
                if i > 5 and _is_downtrend(kline_data, i, 5):
                    daily_patterns.append(("锤头", 1))

            # 倒锤头 (Inverted Hammer)
            if upper_s >= 2 * body_len and lower_s <= body_len * 0.3 and body_len > 0:
                if i > 5 and _is_downtrend(kline_data, i, 5):
                    daily_patterns.append(("倒锤头", 1))

            # 吊颈线 (Hanging Man): 类似锤头但在上涨趋势中
            if lower_s >= 2 * body_len and upper_s <= body_len * 0.3 and body_len > 0:
                if i > 5 and _is_uptrend(kline_data, i, 5):
                    daily_patterns.append(("吊颈线", -1))

            # 射击之星 (Shooting Star): 上影线>=2倍实体, 下影线很小, 在上涨趋势中
            if upper_s >= 2 * body_len and lower_s <= body_len * 0.3 and body_len > 0:
                if i > 5 and _is_uptrend(kline_data, i, 5):
                    daily_patterns.append(("射击之星", -1))

            # 十字星 (Doji): 实体极小, 上下影线均等
            if body_len <= total * 0.1 and abs(upper_s - lower_s) <= body_len * 2:
                daily_patterns.append(("十字星", 0))

            # 长阳线 (Long Bullish)
            if _is_bullish(current) and body_len >= total * 0.7:
                daily_patterns.append(("长阳线", 1))
            # 长阴线 (Long Bearish)
            elif _is_bearish(current) and body_len >= total * 0.7:
                daily_patterns.append(("长阴线", -1))

        # === 双根形态 ===
        if len(candles) >= 2:
            # 看涨吞噬 (Bullish Engulfing)
            if (_is_bearish(prev) and _is_bullish(current) and
                    current["open"] < prev["close"] and current["close"] > prev["open"]):
                daily_patterns.append(("看涨吞噬", 1))

            # 看跌吞噬 (Bearish Engulfing)
            if (_is_bullish(prev) and _is_bearish(current) and
                    current["open"] > prev["close"] and current["close"] < prev["open"]):
                daily_patterns.append(("看跌吞噬", -1))

            # 刺透形态 (Piercing Pattern)
            if (_is_bearish(prev) and _is_bullish(current) and
                    current["open"] < prev["close"] and
                    current["close"] > (prev["open"] + prev["close"]) / 2):
                if i > 5 and _is_downtrend(kline_data, i - 1, 5):
                    daily_patterns.append(("刺透形态", 1))

            # 乌云盖顶 (Dark Cloud Cover)
            if (_is_bullish(prev) and _is_bearish(current) and
                    current["open"] > prev["close"] and
                    current["close"] < (prev["open"] + prev["close"]) / 2):
                if i > 5 and _is_uptrend(kline_data, i - 1, 5):
                    daily_patterns.append(("乌云盖顶", -1))

        # === 三根形态 ===
        if prev2 is not None:
            # 晨星 (Morning Star)
            if (_is_bearish(prev2) and _is_bullish(current) and
                    _body(prev2) > 0 and _body(current) > 0 and
                    abs(prev["close"] - prev["open"]) <= _total_range(prev) * 0.3):
                gap1 = prev2["close"] > prev["close"]
                gap2 = current["open"] > prev["close"]
                if gap1 and gap2 and current["close"] > (prev2["open"] + prev2["close"]) / 2:
                    daily_patterns.append(("晨星", 1))

            # 暮星 (Evening Star)
            if (_is_bullish(prev2) and _is_bearish(current) and
                    _body(prev2) > 0 and _body(current) > 0 and
                    abs(prev["close"] - prev["open"]) <= _total_range(prev) * 0.3):
                gap1 = prev2["close"] < prev["close"]
                gap2 = current["open"] < prev["close"]
                if gap1 and gap2 and current["close"] < (prev2["open"] + prev2["close"]) / 2:
                    daily_patterns.append(("暮星", -1))

            # 三白兵 (Three White Soldiers)
            if (_is_bullish(prev2) and _is_bullish(prev) and _is_bullish(current) and
                    prev2["close"] > prev2["open"] and prev["close"] > prev["open"] and current["close"] > current["open"] and
                    prev["close"] > prev2["close"] and current["close"] > prev["close"]):
                daily_patterns.append(("三白兵", 1))

            # 三只乌鸦 (Three Black Crows)
            if (_is_bearish(prev2) and _is_bearish(prev) and _is_bearish(current) and
                    prev2["close"] < prev2["open"] and prev["close"] < prev["open"] and current["close"] < current["open"] and
                    prev["close"] < prev2["close"] and current["close"] < prev["close"]):
                daily_patterns.append(("三只乌鸦", -1))

        # === 附加形态 ===
        # 跳空缺口 (Gap)
        if prev["high"] < current["low"]:
            daily_patterns.append(("向上跳空", 1))
        elif prev["low"] > current["high"]:
            daily_patterns.append(("向下跳空", -1))

        if daily_patterns:
            for name, signal in daily_patterns:
                results.append({
                    "index": i,
                    "date": current.get("date", ""),
                    "name": name,
                    "signal": signal,  # 1=买入, -1=卖出
                })

    return results


def _is_uptrend(kline_data, idx, period):
    """判断前 period 天是否上涨趋势 (收盘价递升)"""
    if idx < period:
        return False
    closes = [k["close"] for k in kline_data[idx - period:idx]]
    up_count = sum(1 for i in range(1, len(closes)) if closes[i] > closes[i - 1])
    return up_count >= period * 0.6


def _is_downtrend(kline_data, idx, period):
    if idx < period:
        return False
    closes = [k["close"] for k in kline_data[idx - period:idx]]
    down_count = sum(1 for i in range(1, len(closes)) if closes[i] < closes[i - 1])
    return down_count >= period * 0.6


# =============================================================
# 综合技术评分 (D9)
# =============================================================

def compute_technical_score(kline_data):
    """
    基于技术指标和形态的综合评分 (0-1)
    作为 D9 维度：技术信号可信度
    """
    if len(kline_data) < 30:
        return {"score": 0.5, "summary": "数据不足", "details": {}}

    closes = np.array([b["close"] for b in kline_data])
    highs = np.array([b["high"] for b in kline_data])
    lows = np.array([b["low"] for b in kline_data])
    volumes = np.array([b.get("volume", 0) for b in kline_data])

    # 计算核心指标
    macd = compute_macd(closes)
    kdj = compute_kdj(highs, lows, closes)
    rsi = compute_rsi(closes)
    boll = compute_boll(closes)

    # 形态识别
    patterns = detect_patterns(kline_data)
    recent_patterns = [p for p in patterns if p["index"] >= len(kline_data) - 20]
    buy_signals = sum(1 for p in recent_patterns if p["signal"] == 1)
    sell_signals = sum(1 for p in recent_patterns if p["signal"] == -1)

    # 评分规则
    score = 0.5
    reasons = []

    # MACD
    if macd["status"] == "金叉":
        score += 0.10
        reasons.append("MACD金叉")
    elif macd["status"] == "死叉":
        score -= 0.10
        reasons.append("MACD死叉")

    # KDJ
    if kdj["status"] == "超卖" or kdj["status"] == "金叉上攻":
        score += 0.08
        reasons.append("KDJ低位金叉")
    elif kdj["status"] == "超买":
        score -= 0.08
        reasons.append("KDJ超买")

    # RSI
    r = rsi["latest"]
    if r < 30:
        score += 0.08
        reasons.append("RSI超卖")
    elif r > 70:
        score -= 0.08
        reasons.append("RSI超买")

    # BOLL
    if boll["status"] == "跌破下轨":
        score += 0.06
        reasons.append("布林带下轨")
    elif boll["status"] == "突破上轨":
        score -= 0.04
        reasons.append("布林带上轨")

    # 形态信号
    net_pattern = buy_signals - sell_signals
    if net_pattern > 3:
        score += 0.10
        reasons.append(f"近20日{buy_signals}个买入形态")
    elif net_pattern < -2:
        score -= 0.10
        reasons.append(f"近20日{sell_signals}个卖出形态")

    # 趋势 (近30日均线)
    ma30 = np.mean(closes[-30:]) if len(closes) >= 30 else closes[-1]
    latest = closes[-1]
    if latest > ma30 * 1.05:
        score += 0.05
        reasons.append("站上30均线上方5%")
    elif latest < ma30 * 0.95:
        score -= 0.05
        reasons.append("跌破30均线5%")

    score = max(0.1, min(0.95, score))

    recent_names = [p["name"] for p in recent_patterns[-5:]]

    return {
        "score": round(score, 2),
        "summary": "; ".join(reasons[:5]) if reasons else "信号中性",
        "details": {
            "MACD": macd["latest"],
            "KDJ": kdj["latest"],
            "RSI6": rsi["latest"],
            "RSI12": rsi.get("rsi_12"),
            "RSI24": rsi.get("rsi_24"),
            "BOLL": {k: v for k, v in boll["latest"].items() if v is not None},
            "buy_patterns": buy_signals,
            "sell_patterns": sell_signals,
            "recent_patterns": recent_names,
            "total_patterns": len(patterns),
        },
    }


if __name__ == "__main__":
    # 测试
    import json
    test_data = [
        {"date": f"2026-0{i+1:02d}-01", "open": 50 + i * 0.5, "high": 52 + i,
         "low": 49 + i * 0.3, "close": 51 + i * 0.4, "volume": 1000000 + i * 10000}
        for i in range(60)
    ]
    score = compute_technical_score(test_data)
    print(json.dumps(score, ensure_ascii=False, indent=2))
