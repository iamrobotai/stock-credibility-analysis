# -*- coding: utf-8 -*-
"""新易盛(300502) 分段 + 价格曲线图。与中际旭创同口径：30% 摆幅阈值得主波段。"""
import json, os
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib.font_manager import FontProperties

BASE = os.path.dirname(os.path.abspath(__file__))
FP = FontProperties(fname=r"C:/WINDOWS/Fonts/msyh.ttc", size=9)

with open(os.path.join(BASE, "kline_300502.json"), encoding='utf-8') as f:
    data = json.load(f)['data']
kl = data['klines']
dates = [r.split(',')[0] for r in kl]
closes = [float(r.split(',')[2]) for r in kl]  # 收盘价
print(f"bars={len(closes)}  range={dates[0]}..{dates[-1]}  first={closes[0]:.2f} last={closes[-1]:.2f}")

def segment(prices, thr=0.35):
    """摆荡腿分段：仅在出现反向 ≥thr 摆动时才切换相位，消除 0% 伪段。"""
    n = len(prices); segs = []
    start = 0; anchor = prices[0]; direction = None
    ext = prices[0]; ext_i = 0
    for i in range(1, n):
        p = prices[i]
        if direction is None:
            if p >= anchor * (1 + thr):
                direction = 'up'; ext = p; ext_i = i
            elif p <= anchor * (1 - thr):
                direction = 'down'; ext = p; ext_i = i
            continue
        else:
            if direction == 'up':
                if p > ext:
                    ext = p; ext_i = i
                elif p <= ext * (1 - thr):
                    segs.append((start, ext_i, 'up')); start = ext_i
                    direction = 'down'; ext = p; ext_i = i
            else:
                if p < ext:
                    ext = p; ext_i = i
                elif p >= ext * (1 + thr):
                    segs.append((start, ext_i, 'down')); start = ext_i
                    direction = 'up'; ext = p; ext_i = i
    if direction:
        segs.append((start, n-1, direction))
    return segs

segs = segment(closes)
print(f"segments={len(segs)}")
summary = []
for k, (a, b, d) in enumerate(segs, 1):
    chg = (closes[b]-closes[a])/closes[a]*100
    summary.append({'band': k, 'start': dates[a], 'end': dates[b],
                   'dir': d, 'p0': closes[a], 'p1': closes[b], 'pct': round(chg,1)})
    print(f"  P{k} {d:4s} {dates[a]}→{dates[b]}  {closes[a]:.2f}→{closes[b]:.2f}  {chg:+.1f}%")
with open(os.path.join(BASE, "segments_300502.json"), "w", encoding='utf-8') as f:
    json.dump(summary, f, ensure_ascii=False, indent=2)

# 画图
fig, ax = plt.subplots(figsize=(11, 5.2))
xs = list(range(len(closes)))
ax.plot(xs, closes, color='#555555', lw=0.7, zorder=1)
# 分段底色
colors = {'up': '#e74c3c', 'down': '#27ae60'}
for k, (a, b, d) in enumerate(segs, 1):
    ax.axvspan(a, b, color=colors[d], alpha=0.10, zorder=0)
    midx = (a+b)/2
    ax.text(midx, closes[b]*1.02 if d=='up' else closes[b]*0.96, f"P{k}",
            color=colors[d], fontsize=8, ha='center', fontproperties=FP, zorder=3)
ax.set_yscale('log')
ax.set_title("新易盛(300502) 日线收盘价分段（红涨/绿跌·对数轴）", fontproperties=FontProperties(fname=r"C:/WINDOWS/Fonts/msyh.ttc", size=12))
step = max(1, len(dates)//10)
ax.set_xticks(xs[::step]); ax.set_xticklabels([dates[i] for i in xs[::step]], rotation=45, fontproperties=FP, fontsize=7)
ax.tick_params(axis='y', labelsize=7)
ax.grid(True, alpha=0.25)
fig.tight_layout()
out = os.path.join(BASE, "price_chart_300502.png")
fig.savefig(out, dpi=130)
print("saved", out)
