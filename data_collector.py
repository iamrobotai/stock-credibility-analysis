# -*- coding: utf-8 -*-
"""
data_collector.py — 本地零-token 多源数据采集器 v2.0
支持平台选择、情绪帖过滤、高价值数据优先。

数据源分类:
  [核心] kline / news / reports / financials — 必采
  [高价值] cninfo(公告) / ir(互动易) / ths(同花顺) / sina_fund(资金流) / lhb(龙虎榜) / xueqiu(雪球) / comment(评论)
  [情绪] guba(股吧) / taoguba(淘股吧) — 可选，默认启用但带过滤

用法:
  collect(code, name)                           # 全平台
  collect(code, name, platforms=['kline','news','reports','financials','cninfo','ir'])  # 仅高价值
  collect(code, name, filter_emotion=True)      # 过滤情绪帖
"""
import akshare as ak
import requests
from bs4 import BeautifulSoup
import json, os, sys, time, re
from datetime import datetime, timedelta

UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0 Safari/537.36"
HEADERS = {"User-Agent": UA, "Referer": "https://guba.eastmoney.com/"}

# ── 平台注册表 ──
PLATFORM_REGISTRY = {
    # 核心 (不可关闭)
    "kline":      {"label": "K线(新浪)",       "category": "core",     "value": "high",   "desc": "前复权全历史日线，分段+曲线基础"},
    "news":       {"label": "东财新闻",         "category": "core",     "value": "high",   "desc": "公司相关新闻，含来源和时间"},
    "reports":    {"label": "东财研报",         "category": "core",     "value": "high",   "desc": "机构研报，含EPS/PE/评级预测"},
    "financials": {"label": "东财财务摘要",     "category": "core",     "value": "high",   "desc": "财务基本面数据"},
    # 高价值 (默认启用)
    "cninfo":     {"label": "巨潮资讯(公告)",   "category": "high",     "value": "high",   "desc": "官方公告：年报/定增/回购/减持"},
    "ir":         {"label": "互动易(问答)",     "category": "high",     "value": "high",   "desc": "投资者问答，公司官方回应"},
    "ths":        {"label": "同花顺(千股千评)", "category": "high",     "value": "medium", "desc": "千股千评/财务指标/公司亮点"},
    "sina_fund":  {"label": "新浪资金流向",     "category": "high",     "value": "medium", "desc": "主力净流入/大单/超大单"},
    "lhb":        {"label": "东财龙虎榜",       "category": "high",     "value": "medium", "desc": "近3月龙虎榜明细"},
    "xueqiu":     {"label": "雪球(基本面)",     "category": "high",     "value": "medium", "desc": "雪球个股基本面信息"},
    "comment":    {"label": "东财评论",         "category": "high",     "value": "medium", "desc": "市场情绪指标/综合评价"},
    # 情绪 (可选，默认启用但带过滤)
    "guba":       {"label": "东财股吧",         "category": "emotional","value": "low",    "desc": "散户讨论帖，情绪化较多"},
    "taoguba":    {"label": "淘股吧",           "category": "emotional","value": "low",    "desc": "短线情绪/技术分析帖"},
}

# 默认启用的平台 (核心+高价值+情绪)
DEFAULT_PLATFORMS = list(PLATFORM_REGISTRY.keys())

# 仅高价值平台 (不含情绪)
HIGH_VALUE_PLATFORMS = [k for k, v in PLATFORM_REGISTRY.items() if v["category"] != "emotional"]

# ── 情绪帖过滤关键词 ──
EMOTION_FILTER_KW = [
    "必涨", "稳赚", "暴涨", "起飞", "拉升", "主升浪", "翻倍", "闭眼买",
    "钻石底", "黄金坑", "满仓", "抄底", "涨停", "跌停", "牛股", "妖股",
    "绝密", "内部", "跟上", "上车", "下车的", "留仓", "清仓",
]
EMOTION_KEEP_KW = [
    "营收", "净利", "利润", "订单", "产能", "市占率", "毛利率", "同比", "环比",
    "亿元", "万片", "GWh", "良率", "制程", "稼动率", "评级", "目标价",
    "EPS", "PE", "PB", "ROE", "研报", "公告", "回购", "增持", "减持",
]


