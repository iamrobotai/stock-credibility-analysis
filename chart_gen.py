# -*- coding: utf-8 -*-
"""
chart_gen.py - 增强版图表生成器 v2.4
1. 标注涨跌幅较大时间点（日涨跌>5% 或波段涨跌>15%）
2. 关键波段放大插图
3. 行业多股走势叠加图
4. 技术指标叠加（MACD/KDJ/RSI/BOLL 子图）
"""
import json, os, numpy as np
from datetime import datetime as dt


def _setup_matplotlib():
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    import matplotlib.dates as mdates
    from matplotlib.patches import FancyBboxPatch
    plt.rcParams["font.sans-serif"] = ["SimHei", "Microsoft YaHei", "SimSun"]
    plt.rcParams["axes.unicode_minus"] = False
    return plt, mdates


def gen_stock_chart(code, kline, segments, outdir="data", threshold_daily=5.0, threshold_seg=15.0):
    """
    生成增强版价格曲线图：
    - 标注日涨跌幅超过 threshold_daily% 的交易日
    - 标注波段涨跌幅超过 threshold_seg% 的波段
    - 对最大涨跌波段做放大插图
    """
    if not kline:
        return None
    plt, mdates = _setup_matplotlib()

    dates = [dt.strptime(b["date"], "%Y-%m-%d") for b in kline]
    closes = [b["close"] for b in kline]
    highs = [b.get("high", b["close"]) for b in kline]
    lows = [b.get("low", b["close"]) for b in kline]

    # 计算日涨跌幅
    daily_changes = []
    for i in range(1, len(kline)):
        prev_close = kline[i - 1]["close"]
        curr_close = kline[i]["close"]
        if prev_close > 0:
            pct = (curr_close - prev_close) / prev_close * 100
            daily_changes.append((i, pct))

    # 找出大幅波动日
    big_moves = [(i, pct) for i, pct in daily_changes if abs(pct) >= threshold_daily]

    # 找出大幅波段
    big_segs = [s for s in segments if abs(s.get("pct", 0)) >= threshold_seg]

    # ---- 主图 + 放大插图 ----
    has_inset = len(big_segs) > 0
    if has_inset:
        fig = plt.figure(figsize=(12, 5))
        ax = fig.add_axes([0.08, 0.15, 0.62, 0.75])  # 主图
        ax_inset = fig.add_axes([0.72, 0.45, 0.26, 0.45])  # 放大图
    else:
        fig, ax = plt.subplots(figsize=(10, 4))

    # 主曲线
    ax.plot(dates, closes, color="#333333", linewidth=0.8, label="收盘价(前复权)")
    ax.fill_between(dates, closes, min(closes) * 0.95, alpha=0.05, color="#333333")

    # 波段背景色
    colors = {"涨": "#DC143C", "跌": "#228B22"}
    for seg in segments:
        try:
            s = dt.strptime(seg["start_date"], "%Y-%m-%d")
            e = dt.strptime(seg["end_date"], "%Y-%m-%d")
            ax.axvspan(s, e, alpha=0.10, color=colors.get(seg["direction"], "#888"))
            # 大幅波段标注
            if abs(seg.get("pct", 0)) >= threshold_seg:
                ax.annotate(
                    f"★ {seg['id']} {seg['direction']}{seg['pct']:+.1f}%",
                    xy=(e, seg["end_price"]),
                    xytext=(15, 10 if seg["direction"] == "涨" else -15),
                    textcoords="offset points",
                    fontsize=8, fontweight="bold",
                    color=colors.get(seg["direction"], "#333"),
                    arrowprops=dict(arrowstyle="->", color=colors.get(seg["direction"], "#333"), lw=1.2),
                    bbox=dict(boxstyle="round,pad=0.2", facecolor="white", edgecolor=colors.get(seg["direction"], "#333"), alpha=0.85),
                )
            else:
                ax.annotate(
                    f"{seg['id']} {seg['pct']:+.0f}%",
                    xy=(e, seg["end_price"]),
                    fontsize=6, color=colors.get(seg["direction"], "#333"),
                )
        except Exception:
            continue

    # 标注大幅波动日
    for idx, pct in big_moves:
        if idx < len(dates):
            d = dates[idx]
            c = closes[idx]
            marker_color = "#FF4444" if pct > 0 else "#00AA00"
            ax.plot(d, c, "v" if pct < 0 else "^", color=marker_color, markersize=6, zorder=5)
            ax.annotate(
                f"{pct:+.1f}%",
                xy=(d, c),
                xytext=(0, 12 if pct > 0 else -12),
                textcoords="offset points",
                fontsize=6, color=marker_color, fontweight="bold",
                ha="center",
            )

    ax.set_title(f"{code} 价格分段曲线（★=大幅波段 ▲▼=日涨跌>{threshold_daily:.0f}%）", fontsize=10)
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%Y-%m"))
    ax.xaxis.set_major_locator(mdates.MonthLocator(interval=3))
    ax.legend(fontsize=7, loc="upper left")
    ax.grid(True, alpha=0.3)
    fig.autofmt_xdate()

    # ---- 放大插图：最大涨跌波段 ----
    if has_inset:
        big_segs_sorted = sorted(big_segs, key=lambda s: abs(s.get("pct", 0)), reverse=True)
        zoom_seg = big_segs_sorted[0]
        try:
            s_date = dt.strptime(zoom_seg["start_date"], "%Y-%m-%d")
            e_date = dt.strptime(zoom_seg["end_date"], "%Y-%m-%d")
            # 找到对应索引范围
            s_idx = next((i for i, d in enumerate(dates) if d >= s_date), 0)
            e_idx = next((i for i, d in enumerate(dates) if d >= e_date), len(dates) - 1)
            e_idx = min(e_idx + 1, len(dates) - 1)

            zoom_dates = dates[s_idx:e_idx + 1]
            zoom_closes = closes[s_idx:e_idx + 1]
            zoom_highs = highs[s_idx:e_idx + 1]
            zoom_lows = lows[s_idx:e_idx + 1]

            ax_inset.plot(zoom_dates, zoom_closes, color="#333", linewidth=1.2)
            ax_inset.fill_between(zoom_dates, zoom_closes, min(zoom_closes) * 0.98, alpha=0.1, color=colors.get(zoom_seg["direction"], "#888"))
            ax_inset.set_title(f"放大: {zoom_seg['id']} {zoom_seg['direction']}{zoom_seg['pct']:+.1f}%", fontsize=8, fontweight="bold")
            ax_inset.xaxis.set_major_formatter(mdates.DateFormatter("%m-%d"))
            ax_inset.tick_params(axis="both", labelsize=6)
            ax_inset.grid(True, alpha=0.3)

            # 在放大图中也标注日内大幅波动
            for idx, pct in big_moves:
                if s_idx <= idx <= e_idx:
                    zd = dates[idx]
                    zc = closes[idx]
                    mc = "#FF4444" if pct > 0 else "#00AA00"
                    ax_inset.plot(zd, zc, "v" if pct < 0 else "^", color=mc, markersize=5, zorder=5)
                    ax_inset.annotate(f"{pct:+.1f}%", xy=(zd, zc),
                                      xytext=(0, 8 if pct > 0 else -8),
                                      textcoords="offset points",
                                      fontsize=5, color=mc, ha="center")
        except Exception:
            ax_inset.text(0.5, 0.5, "放大区数据不足", ha="center", va="center", transform=ax_inset.transAxes, fontsize=8)

    path = os.path.join(outdir, f"{code}_chart.png")
    fig.savefig(path, dpi=150, bbox_inches="tight")
    plt.close(fig)
    return path


