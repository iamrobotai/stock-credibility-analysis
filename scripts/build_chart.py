#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""基于日线数据生成中际旭创分段涨跌曲线图(SVG, 对数纵坐标)。
分段策略：摆幅阈值 30%（从区间极值回撤/反弹 30% 即确认一段）。"""
import json, math, os

HERE = os.path.dirname(os.path.abspath(__file__))
with open(os.path.join(HERE, "kline_300308.json"), encoding="utf-8") as f:
    DATA = json.load(f)
ROWS = DATA["rows"]
DATES = [r["date"] for r in ROWS]
CLOSE = [r["close"] for r in ROWS]
N = len(CLOSE)

# ---------- 1. 波段分段（30% 摆幅）----------
TH = 0.30
# 初始方向：首个 >=5% 移动决定
j = 1
while j < N and abs(CLOSE[j] / CLOSE[0] - 1) < 0.05:
    j += 1
direction = 1 if CLOSE[j] >= CLOSE[0] else -1
ext = CLOSE[j]; ext_i = j
segs = []
i = 0
for k in range(j, N):
    if direction == 1:
        if CLOSE[k] > ext:
            ext = CLOSE[k]; ext_i = k
        elif CLOSE[k] < ext * (1 - TH):
            segs.append((i, ext_i)); i = ext_i
            direction = -1; ext = CLOSE[k]; ext_i = k
    else:
        if CLOSE[k] < ext:
            ext = CLOSE[k]; ext_i = k
        elif CLOSE[k] > ext * (1 + TH):
            segs.append((i, ext_i)); i = ext_i
            direction = 1; ext = CLOSE[k]; ext_i = k
segs.append((i, N - 1))

seg_info = []
for (s, e) in segs:
    pct = (CLOSE[e] / CLOSE[s] - 1) * 100
    seg_info.append({
        "idx_start": s, "idx_end": e,
        "date_start": DATES[s], "date_end": DATES[e],
        "trend": "up" if pct >= 0 else "down",
        "close_start": round(CLOSE[s], 2),
        "close_end": round(CLOSE[e], 2),
        "pct": round(pct, 1),
    })

# ---------- 2. 年度统计 ----------
yearly = {}
for r in ROWS:
    y = r["date"][:4]
    d = yearly.setdefault(y, {"lo": r["close"], "hi": r["close"], "last": r["close"]})
    d["lo"] = min(d["lo"], r["close"]); d["hi"] = max(d["hi"], r["close"])
    d["last"] = r["close"]

# ---------- 3. SVG 绘制 ----------
W, H = 1180, 600
ML, MR, MT, MB = 70, 250, 40, 60
PW = W - ML - MR
PH = H - MT - MB
lo_log = math.log10(min(CLOSE)); hi_log = math.log10(max(CLOSE))

def x(i): return ML + (i / (N - 1)) * PW
def y(v):
    lg = math.log10(v)
    return MT + PH - ((lg - lo_log) / (hi_log - lo_log)) * PH

RED = "#d83a3a"; GREEN = "#1f9d55"; GRID = "#e3e3e8"; AXIS = "#888"; INK = "#222"

parts = []
parts.append(f'<svg xmlns="http://www.w3.org/2000/svg" width="{W}" height="{H}" viewBox="0 0 {W} {H}" font-family="-apple-system,Segoe UI,Microsoft YaHei,sans-serif">')
parts.append(f'<rect width="{W}" height="{H}" fill="#fbfbfd"/>')
parts.append(f'<text x="{ML}" y="24" font-size="18" font-weight="700" fill="{INK}">中际旭创 (300308) 前复权收盘价走势 · 2022–2026</text>')
parts.append(f'<text x="{ML}" y="42" font-size="12" fill="#888">纵轴对数刻度；红=上涨波段，绿=下跌波段；右侧为波段清单</text>')

for exp in range(int(math.floor(lo_log)), int(math.ceil(hi_log)) + 1):
    for kk in [1, 2, 5]:
        val = kk * (10 ** exp)
        if val < min(CLOSE) * 0.9 or val > max(CLOSE) * 1.1:
            continue
        yy = y(val)
        parts.append(f'<line x1="{ML}" y1="{yy:.1f}" x2="{ML+PW}" y2="{yy:.1f}" stroke="{GRID}" stroke-width="1"/>')
        parts.append(f'<text x="{ML-8}" y="{yy+4:.1f}" font-size="10" fill="{AXIS}" text-anchor="end">{val:g}</text>')

for yr in sorted(yearly.keys()):
    fi = next(idx for idx, d in enumerate(DATES) if d.startswith(yr))
    xx = x(fi)
    parts.append(f'<line x1="{xx:.1f}" y1="{MT}" x2="{xx:.1f}" y2="{MT+PH}" stroke="{GRID}" stroke-width="1"/>')
    parts.append(f'<text x="{xx:.1f}" y="{MT+PH+18}" font-size="11" fill="{AXIS}" text-anchor="middle">{yr}</text>')

for (s, e) in segs:
    pct = (CLOSE[e] / CLOSE[s] - 1) * 100
    col = RED if pct >= 0 else GREEN
    pts = " ".join(f"{x(i):.1f},{y(CLOSE[i]):.1f}" for i in range(s, e + 1))
    parts.append(f'<polyline points="{pts}" fill="none" stroke="{col}" stroke-width="2.4"/>')

gmin_i = CLOSE.index(min(CLOSE)); gmax_i = CLOSE.index(max(CLOSE))
parts.append(f'<circle cx="{x(gmin_i):.1f}" cy="{y(CLOSE[gmin_i]):.1f}" r="3.5" fill="{GREEN}" stroke="#fff" stroke-width="1"/>')
parts.append(f'<text x="{x(gmin_i):.1f}" y="{y(CLOSE[gmin_i])+16:.1f}" font-size="10" fill="{GREEN}" text-anchor="middle">低 {CLOSE[gmin_i]:.1f}</text>')
parts.append(f'<circle cx="{x(gmax_i):.1f}" cy="{y(CLOSE[gmax_i]):.1f}" r="3.5" fill="{RED}" stroke="#fff" stroke-width="1"/>')
parts.append(f'<text x="{x(gmax_i):.1f}" y="{y(CLOSE[gmax_i])-10:.1f}" font-size="10" fill="{RED}" text-anchor="middle">高 {CLOSE[gmax_i]:.1f}</text>')

parts.append(f'<rect x="{ML+10}" y="{MT+8}" width="14" height="14" fill="{RED}"/>')
parts.append(f'<text x="{ML+30}" y="{MT+19}" font-size="11" fill="{INK}">上涨波段</text>')
parts.append(f'<rect x="{ML+10}" y="{MT+28}" width="14" height="14" fill="{GREEN}"/>')
parts.append(f'<text x="{ML+30}" y="{MT+39}" font-size="11" fill="{INK}">下跌波段</text>')

parts.append(f'<text x="{ML+PW+20}" y="{MT+10}" font-size="13" font-weight="700" fill="{INK}">趋势波段 ({len(seg_info)}段)</text>')
ly = MT + 34
for kk, sg in enumerate(seg_info, 1):
    col = RED if sg["trend"] == "up" else GREEN
    arrow = "▲" if sg["trend"] == "up" else "▼"
    parts.append(f'<text x="{ML+PW+20}" y="{ly}" font-size="11" fill="{col}">{kk}. {sg["date_start"][:7]}→{sg["date_end"][:7]} {arrow} {sg["pct"]:+.0f}%</text>')
    ly += 22

parts.append('</svg>')
svg = "\n".join(parts)
out = os.path.join(HERE, "chart_300308.svg")
with open(out, "w", encoding="utf-8") as f:
    f.write(svg)
with open(os.path.join(HERE, "segments.json"), "w", encoding="utf-8") as f:
    json.dump(seg_info, f, ensure_ascii=False, indent=2)

print(f"分段数: {len(seg_info)}")
for i, sg in enumerate(seg_info, 1):
    print(f"  P{i}: {sg['date_start']}→{sg['date_end']} {'涨' if sg['trend']=='up' else '跌'} {sg['pct']:+.0f}%  ({sg['close_start']}→{sg['close_end']})")
print("SVG 已保存:", out)
