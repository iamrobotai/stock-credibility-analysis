# -*- coding: utf-8 -*-
"""
supplement_sources.py — 增量补齐本地缺失的数据源
====================================================
策略:
  1. 读取每只股票现有 {code}_raw.json
  2. 只对"缺失或为空"的高价值数据源进行采集 (核心源已完整，不重采)
  3. 采集结果合并回 raw.json (保留原有数据 + fetch_time)
  4. comment 全市场表一次性缓存复用，避免重复拉取

补充源: cninfo / ir / ths / sina_fund / lhb / comment / xueqiu
用法:
  python supplement_sources.py            # 全部股票
  python supplement_sources.py 300308     # 指定单只
  python supplement_sources.py --only cninfo,ir   # 只补指定源
"""
import sys, os, json, glob, time
from datetime import datetime

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "core"))
DATA = os.path.join(ROOT, "data")
import data_collector as dc
import akshare as ak

# 需要补充的高价值源 (核心 kline/news/reports/financials 不在此列)
SUPPLEMENT = ["cninfo", "ir", "ths", "sina_fund", "lhb", "comment", "xueqiu"]

from datetime import timedelta

# comment 全市场缓存
_COMMENT_CACHE = {"df": None, "loaded": False}
# lhb 全市场缓存 (近90天)
_LHB_CACHE = {"df": None, "loaded": False}

def _get_lhb_rows(code):
    if not _LHB_CACHE["loaded"]:
        end = datetime.now().strftime("%Y%m%d")
        start = (datetime.now() - timedelta(days=90)).strftime("%Y%m%d")
        try:
            _LHB_CACHE["df"] = ak.stock_lhb_detail_em(start_date=start, end_date=end)
        except Exception as e:
            print(f"  [lhb] 全市场表加载失败: {e}")
            _LHB_CACHE["df"] = None
        _LHB_CACHE["loaded"] = True
    df = _LHB_CACHE["df"]
    if df is None:
        return []
    col = "代码" if "代码" in df.columns else ("股票代码" if "股票代码" in df.columns else None)
    if not col:
        return []
    sub = df[df[col].astype(str) == str(code)]
    url = f"https://data.eastmoney.com/stock/lhb,{code}.html"
    recs = sub.to_dict("records")
    for r in recs:
        r["url"] = url
    return recs

def _get_comment_row(code):
    if not _COMMENT_CACHE["loaded"]:
        try:
            _COMMENT_CACHE["df"] = ak.stock_comment_em()
        except Exception as e:
            print(f"  [comment] 全市场表加载失败: {e}")
            _COMMENT_CACHE["df"] = None
        _COMMENT_CACHE["loaded"] = True
    df = _COMMENT_CACHE["df"]
    if df is None:
        return []
    col = "代码" if "代码" in df.columns else ("股票代码" if "股票代码" in df.columns else None)
    if not col:
        return []
    sub = df[df[col].astype(str) == str(code)]
    url = f"https://emweb.securities.eastmoney.com/pc_hsf10/pages/index.html?type=web&code={'SH' if code.startswith('6') else 'SZ'}{code}"
    recs = sub.to_dict("records")
    for r in recs:
        r["url"] = url
    return recs

def _is_empty(v):
    if v is None: return True
    if isinstance(v, (list, dict)) and len(v) == 0: return True
    if isinstance(v, str) and not v.strip(): return True
    return False

COLLECTORS = {
    "cninfo":    lambda code, name: dc.collect_cninfo(code),
    "ir":        lambda code, name: dc.collect_ir(code),
    "ths":       lambda code, name: dc.collect_ths(code),
    "sina_fund": lambda code, name: dc.collect_sina_fund(code),
    "lhb":       lambda code, name: _get_lhb_rows(code),
    "comment":   lambda code, name: _get_comment_row(code),
    "xueqiu":    lambda code, name: dc.collect_xueqiu(code),
}

# 时效性源: --refresh 模式下重采并合并新增 (去重)
REFRESH_SRC = ["news", "reports", "cninfo", "ir", "sina_fund", "lhb", "comment"]

