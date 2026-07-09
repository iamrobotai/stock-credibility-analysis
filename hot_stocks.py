# -*- coding: utf-8 -*-
"""
hot_stocks.py — 实时热门股票与行业推荐
数据源:
  1. 东财 push2 多 CDN 节点 (82.push2 / 48.push2 / push2)
  2. 新浪 A 股排行 (备用)
  3. akshare 热度榜 (备用)
功能:
  1. 热门个股 (涨幅榜 + 主力净流入榜 + 热度榜)
  2. 热门行业板块 (涨幅排行 + 主力净流入排行)
  3. 热门概念板块 (涨幅排行)
"""
import time, requests, json
from datetime import datetime

UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"

# push2 CDN 节点列表（按优先级）
_PUSH2_NODES = ["82.push2", "48.push2", "18.push2", "56.push2", "push2"]

_cache = {}
_CACHE_TTL = 120  # 2分钟缓存


def _push2_get(path, retries=2):
    """尝试多个 push2 CDN 节点"""
    for node in _PUSH2_NODES:
        url = f"https://{node}.eastmoney.com{path}"
        for attempt in range(retries):
            try:
                r = requests.get(url, headers={"User-Agent": UA}, timeout=8)
                data = r.json()
                items = data.get("data", {}).get("diff", [])
                if items:
                    return items
            except Exception:
                pass
    return []


def _sina_industries():
    """新浪行业排行 (备用, 返回 49 个行业 + 领涨股)"""
    url = "http://vip.stock.finance.sina.com.cn/q/view/newSinaHy.php"
    try:
        r = requests.get(url, headers={"User-Agent": UA}, timeout=10)
        text = r.text
        # 格式: var FEED = {"code":"code,name,count,avg_price,avg_change,avg_change_pct,...", ...}
        import re
        matches = re.findall(r'"([^"]+)":"([^"]+)"', text)
        industries = []
        for node_code, raw in matches:
            parts = raw.split(",")
            if len(parts) < 13:
                continue
            name = parts[1]
            try:
                change_pct = float(parts[5])  # avg_change_pct
            except (ValueError, IndexError):
                change_pct = 0.0
            try:
                volume = float(parts[6]) if parts[6] else 0
            except (ValueError, IndexError):
                volume = 0
            top_stock_code = parts[8] if len(parts) > 8 else ""
            top_stock_name = parts[12] if len(parts) > 12 else ""
            industries.append({
                "code": node_code,
                "name": name,
                "change_pct": round(change_pct, 2),
                "net_inflow": round(volume / 1e8, 2),
                "source": "新浪行业",
                "rank": 0,
                "top_stock_code": top_stock_code,
                "top_stock_name": top_stock_name,
            })
        # 按涨幅排序
        industries.sort(key=lambda x: x["change_pct"], reverse=True)
        for i, ind in enumerate(industries):
            ind["rank"] = i + 1
        return industries[:20]
    except Exception:
        return []


def _sina_gainers(count=15):
    """新浪 A 股涨幅排行 (备用)"""
    url = (f"https://vip.stock.finance.sina.com.cn/quotes_service/api/json_v2.php/"
           f"Market_Center.getHQNodeData?page=1&num={count}&sort=changepercent&asc=0"
           f"&node=hs_a&symbol=&_s_r_a=sort")
    try:
        r = requests.get(url, headers={"User-Agent": UA}, timeout=10)
        items = json.loads(r.text)
        return items
    except Exception:
        return []


def _cached(key, fetcher):
    """带 TTL 的缓存"""
    now = time.time()
    if key in _cache:
        data, ts = _cache[key]
        if now - ts < _CACHE_TTL:
            return data
    try:
        data = fetcher()
        if data:
            _cache[key] = (data, now)
        return data
    except Exception:
        if key in _cache:
            return _cache[key][0]
        return []


def get_hot_stocks():
    """
    热门个股: 合并涨幅榜 + 主力净流入榜 + 热度榜
    返回 [{code, name, change_pct, industry, source, rank}]
    """
    results = []
    seen = set()

    # 1. 涨幅榜 (push2 优先, sina 备用)
    def _fetch_gainers():
        gainers = []
        items = _push2_get(
            "/api/qt/clist/get?pn=1&pz=15&po=1&np=1&fltt=2&invt=2&fid=f3"
            "&fs=m:0+t:6,m:0+t:80,m:1+t:2,m:1+t:23&fields=f12,f14,f3,f127"
        )
        if items:
            for i, item in enumerate(items):
                code = str(item.get("f12", ""))
                if code in seen:
                    continue
                seen.add(code)
                gainers.append({
                    "code": code,
                    "name": str(item.get("f14", "")).strip(),
                    "change_pct": float(item.get("f3", 0)),
                    "industry": str(item.get("f127", "")),
                    "source": "涨幅榜",
                    "rank": i + 1,
                })
        else:
            # sina fallback
            sina_items = _sina_gainers(15)
            for i, item in enumerate(sina_items):
                code = str(item.get("code", "")).zfill(6)
                if code in seen:
                    continue
                seen.add(code)
                gainers.append({
                    "code": code,
                    "name": str(item.get("name", "")).strip(),
                    "change_pct": float(item.get("changepercent", 0)),
                    "industry": "",
                    "source": "涨幅榜",
                    "rank": i + 1,
                })
        return gainers

    results.extend(_cached("gainers", _fetch_gainers))

    # 2. 主力净流入榜 (push2)
    def _fetch_flow():
        items = _push2_get(
            "/api/qt/clist/get?pn=1&pz=10&po=1&np=1&fltt=2&invt=2&fid=f62"
            "&fs=m:0+t:6,m:0+t:80,m:1+t:2,m:1+t:23&fields=f12,f14,f3,f62,f127"
        )
        flows = []
        for i, item in enumerate(items):
            code = str(item.get("f12", ""))
            if code in seen:
                continue
            seen.add(code)
            flows.append({
                "code": code,
                "name": str(item.get("f14", "")).strip(),
                "change_pct": float(item.get("f3", 0)),
                "industry": str(item.get("f127", "")),
                "source": "主力净流入",
                "rank": i + 1,
                "net_inflow": round(float(item.get("f62", 0)) / 1e8, 2),
            })
        return flows

    results.extend(_cached("flow", _fetch_flow))

    # 3. 热度榜 (akshare)
    def _fetch_hot():
        try:
            import akshare as ak
            df = ak.stock_hot_rank_em()
            hot_list = []
            for _, row in df.head(15).iterrows():
                code_raw = str(row["代码"])
                code = code_raw[2:] if len(code_raw) > 6 else code_raw
                name = str(row["股票名称"]).strip()
                if code in seen:
                    continue
                seen.add(code)
                hot_list.append({
                    "code": code,
                    "name": name,
                    "change_pct": round(float(row.get("涨跌幅", 0)), 2),
                    "industry": "",
                    "source": "热度榜",
                    "rank": int(row["当前排名"]),
                })
            return hot_list
        except Exception:
            return []

    results.extend(_cached("hot_rank", _fetch_hot))

    return results[:30]