def _retry(fn, tries=3, delay=1.5):
    for i in range(tries):
        try:
            return fn()
        except Exception as e:
            if i == tries - 1:
                raise
            time.sleep(delay * (i + 1))
    return None


def _filter_emotional_posts(posts, keep_threshold=1):
    """
    过滤情绪帖: 保留含实质性关键词的帖子，剔除纯情绪喊单帖
    keep_threshold: 至少命中 N 个实质关键词才保留 (0=不过滤)
    """
    if keep_threshold <= 0:
        return posts
    filtered = []
    for p in posts:
        text = p.get("title", "") + " " + p.get("content", "")
        # 含实质关键词 → 保留
        substance_hits = sum(1 for kw in EMOTION_KEEP_KW if kw in text)
        # 纯情绪关键词且无实质内容 → 剔除
        emotion_hits = sum(1 for kw in EMOTION_FILTER_KW if kw in text)
        if substance_hits >= keep_threshold:
            filtered.append(p)
        elif emotion_hits == 0 and len(p.get("title", "")) > 5:
            # 无情绪词且标题够长 → 保留 (中性帖)
            filtered.append(p)
    return filtered


# ============================================================
# 核心平台
# ============================================================

def collect_kline(code, days=1095):
    """新浪源 K线（前复权全历史）"""
    sym = f"sh{code}" if str(code).startswith("6") else f"sz{code}"
    df = _retry(lambda: ak.stock_zh_a_daily(symbol=sym, adjust="qfq"))
    cutoff = datetime.now() - timedelta(days=days)
    bars = []
    for _, r in df.iterrows():
        d = str(r["date"])[:10]
        try:
            dt = datetime.strptime(d, "%Y-%m-%d")
        except Exception:
            continue
        if dt < cutoff:
            continue
        bars.append({
            "date": d,
            "open": float(r["open"]), "close": float(r["close"]),
            "high": float(r["high"]), "low": float(r["low"]),
            "volume": float(r.get("volume", 0)),
            "amount": float(r.get("amount", 0)),
            "pct": 0.0, "turnover": float(r.get("turnover", 0)),
        })
    for i in range(1, len(bars)):
        if bars[i - 1]["close"] > 0:
            bars[i]["pct"] = round(
                (bars[i]["close"] - bars[i - 1]["close"]) / bars[i - 1]["close"] * 100, 2)
    return bars


def collect_news(code, limit=15):
    df = _retry(lambda: ak.stock_news_em(symbol=code))
    stock_url = f"https://emweb.securities.eastmoney.com/pc_hsf10/pages/index.html?type=web&code={'SH' if code.startswith('6') else 'SZ'}{code}#/news"
    items = []
    for _, r in df.head(limit).iterrows():
        news_url = str(r.get("新闻链接", ""))
        items.append({
            "id": f"N-{len(items)+1:02d}",
            "title": str(r.get("新闻标题", "")),
            "content": str(r.get("新闻内容", ""))[:600],
            "time": str(r.get("发布时间", "")),
            "source": str(r.get("文章来源", "")),
            "url": news_url if news_url else stock_url,
        })
    return items


def collect_reports(code, limit=30):
    df = _retry(lambda: ak.stock_research_report_em(symbol=code))
    items = []
    report_url = f"https://data.eastmoney.com/report/zw/stock/{code}.html"
    for _, r in df.head(limit).iterrows():
        items.append({
            "id": f"R-{len(items)+1:02d}",
            "title": str(r.get("报告名称", "")),
            "rating": str(r.get("东财评级", "")),
            "org": str(r.get("机构", "")),
            "eps_2026": str(r.get("2026-盈利预测-收益", "")),
            "pe_2026": str(r.get("2026-盈利预测-市盈率", "")),
            "eps_2027": str(r.get("2027-盈利预测-收益", "")),
            "pe_2027": str(r.get("2027-盈利预测-市盈率", "")),
            "eps_2028": str(r.get("2028-盈利预测-收益", "")),
            "pe_2028": str(r.get("2028-盈利预测-市盈率", "")),
            "date": str(r.get("日期", "")),
            "url": report_url,
        })
    return items