def gen_industry_chart(stocks_data, industry_name, outdir="data"):
    """
    行业多股走势叠加图
    stocks_data: [{"code": "002371", "name": "北方华创", "kline": [...]}]
    """
    if not stocks_data:
        return None
    plt, mdates = _setup_matplotlib()

    fig, ax = plt.subplots(figsize=(12, 6))

    # 颜色循环
    colors_cycle = [
        "#e6194B", "#3cb44b", "#4363d8", "#f58231", "#911eb4",
        "#42d4f4", "#f032e6", "#bfef45", "#fabebe", "#469990",
        "#e6beff", "#9A6324", "#800000", "#808000", "#000075",
    ]

    # 归一化基准日：取所有股票中最晚的起始日
    all_start_dates = []
    for s in stocks_data:
        if s.get("kline"):
            all_start_dates.append(dt.strptime(s["kline"][0]["date"], "%Y-%m-%d"))
    if not all_start_dates:
        return None
    base_date = max(all_start_dates)

    for i, s in enumerate(stocks_data):
        kline = s.get("kline", [])
        if not kline:
            continue
        name = s.get("name", s["code"])
        code = s["code"]

        # 从基准日开始截取
        dates = []
        closes = []
        for b in kline:
            d = dt.strptime(b["date"], "%Y-%m-%d")
            if d >= base_date:
                dates.append(d)
                closes.append(b["close"])

        if len(closes) < 2:
            continue

        # 归一化为相对涨幅 (%)
        base_price = closes[0]
        if base_price <= 0:
            continue
        pct_changes = [(c - base_price) / base_price * 100 for c in closes]

        color = colors_cycle[i % len(colors_cycle)]
        ax.plot(dates, pct_changes, color=color, linewidth=1.0, alpha=0.85, label=f"{name}({code})")

        # 标注最终涨跌幅
        final_pct = pct_changes[-1]
        if dates:
            ax.annotate(
                f"{final_pct:+.1f}%",
                xy=(dates[-1], final_pct),
                fontsize=7, color=color, fontweight="bold",
                va="center",
            )

    ax.axhline(y=0, color="#666", linewidth=0.5, linestyle="--")
    ax.set_title(f"{industry_name} - 行业个股走势对比（归一化%）", fontsize=12)
    ax.set_ylabel("相对涨跌幅 (%)", fontsize=10)
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%Y-%m"))
    ax.xaxis.set_major_locator(mdates.MonthLocator(interval=3))
    ax.legend(fontsize=7, loc="upper left", ncol=2)
    ax.grid(True, alpha=0.3)
    fig.autofmt_xdate()
    fig.tight_layout()

    safe_name = industry_name.replace("/", "_").replace(" ", "")
    path = os.path.join(outdir, f"industry_{safe_name}_chart.png")
    fig.savefig(path, dpi=150)
    plt.close(fig)
    return path


