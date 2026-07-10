# -*- coding: utf-8 -*-
import json, csv, os
import matplotlib
matplotlib.rcParams['axes.unicode_minus'] = False
matplotlib.rcParams['font.sans-serif'] = ['Microsoft YaHei', 'SimHei', 'Noto Sans SC', 'SimSun']
from matplotlib import font_manager as fm

BASE = r"C:\Users\outzb\WorkBuddy\Claw\stock-credibility-analysis"
OUT = BASE
# ensure CJK font registered (msyh.ttc)
for fp in [r"C:\WINDOWS\Fonts\msyh.ttc", r"C:\WINDOWS\Fonts\simhei.ttf", r"C:\WINDOWS\Fonts\NotoSansSC-VF.ttf"]:
    if os.path.exists(fp):
        try:
            fm.fontManager.addfont(fp)
        except Exception:
            pass

RED = "#d62728"    # 涨 -> 红
GREEN = "#2ca02c"  # 跌 -> 绿
BLUE = "#1f77b4"
GREY = "#555555"

# ---------------- 1) 价格分段曲线 ----------------
import datetime as dt
segs = json.load(open(os.path.join(BASE, "segments.json"), encoding="utf-8"))
dates, closes = [], []
with open(os.path.join(BASE, "kline_300308.csv"), encoding="utf-8-sig") as f:
    for row in csv.DictReader(f):
        dates.append(dt.datetime.strptime(row["date"], "%Y-%m-%d"))
        closes.append(float(row["close"]))

import matplotlib.pyplot as plt
fig, ax = plt.subplots(figsize=(11, 5.2), dpi=150)
for s in segs:
    a, b = s["idx_start"], s["idx_end"]
    xs = dates[a:b+1]
    ys = closes[a:b+1]
    col = RED if s["trend"] == "up" else GREEN
    ax.plot(xs, ys, color=col, lw=1.6)
# boundary lines + labels
labels = ["P1","P2","P3","P4","P5","P6","P7","P8"]
for i, s in enumerate(segs):
    ax.axvline(dates[s["idx_end"]], color="#bbbbbb", lw=0.7, ls="--", alpha=0.7)
    mid = (s["idx_start"] + s["idx_end"]) // 2
    pct = s["pct"]
    tag = f"{labels[i]}\n{pct:+.0f}%"
    ax.text(dates[mid], closes[mid]*1.12 if s['trend']=='up' else closes[mid]*0.86,
            tag, ha="center", va="bottom" if s['trend']=='up' else "top",
            fontsize=8, color=RED if s["trend"]=="up" else GREEN, fontweight="bold")
ax.set_yscale("log")
ax.set_title("中际旭创(300308) 前复权收盘  2022-01 ~ 2026-07\n红涨 / 绿跌 · 对数纵轴 · 8 段主波段", fontsize=12)
ax.set_ylabel("收盘价 (元, 对数)")
ax.grid(True, which="both", ls=":", alpha=0.35)
ax.annotate("市值破万亿 / 高点 1416", xy=(dates[segs[7]['idx_end']], closes[-1]),
            xytext=(dates[segs[6]['idx_end']], 300),
            fontsize=8, color=GREY,
            arrowprops=dict(arrowstyle="->", color=GREY))
fig.tight_layout()
fig.savefig(os.path.join(OUT, "price_chart.png"), dpi=150)
plt.close(fig)
print("price_chart.png done")

# ---------------- 2) 产业链图谱 ----------------
fig, ax = plt.subplots(figsize=(11, 5.6), dpi=150)
ax.set_xlim(0, 10); ax.set_ylim(0, 10); ax.axis("off")

def box(x, y, w, h, text, fc, tc="white", fs=9, bold=True):
    ax.add_patch(plt.Rectangle((x, y), w, h, facecolor=fc, edgecolor="black",
                                lw=1.0, zorder=2))
    ax.text(x+w/2, y+h/2, text, ha="center", va="center", color=tc,
            fontsize=fs, fontweight=("bold" if bold else "normal"), zorder=3)

def arrow(x1, y1, x2, y2, col="#333333", style="-|>"):
    ax.annotate("", xy=(x2, y2), xytext=(x1, y1),
                arrowprops=dict(arrowstyle=style, color=col, lw=2.2), zorder=1)

# 上游 (red, 卡脖子)
ax.text(5, 8.9, "上游（卡脖子集中区 · 国产化率低）", ha="center", fontsize=11, fontweight="bold", color=RED)
box(0.4, 6.6, 2.1, 1.5, "磷化铟(InP)衬底\n缺口>70% · 日美掌控", RED)
box(2.9, 6.6, 2.1, 1.5, "高端 EML 光芯片\n国产化率 4%-5%", RED)
box(5.4, 6.6, 2.1, 1.5, "DSP 数字芯片\n100% 进口", RED)
box(7.9, 6.6, 1.8, 1.5, "硅光/隔离器\n部分突破", "#e07b00")
# 中游 (green)
ax.text(5, 5.5, "中游（封装·中国强项）", ha="center", fontsize=11, fontweight="bold", color=GREEN)
box(2.9, 3.9, 4.2, 1.5, "光模块封装\n中际旭创(全球No.1)·新易盛·天孚·光迅", GREEN)
# 下游 (blue)
ax.text(5, 2.9, "下游（需求高度集中）", ha="center", fontsize=11, fontweight="bold", color=BLUE)
box(2.0, 1.2, 6.0, 1.5, "北美四大云厂商(亚马逊/微软/谷歌/Meta)+英伟达体系\n贡献 >70% 高速光模块需求", BLUE)
# arrows
arrow(4.95, 8.1, 4.95, 5.4)   # 上游 -> 中游
arrow(4.95, 3.9, 4.95, 2.7)   # 中游 -> 下游
# 卡脖子 brackets
ax.annotate("高端 EML / DSP / InP 受美国出口管制\n谁锁定上游，谁有定价权",
            xy=(2.9, 6.6), xytext=(0.2, 9.4), fontsize=8.5, color=RED,
            arrowprops=dict(arrowstyle="->", color=RED))
ax.set_title("光模块产业链结构：上游卡脖子 → 中游封装强 → 下游需求集中", fontsize=12, fontweight="bold")
fig.tight_layout()
fig.savefig(os.path.join(OUT, "value_chain.png"), dpi=150)
plt.close(fig)
print("value_chain.png done")
print("FILES:", os.listdir(OUT))