def collect_financials(code):
    df = _retry(lambda: ak.stock_financial_abstract(symbol=code))
    records = df.to_dict("records")
    fin_url = f"https://emweb.securities.eastmoney.com/pc_hsf10/pages/index.html?type=web&code={'SH' if code.startswith('6') else 'SZ'}{code}#/cwfx"
    for r in records:
        r["url"] = fin_url
    return records


# ============================================================
# 高价值平台
# ============================================================

def collect_cninfo(code, limit=15):
    """巨潮资讯 — 官方公告 (年报/定增/回购/减持)"""
    try:
        r = requests.post("http://www.cninfo.com.cn/new/information/topSearch/query",
                          headers={"User-Agent": UA}, data={"keyWord": code, "maxNum": 5}, timeout=10)
        arr = r.json()
        if isinstance(arr, list) and arr:
            org_id = arr[0].get("orgId", "")
        elif isinstance(arr, dict) and arr.get("arr"):
            org_id = arr["arr"][0].get("orgId", "")
        else:
            return []
    except Exception:
        return []

    plate = "sh" if code.startswith("6") else "sz"
    column = "sse" if code.startswith("6") else "szse"
    end = datetime.now().strftime("%Y-%m-%d")
    start = (datetime.now() - timedelta(days=365)).strftime("%Y-%m-%d")
    try:
        r2 = requests.post("http://www.cninfo.com.cn/new/hisAnnouncement/query",
                           headers={"User-Agent": UA},
                           data={"pageNum": 1, "pageSize": limit,
                                 "column": column, "tabName": "fulltext",
                                 "stock": f"{code},{org_id}",
                                 "searchkey": "", "secid": "",
                                 "category": "", "plate": plate,
                                 "seDate": f"{start}~{end}"},
                           timeout=10)
        anns = r2.json().get("announcements", []) or []
        return [{"id": f"C-{i+1:02d}", "title": a.get("announcementTitle", ""),
                 "date": datetime.fromtimestamp(
                     a.get("announcementTime", 0) / 1000
                 ).strftime("%Y-%m-%d") if a.get("announcementTime") else "",
                 "type": a.get("announcementTypeName", ""),
                 "url": f"http://static.cninfo.com.cn/{a.get('adjunctUrl', '')}"
                 } for i, a in enumerate(anns[:limit])]
    except Exception:
        return []


def collect_ir(code, limit=15):
    """互动易 — 投资者问答 (公司官方回应)"""
    ir_url = f"http://irm.cninfo.com.cn/ircs/search?keyword={code}"
    try:
        df = ak.stock_irm_cninfo(symbol=code)
        items = []
        for i, (_, r) in enumerate(df.head(limit).iterrows()):
            items.append({
                "id": f"IR-{i+1:02d}",
                "question": str(r.get("提问内容", r.get("问题", "")))[:200],
                "answer": str(r.get("回答内容", r.get("回复", "")))[:300],
                "date": str(r.get("提问时间", r.get("日期", ""))),
                "source": "互动易",
                "url": ir_url,
            })
        return items
    except Exception:
        return []


def collect_ths(code):
    """同花顺 — 千股千评/财务指标"""
    url = f"http://basic.10jqka.com.cn/{code}/"
    try:
        resp = _retry(lambda: requests.get(url, headers={"User-Agent": UA}, timeout=10))
        soup = BeautifulSoup(resp.text, "html.parser")
        data = {"url": url, "tables": [], "evaluation": ""}
        eval_el = soup.find("span", id="evaluation")
        if eval_el:
            data["evaluation"] = eval_el.get_text(strip=True)
        for table in soup.find_all("table"):
            rows = []
            for tr in table.find_all("tr"):
                cells = [td.get_text(strip=True) for td in tr.find_all(["td", "th"])]
                if cells:
                    rows.append(cells)
            if rows:
                data["tables"].append(rows)
        highlight = soup.find("span", class_="company-highlight")
        if highlight:
            data["highlight"] = highlight.get_text(strip=True)
        return data
    except Exception:
        return {"tables": [], "evaluation": ""}