if __name__ == "__main__":
    import sys
    code = sys.argv[1] if len(sys.argv) > 1 else "002371"
    datadir = "data"
    raw_path = os.path.join(datadir, f"{code}_raw.json")
    seg_path = os.path.join(datadir, f"{code}_segments.json")
    if os.path.exists(raw_path):
        raw = json.load(open(raw_path, encoding="utf-8"))
        segs = json.load(open(seg_path, encoding="utf-8")) if os.path.exists(seg_path) else []
        path = gen_stock_chart(code, raw.get("kline", []), segs, datadir)
        print(f"Chart saved: {path}")
    else:
        print(f"No data for {code}")


def gen_technical_chart(code, kline, outdir="data"):
    """
    技术指标叠加图: 价格+成交量 + MACD + KDJ + RSI/BOLL
    """
    if not kline:
        return None
    plt, mdates = _setup_matplotlib()

    dates = [dt.strptime(b["date"], "%Y-%m-%d") for b in kline]
    closes = np.array([b["close"] for b in kline])
    highs = np.array([b["high"] for b in kline])
    lows = np.array([b["low"] for b in kline])
    opens = np.array([b["open"] for b in kline])
    volumes = np.array([b.get("volume", 0) for b in kline])

    try:
        from technical import compute_macd, compute_kdj, compute_rsi, compute_boll
        macd = compute_macd(closes)
        kdj = compute_kdj(highs, lows, closes)
        rsi = compute_rsi(closes)
        boll = compute_boll(closes)
    except Exception:
        return None

    # 4 行子图
    fig, axes = plt.subplots(4, 1, figsize=(14, 10), sharex=True,
                              gridspec_kw={"height_ratios": [3, 1.2, 1.2, 1.2]})

    ax1, ax2, ax3, ax4 = axes

    # ---- 子图1: K线 + 布林带 ----
    # 蜡烛图简化：阳线白色，阴线深色
    for i in range(len(dates)):
        if closes[i] >= opens[i]:
            color = "#DC143C"
            body_bottom = opens[i]
            body_top = closes[i]
        else:
            color = "#228B22"
            body_bottom = closes[i]
            body_top = opens[i]
        ax1.plot([dates[i], dates[i]], [lows[i], highs[i]], color=color, linewidth=0.6)
        ax1.plot([dates[i], dates[i]], [body_bottom, body_top], color=color, linewidth=3)

    # 布林带
    boll_upper = np.array(boll["UPPER"])
    boll_mid = np.array(boll["MIDDLE"])
    boll_lower = np.array(boll["LOWER"])
    valid = ~np.isnan(boll_mid)
    if np.any(valid):
        ax1.plot(np.array(dates)[valid], boll_mid[valid], color="#FF9800", linewidth=0.8, alpha=0.7, label="BOLL中轨")
        ax1.plot(np.array(dates)[valid], boll_upper[valid], color="#FF9800", linewidth=0.5, alpha=0.4, linestyle=":")
        ax1.plot(np.array(dates)[valid], boll_lower[valid], color="#FF9800", linewidth=0.5, alpha=0.4, linestyle=":")
        ax1.fill_between(np.array(dates)[valid], boll_upper[valid], boll_lower[valid], alpha=0.05, color="#FF9800")

    ax1.set_title(f"{code} 技术分析（K线+布林带/MACD/KDJ/RSI）", fontsize=10)
    ax1.legend(fontsize=7, loc="upper left")
    ax1.grid(True, alpha=0.3)

    # ---- 子图2: MACD ----
    dif = np.array(macd["DIF"])
    dea = np.array(macd["DEA"])
    macd_bar = np.array(macd["MACD"])
    ax2.bar(dates, macd_bar, width=0.8, color=np.where(macd_bar >= 0, "#DC143C", "#228B22"), alpha=0.6)
    ax2.plot(dates, dif, color="#FFFFFF", linewidth=0.8, label="DIF")
    ax2.plot(dates, dea, color="#FF9800", linewidth=0.8, label="DEA")
    ax2.axhline(y=0, color="#666666", linewidth=0.3)
    ax2.set_ylabel("MACD", fontsize=8)
    ax2.legend(fontsize=6, loc="upper left")
    ax2.grid(True, alpha=0.3)

    # ---- 子图3: KDJ ----
    k = np.array(kdj["K"])
    d = np.array(kdj["D"])
    j = np.array(kdj["J"])
    ax3.plot(dates, k, color="#FFFFFF", linewidth=0.8, label="K")
    ax3.plot(dates, d, color="#FF9800", linewidth=0.8, label="D")
    ax3.plot(dates, j, color="#E040FB", linewidth=0.8, label="J")
    ax3.axhline(y=80, color="#DC143C", linewidth=0.3, linestyle=":")
    ax3.axhline(y=20, color="#228B22", linewidth=0.3, linestyle=":")
    ax3.set_ylabel("KDJ", fontsize=8)
    ax3.legend(fontsize=6, loc="upper left")
    ax3.grid(True, alpha=0.3)

    # ---- 子图4: RSI ----
    rsi6 = np.array(rsi["RSI"])
    ax4.plot(dates, rsi6, color="#58A6FF", linewidth=0.8, label="RSI(6)")
    ax4.axhline(y=70, color="#DC143C", linewidth=0.3, linestyle=":")
    ax4.axhline(y=30, color="#228B22", linewidth=0.3, linestyle=":")
    ax4.axhline(y=50, color="#666666", linewidth=0.3, linestyle="--")
    ax4.set_ylabel("RSI", fontsize=8)
    ax4.legend(fontsize=6, loc="upper left")
    ax4.grid(True, alpha=0.3)

    # 共享 X 轴
    ax4.xaxis.set_major_formatter(mdates.DateFormatter("%Y-%m"))
    ax4.xaxis.set_major_locator(mdates.MonthLocator(interval=3))
    fig.autofmt_xdate()
    fig.tight_layout()

    path = os.path.join(outdir, f"{code}_tech_chart.png")
    fig.savefig(path, dpi=150)
    plt.close(fig)
    return path