def get_hot_industries():
    """
    热门行业板块: 涨幅排行 + 主力净流入排行
    push2 优先, sina 备用
    返回 [{code, name, change_pct, net_inflow, source, rank}]
    """
    results = []
    seen = set()

    # 1. 行业涨幅排行 (push2 优先, sina 备用)
    def _fetch_ind_gain():
        items = _push2_get(
            "/api/qt/clist/get?pn=1&pz=15&po=1&np=1&fltt=2&invt=2&fid=f3"
            "&fs=m:90+t:2&fields=f12,f14,f3,f62"
        )
        ind_list = []
        if items:
            for i, item in enumerate(items):
                code = str(item.get("f12", ""))
                if code in seen:
                    continue
                seen.add(code)
                ind_list.append({
                    "code": code,
                    "name": str(item.get("f14", "")).strip(),
                    "change_pct": float(item.get("f3", 0)),
                    "net_inflow": round(float(item.get("f62", 0)) / 1e8, 2),
                    "source": "涨幅榜",
                    "rank": i + 1,
                })
        else:
            # sina fallback
            sina_inds = _sina_industries()
            for ind in sina_inds[:15]:
                if ind["name"] in seen:
                    continue
                seen.add(ind["name"])
                ind_list.append(ind)
        return ind_list

    results.extend(_cached("ind_gain", _fetch_ind_gain))

    # 2. 行业主力净流入排行 (push2 only - sina doesn't have this)
    def _fetch_ind_flow():
        items = _push2_get(
            "/api/qt/clist/get?pn=1&pz=10&po=1&np=1&fltt=2&invt=2&fid=f62"
            "&fs=m:90+t:2&fields=f12,f14,f3,f62"
        )
        flow_list = []
        for i, item in enumerate(items):
            code = str(item.get("f12", ""))
            if code in seen:
                continue
            seen.add(code)
            flow_list.append({
                "code": code,
                "name": str(item.get("f14", "")).strip(),
                "change_pct": float(item.get("f3", 0)),
                "net_inflow": round(float(item.get("f62", 0)) / 1e8, 2),
                "source": "主力净流入",
                "rank": i + 1,
            })
        return flow_list

    results.extend(_cached("ind_flow", _fetch_ind_flow))

    return results[:20]


def get_hot_concepts():
    """
    热门概念板块: 涨幅排行
    返回 [{code, name, change_pct, rank}]
    """
    def _fetch_concept():
        items = _push2_get(
            "/api/qt/clist/get?pn=1&pz=15&po=1&np=1&fltt=2&invt=2&fid=f3"
            "&fs=m:90+t:3&fields=f12,f14,f3"
        )
        return [{
            "code": str(item.get("f12", "")),
            "name": str(item.get("f14", "")).strip(),
            "change_pct": float(item.get("f3", 0)),
            "rank": i + 1,
        } for i, item in enumerate(items)]

    return _cached("concept", _fetch_concept)


def get_all_hot():
    """获取全部热门数据"""
    return {
        "stocks": get_hot_stocks(),
        "industries": get_hot_industries(),
        "concepts": get_hot_concepts(),
        "update_time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    }


if __name__ == "__main__":
    data = get_all_hot()
    print(f"更新时间: {data['update_time']}")
    print(f"\n=== 热门个股 ({len(data['stocks'])}只) ===")
    for s in data["stocks"][:10]:
        flow_str = f" | 净流入: {s.get('net_inflow', '?')}亿" if "net_inflow" in s else ""
        print(f"  {s['code']:8s} | {s['name']:10s} | {s['change_pct']:+.2f}% | {s['source']}{flow_str}")
    print(f"\n=== 热门行业 ({len(data['industries'])}个) ===")
    for ind in data["industries"][:10]:
        print(f"  {ind['name']:14s} | {ind['change_pct']:+.2f}% | 净流入: {ind['net_inflow']:.2f}亿 | {ind['source']}")
    print(f"\n=== 热门概念 ({len(data['concepts'])}个) ===")
    for c in data["concepts"][:10]:
        print(f"  {c['name']:16s} | {c['change_pct']:+.2f}%")