def collect_sina_fund(code):
    """新浪 — 资金流向 (主力净流入)"""
    prefix = "sh" if code.startswith("6") else "sz"
    sym = f"{prefix}{code}"
    url = (f"http://vip.stock.finance.sina.com.cn/quotes_service/api/json_v2.php"
           f"/MoneyFlow.ssl_bkzj_bk?page=1&num=10&sort=opendate&asc=0&fenlei=1&node={sym}")
    try:
        r = requests.get(url, headers={"User-Agent": UA}, timeout=10)
        text = r.text.strip()
        if text.startswith("["):
            data = json.loads(text)
            return [{"date": d.get("opendate", ""),
                     "main_net": d.get("r0_net", ""),
                     "main_pct": d.get("r0_pct", ""),
                     "super_net": d.get("r3_net", ""),
                     "big_net": d.get("r1_net", ""),
                     } for d in data[:10]]
        return []
    except Exception:
        return []


def collect_lhb(code):
    """东财 — 近3月龙虎榜"""
    end = datetime.now().strftime("%Y%m%d")
    start = (datetime.now() - timedelta(days=90)).strftime("%Y%m%d")
    lhb_url = f"https://data.eastmoney.com/stock/lhb,{code}.html"
    try:
        df = ak.stock_lhb_detail_em(start_date=start, end_date=end)
        if "代码" in df.columns:
            df = df[df["代码"] == code]
        elif "股票代码" in df.columns:
            df = df[df["股票代码"] == code]
        records = df.to_dict("records")
        for r in records:
            r["url"] = lhb_url
        return records
    except Exception:
        return []


def collect_xueqiu(code):
    """雪球 — 个股基本面"""
    sym = f"SH{code}" if code.startswith("6") else f"SZ{code}"
    xq_url = f"https://xueqiu.com/S/{sym}"
    try:
        df = ak.stock_individual_basic_info_xq(symbol=sym)
        records = df.to_dict("records")
        for r in records:
            r["url"] = xq_url
        return records
    except Exception:
        return []


def collect_comment(code):
    """东财 — 市场情绪/综合评价"""
    comment_url = f"https://emweb.securities.eastmoney.com/pc_hsf10/pages/index.html?type=web&code={'SH' if code.startswith('6') else 'SZ'}{code}"
    try:
        df = ak.stock_comment_em(symbol=code)
        records = df.to_dict("records")
        for r in records:
            r["url"] = comment_url
        return records
    except Exception:
        return []


# ============================================================
# 情绪平台
# ============================================================

def collect_guba(code, pages=3):
    """东方财富股吧帖子"""
    posts = []
    for page in range(1, pages + 1):
        url = f"https://guba.eastmoney.com/list,{code}_{page}.html"
        try:
            resp = requests.get(url, headers=HEADERS, timeout=12)
            resp.encoding = "utf-8"
            soup = BeautifulSoup(resp.text, "html.parser")
            found = soup.select("span.l3 a, div.l3 a, .l3 a")
            if not found:
                found = [a for a in soup.select("a[href*='/news,']") if a.get_text(strip=True)]
            for a in found:
                t = a.get_text(strip=True)
                href = a.get("href", "")
                if t and len(t) > 3 and "条新消息" not in t:
                    full = href if href.startswith("http") else "https://guba.eastmoney.com" + href
                    posts.append({"id": f"P-{len(posts)+1:02d}", "title": t,
                                  "url": full, "source": "股吧", "page": page})
        except Exception as e:
            print(f"  [guba p{page}] {e}")
        time.sleep(0.4)
    seen = set(); deduped = []
    for p in posts:
        if p["title"] not in seen:
            seen.add(p["title"]); deduped.append(p)
    return deduped[:30]


def collect_taoguba(code, name="", limit=15):
    """淘股吧 — 短线情绪/技术分析帖"""
    keyword = name if name else code
    url = f"https://www.taoguba.com.cn/search?keyword={keyword}"
    try:
        resp = _retry(lambda: requests.get(url, headers={"User-Agent": UA}, timeout=10))
        soup = BeautifulSoup(resp.text, "html.parser")
        items = []
        for a in soup.find_all("a", href=True):
            href = a["href"]
            if "/article/" in href:
                title = a.get_text(strip=True)
                if title and len(title) > 3:
                    items.append({"id": f"TG-{len(items)+1:02d}", "title": title[:100],
                                  "url": href, "source": "淘股吧"})
                    if len(items) >= limit:
                        break
        return items
    except Exception:
        return []