# 核心源采集器 (供 refresh 使用)
CORE_COLLECTORS = {
    "news":    lambda code, name: dc.collect_news(code),
    "reports": lambda code, name: dc.collect_reports(code),
}

def supplement_one(path, only=None, refresh=False):
    code = os.path.basename(path).replace("_raw.json", "")
    try:
        with open(path, encoding="utf-8") as f:
            d = json.load(f)
    except Exception as e:
        print(f"[{code}] 读取失败: {e}")
        return 0
    name = d.get("name", "")
    filled = []

    if refresh:
        # 增量刷新: 时效源重采 + 去重合并新增
        from incremental_manager import merge_data
        targets = only if only else REFRESH_SRC
        changed = False
        for src in targets:
            fn = COLLECTORS.get(src) or CORE_COLLECTORS.get(src)
            if not fn:
                continue
            try:
                new = fn(code, name)
                # comment/资金流快照类 → 覆盖(仅当有数据); 其余按 key 去重合并
                if src == "comment":
                    if new:
                        d[src] = new; changed = True
                elif isinstance(new, list):
                    old = d.get(src, []) if isinstance(d.get(src), list) else []
                    key = "date" if src == "sina_fund" else "title"
                    merged, nc = merge_data(old, new, key_field=key)
                    d[src] = merged
                    if nc > 0:
                        filled.append(f"{src}+{nc}"); changed = True
                else:
                    d[src] = new; changed = True  # dict 类 (ths) 直接覆盖
            except Exception as e:
                print(f"  [{code}/{src}] refresh FAIL: {str(e)[:50]}")
        if changed:
            d["supplement_time"] = datetime.now().isoformat()
            with open(path, "w", encoding="utf-8") as f:
                json.dump(d, f, ensure_ascii=False, default=str, indent=2)
            if filled:
                print(f"[{code}] {name}: 增量 {', '.join(filled)}")
            return len(filled)
        return 0

    # 默认: 补空缺 (幂等)
    targets = only if only else SUPPLEMENT
    for src in targets:
        if src not in COLLECTORS:
            continue
        # 已有非空数据则跳过 (幂等)
        if src in d and not _is_empty(d[src]):
            continue
        try:
            data = COLLECTORS[src](code, name)
            d[src] = data
            n = len(data) if isinstance(data, (list, dict)) else (1 if data else 0)
            if n > 0:
                filled.append(f"{src}={n}")
        except Exception as e:
            d.setdefault(src, [])
            print(f"  [{code}/{src}] FAIL: {str(e)[:50]}")
    if filled:
        d["supplement_time"] = datetime.now().isoformat()
        with open(path, "w", encoding="utf-8") as f:
            json.dump(d, f, ensure_ascii=False, default=str, indent=2)
        print(f"[{code}] {name}: +{', '.join(filled)}")
        return len(filled)
    return 0

def main():
    args = [a for a in sys.argv[1:]]
    only = None
    codes = None
    refresh = False
    i = 0
    while i < len(args):
        if args[i] == "--only" and i+1 < len(args):
            only = [x.strip() for x in args[i+1].split(",")]
            i += 2
        elif args[i] == "--refresh":
            refresh = True
            i += 1
        else:
            codes = codes or []
            codes.append(args[i])
            i += 1

    if codes:
        files = [os.path.join(DATA, f"{c}_raw.json") for c in codes]
    else:
        files = sorted(glob.glob(os.path.join(DATA, "*_raw.json")))

    total = len(files)
    mode = "增量刷新(refresh)" if refresh else "补空缺(fill)"
    src_list = only or (REFRESH_SRC if refresh else SUPPLEMENT)
    print(f"待处理: {total} 只 | 模式: {mode} | 源: {src_list}\n")
    done = 0; touched = 0
    t0 = time.time()
    for path in files:
        if not os.path.exists(path):
            continue
        r = supplement_one(path, only=only, refresh=refresh)
        touched += (1 if r else 0)
        done += 1
        if done % 20 == 0:
            el = time.time()-t0
            print(f"  ... {done}/{total} ({el:.0f}s, 补充 {touched} 只)")
    print(f"\n完成: 处理 {done} 只，补充 {touched} 只，用时 {time.time()-t0:.0f}s")

if __name__ == "__main__":
    main()
