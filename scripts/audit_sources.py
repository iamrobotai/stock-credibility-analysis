# -*- coding: utf-8 -*-
"""audit_sources.py — 审计各股票 raw.json 的数据源覆盖情况，定位缺失数据源。"""
import json, os, glob, sys
from collections import defaultdict

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(ROOT, "data")

# 平台注册表（与 data_collector 对齐）
PLATFORMS = ["kline","news","reports","financials","cninfo","ir","ths",
             "sina_fund","lhb","xueqiu","xueqiu_posts","zhihu","comment",
             "guba","taoguba"]
META = {"code","name","fetch_time","stock_url","guba_url","cninfo_url","incremental"}

files = sorted(glob.glob(os.path.join(DATA, "*_raw.json")))
total = len(files)
present = defaultdict(int)      # 有数据(非空)
empty = defaultdict(int)        # 键存在但为空
missing = defaultdict(int)      # 键完全不存在
missing_stocks = defaultdict(list)

for f in files:
    code = os.path.basename(f).replace("_raw.json","")
    try:
        with open(f, encoding="utf-8") as fh:
            d = json.load(fh)
    except Exception as e:
        print(f"[ERR] {code}: {e}")
        continue
    for p in PLATFORMS:
        if p not in d:
            missing[p] += 1
            missing_stocks[p].append(code)
        else:
            v = d[p]
            has = (isinstance(v, list) and len(v) > 0) or (isinstance(v, dict) and len(v) > 0) or (isinstance(v, (int,float,str)) and str(v).strip())
            if has:
                present[p] += 1
            else:
                empty[p] += 1
                missing_stocks[p].append(code)

print(f"总股票数: {total}\n")
print(f"{'数据源':<15}{'有数据':>8}{'空':>8}{'缺键':>8}{'覆盖率':>10}")
print("-"*55)
for p in PLATFORMS:
    cov = present[p]/total*100 if total else 0
    print(f"{p:<15}{present[p]:>8}{empty[p]:>8}{missing[p]:>8}{cov:>9.1f}%")

# 输出缺失清单供后续补采
gaps = {}
for p in PLATFORMS:
    lst = missing_stocks.get(p, [])
    if lst:
        gaps[p] = lst
with open(os.path.join(DATA, "_source_gaps.json"), "w", encoding="utf-8") as fh:
    json.dump({"total": total, "gaps": gaps,
               "coverage": {p: present[p] for p in PLATFORMS}}, fh, ensure_ascii=False, indent=2)
print(f"\n缺口清单已写入: data/_source_gaps.json")