# ============================================================
# 主采集函数
# ============================================================

def get_platform_list():
    """返回平台列表 (供前端展示)"""
    return [{"id": k, **v} for k, v in PLATFORM_REGISTRY.items()]


def collect(code, name="", outdir="data", platforms=None, filter_emotion=True):
    """
    主采集函数
    platforms: 平台 id 列表, None=全部
    filter_emotion: 是否过滤情绪帖 (仅影响 guba/taoguba)
    """
    if platforms is None:
        platforms = DEFAULT_PLATFORMS

    os.makedirs(outdir, exist_ok=True)
    prefix = "SH" if code.startswith("6") else "SZ"
    stock_url = f"https://emweb.securities.eastmoney.com/pc_hsf10/pages/index.html?type=web&code={prefix}{code}"
    result = {
        "code": code, "name": name,
        "stock_url": stock_url,
        "guba_url": f"https://guba.eastmoney.com/list,{code}.html",
        "cninfo_url": f"http://www.cninfo.com.cn/new/disclosure/stock?stockCode={code}&orgId=",
        "fetch_time": datetime.now().isoformat(),
    }
    print(f"\n>>> [{code}] {name} | 平台: {len(platforms)}个")

    # 平台调度表
    all_sources = [
        ("kline",      lambda: collect_kline(code)),
        ("news",       lambda: collect_news(code)),
        ("reports",    lambda: collect_reports(code)),
        ("financials", lambda: collect_financials(code)),
        ("cninfo",     lambda: collect_cninfo(code)),
        ("ir",         lambda: collect_ir(code)),
        ("ths",        lambda: collect_ths(code)),
        ("sina_fund",  lambda: collect_sina_fund(code)),
        ("lhb",        lambda: collect_lhb(code)),
        ("xueqiu",     lambda: collect_xueqiu(code)),
        ("comment",    lambda: collect_comment(code)),
        ("guba",       lambda: collect_guba(code)),
        ("taoguba",    lambda: collect_taoguba(code, name)),
    ]

    for key, fn in all_sources:
        if key not in platforms:
            continue
        try:
            data = fn()
            # 情绪帖过滤
            if filter_emotion and key in ("guba", "taoguba") and isinstance(data, list):
                original = len(data)
                data = _filter_emotional_posts(data, keep_threshold=1)
                filtered = original - len(data)
                if filtered > 0:
                    print(f"  [{key:11s}] {len(data)} (过滤{filtered}条情绪帖)")
                else:
                    print(f"  [{key:11s}] {len(data)}")
            else:
                n = len(data) if isinstance(data, list) else 1
                print(f"  [{key:11s}] {n}")
            result[key] = data
        except Exception as e:
            result[key] = []
            print(f"  [{key:11s}] FAIL: {e}")

    outf = os.path.join(outdir, f"{code}_raw.json")
    with open(outf, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, default=str, indent=2)
    print(f"  -> {outf}")

    # 统计
    total = 0
    plats = set()
    for k, v in result.items():
        if k in ("code", "name", "fetch_time"):
            continue
        if isinstance(v, list) and v:
            total += len(v)
            plats.add(PLATFORM_REGISTRY.get(k, {}).get("label", k))
    print(f"  TOTAL={total} data pts | platforms={len(plats)}")
    return result


if __name__ == "__main__":
    code = sys.argv[1] if len(sys.argv) > 1 else "002371"
    name = sys.argv[2] if len(sys.argv) > 2 else ""
    # 如果未提供 name，尝试自动解析
    if not name:
        try:
            from stock_resolver import resolve
            info = resolve(code)
            name = info.get("name", code)
            print(f"自动解析: {code} → {name} | {info.get('industry', '')}")
        except Exception:
            name = code
    collect(code, name)
