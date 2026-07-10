# -*- coding: utf-8 -*-
"""
segment.py — 摆荡腿分段算法（本地，零 token）
读取 data/<code>_raw.json 的 K线 → 分段 → 输出 segments JSON
"""
import json, os, sys


def segment(prices, thr=0.35):
    """摆荡腿分段：固定初始锚点，仅在反向≥thr 摆幅时切换相位"""
    n = len(prices)
    if n < 5:
        return []
    segs = []
    start = 0
    anchor = prices[0]
    direction = None
    ext = prices[0]
    ext_i = 0
    for i in range(1, n):
        p = prices[i]
        if direction is None:
            if p >= anchor * (1 + thr):
                direction = "up"; ext = p; ext_i = i
            elif p <= anchor * (1 - thr):
                direction = "down"; ext = p; ext_i = i
            continue
        if direction == "up":
            if p > ext:
                ext = p; ext_i = i
            elif p <= ext * (1 - thr):
                segs.append((start, ext_i, "up"))
                start = ext_i; direction = "down"; ext = p; ext_i = i
        else:
            if p < ext:
                ext = p; ext_i = i
            elif p >= ext * (1 + thr):
                segs.append((start, ext_i, "down"))
                start = ext_i; direction = "up"; ext = p; ext_i = i
    if direction:
        segs.append((start, n - 1, direction))
    return segs


def run(code, datadir="data"):
    fpath = os.path.join(datadir, f"{code}_raw.json")
    if not os.path.exists(fpath):
        print(f"[segment] {fpath} not found")
        return None
    d = json.load(open(fpath, encoding="utf-8"))
    kline = d.get("kline", [])
    if not kline:
        print(f"[segment] no kline for {code}")
        return None

    prices = [b["close"] for b in kline]
    dates = [b["date"] for b in kline]
    segs = segment(prices)

    result = []
    for idx, (s, e, dr) in enumerate(segs):
        p0, p1 = prices[s], prices[e]
        pct = (p1 - p0) / p0 * 100
        result.append({
            "id": f"P{idx+1}",
            "start_date": dates[s], "end_date": dates[e],
            "start_price": round(p0, 2), "end_price": round(p1, 2),
            "pct": round(pct, 1),
            "direction": "涨" if dr == "up" else "跌",
            "bars": e - s + 1,
        })

    outf = os.path.join(datadir, f"{code}_segments.json")
    with open(outf, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)
    print(f"[segment] {code}: {len(result)} phases, {len(prices)} bars")
    for s in result:
        print(f"  {s['id']} {s['direction']} {s['pct']:+.1f}% "
              f"({s['start_date']}→{s['end_date']}, {s['bars']}bars)")
    return result


if __name__ == "__main__":
    code = sys.argv[1] if len(sys.argv) > 1 else "002371"
    run(code)
