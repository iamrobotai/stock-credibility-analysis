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
    "kline":         {"label": "K线(新浪)",       "category": "core",     "value": "high",   "desc": "前复权全历史日线，分段+曲线基础"},
    "news":          {"label": "东财新闻",         "category": "core",     "value": "high",   "desc": "公司相关新闻，含来源和时间"},
    "reports":       {"label": "东财研报",         "category": "core",     "value": "high",   "desc": "机构研报，含EPS/PE/评级预测"},
    "financials":    {"label": "东财财务摘要",     "category": "core",     "value": "high",   "desc": "财务基本面数据"},
    # 高价值 (默认启用)
    "cninfo":        {"label": "巨潮资讯(公告)",   "category": "high",     "value": "high",   "desc": "官方公告：年报/定增/回购/减持"},
    "ir":            {"label": "互动易(问答)",     "category": "high",     "value": "high",   "desc": "投资者问答，公司官方回应"},
    "ths":           {"label": "同花顺(千股千评)", "category": "high",     "value": "medium", "desc": "千股千评/财务指标/公司亮点"},
    "sina_fund":     {"label": "新浪资金流向",     "category": "high",     "value": "medium", "desc": "主力净流入/大单/超大单"},
    "lhb":           {"label": "东财龙虎榜",       "category": "high",     "value": "medium", "desc": "近3月龙虎榜明细"},
    "xueqiu":        {"label": "雪球(基本面)",     "category": "high",     "value": "medium", "desc": "雪球个股基本面信息，需登录爬取", "browser": True},
    "xueqiu_posts":  {"label": "雪球(讨论帖)",     "category": "high",     "value": "medium", "desc": "雪球社区讨论帖，需浏览器登录抓取", "browser": True},
    "zhihu":         {"label": "知乎(讨论)",       "category": "high",     "value": "medium", "desc": "知乎相关问答与文章，需浏览器登录抓取", "browser": True},
    "comment":       {"label": "东财评论",         "category": "high",     "value": "medium", "desc": "市场情绪指标/综合评价"},
    # 情绪 (可选，默认启用但带过滤)
    "guba":          {"label": "东财股吧",         "category": "emotional","value": "low",    "desc": "散户讨论帖，情绪化较多"},
    "taoguba":       {"label": "淘股吧",           "category": "emotional","value": "low",    "desc": "短线情绪/技术分析帖，需浏览器登录抓取", "browser": True},
    # 数据维度 (M3.1: 北向/两融/股东/解禁/大宗) — 依赖网络, 缺失优雅降级
    "north_fund":    {"label": "北向资金(沪深港通)","category": "high",     "value": "high",   "desc": "北向持股数/比例/市值及 1/5/10 日变化"},
    "margin":        {"label": "融资融券",         "category": "high",     "value": "medium", "desc": "融资余额/融券余额(杠杆资金方向)"},
    "holder_num":    {"label": "股东户数",         "category": "high",     "value": "medium", "desc": "股东户数变化(筹码集中度)"},
    "unlock":        {"label": "限售解禁",         "category": "high",     "value": "low",    "desc": "未来解禁规模与占比"},
    "block_trade":   {"label": "大宗交易",         "category": "high",     "value": "low",    "desc": "大宗交易折溢价与买卖席位"},
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


def _retry(fn, tries=2, delay=1.0):
    """网络调用重试。tries=2 + delay=1.0：单源故障时快速失败，
    避免整批任务因某个慢/挂源长时间阻塞（原 3/1.5 最坏 ~34s/源）。"""
    for i in range(tries):
        try:
            return fn()
        except Exception as e:
            if i == tries - 1:
                raise
            time.sleep(delay * (i + 1))
    return None


def probe_sources():
    """快速探测主要数据源可达性（4s 短超时），返回可读状态列表。
    用于批量任务启动时诊断「网络超时」真实原因，而非笼统报错。"""
    probes = [
        ("东财push2", "https://82.push2.eastmoney.com/api/qt/clist/get?pn=1&pz=1&po=1&np=1&fltt=2&invt=2&fid=f3&fs=m:0+t:6&fields=f12"),
        ("新浪行情", "https://vip.stock.finance.sina.com.cn/quotes_service/api/json_v2.php/Market_Center.getHQNodeData?page=1&num=1&sort=changepercent&asc=0&node=hs_a"),
        ("雪球", "https://xueqiu.com/"),
        ("股吧", "https://guba.eastmoney.com/"),
    ]
    out = []
    for name, url in probes:
        try:
            r = requests.get(url, headers={"User-Agent": UA}, timeout=4)
            out.append(f"{name}: {'✅可达' if r.status_code == 200 else '⚠️HTTP ' + str(r.status_code)}")
        except Exception as e:
            out.append(f"{name}: ❌不可达 ({type(e).__name__})")
    return out


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
    """雪球 — 个股基本面（登录态 cookie 复用优先，akshare 兜底）"""
    sym = f"SH{code}" if code.startswith("6") else f"SZ{code}"
    xq_url = f"https://xueqiu.com/S/{sym}"
    # 优先：浏览器登录爬取（带 cookie 调官方 quote 接口，最稳）
    try:
        from browser_login import load_cookies, scrape_xueqiu_fundamentals, is_available
        if is_available():
            ck = load_cookies("xueqiu")
            if ck:
                fund = scrape_xueqiu_fundamentals(ck, code)
                if fund:
                    fund["url"] = xq_url
                    return [fund]
                else:
                    print("  [xueqiu] 已登录cookie但无数据，请运行 login_and_scrape.py 重新登录")
    except Exception as e:
        print(f"  [xueqiu] 登录爬取失败: {e}")
    # 兜底：akshare
    try:
        df = ak.stock_individual_basic_info_xq(symbol=sym)
        records = df.to_dict("records")
        for r in records:
            r["url"] = xq_url
        return records
    except Exception:
        return []


def collect_xueqiu_posts(code, name="", use_browser=True, incremental=False):
    """
    雪球 — 社区讨论帖

    Args:
        code: 股票代码
        name: 股票名称
        use_browser: 是否使用浏览器抓取 (应对反爬)
        incremental: 是否增量更新

    Returns:
        list[dict]: 帖子列表
    """
    posts = []

    if use_browser:
        try:
            from browser_login import load_cookies, scrape_xueqiu_posts, is_available
            if is_available():
                ck = load_cookies("xueqiu")
                if ck:
                    posts = scrape_xueqiu_posts(ck, code, max_count=30)
                    if not posts:
                        print("  [xueqiu_posts] 已登录cookie无数据，请运行 login_and_scrape.py 重新登录")
                else:
                    print("  [xueqiu_posts] 无登录cookie，请先运行 login_and_scrape.py 完成雪球登录")
            else:
                print("  [xueqiu_posts] Playwright 未安装，尝试 API 抓取")
        except ImportError:
            pass

    # API 备用方案 (雪球 API)
    if not posts:
        sym = f"SH{code}" if code.startswith("6") else f"SZ{code}"
        xq_url = f"https://xueqiu.com/S/{sym}"
        s = requests.Session()
        s.headers.update({"User-Agent": UA, "Referer": "https://xueqiu.com/"})
        try:
            s.get("https://xueqiu.com/", timeout=10)  # 获取 cookie
            # 雪球状态流 API
            api_url = f"https://xueqiu.com/v4/statuses/symbol_timeline.json?symbol={sym}&count=30&source=user"
            r = s.get(api_url, timeout=10)
            data = r.json()
            statuses = data.get("statuses", []) or data.get("list", []) or []
            for i, st in enumerate(statuses[:30]):
                title = st.get("title", "") or st.get("description", "")[:80]
                if not title:
                    title = st.get("text", "")[:80]
                posts.append({
                    "id": f"XQ-{i+1:02d}",
                    "title": title[:100],
                    "author": st.get("user", {}).get("screen_name", ""),
                    "time": datetime.fromtimestamp(
                        st.get("created_at", 0) / 1000
                    ).strftime("%Y-%m-%d %H:%M") if st.get("created_at") else "",
                    "url": f"https://xueqiu.com{st.get('target', '')}",
                    "content": st.get("description", st.get("text", ""))[:500],
                    "replies": str(st.get("reply_count", 0)),
                    "source": "雪球",
                })
        except Exception as e:
            print(f"  [xueqiu_posts] API 抓取失败: {e}")

    # 增量更新：合并旧数据
    if incremental:
        try:
            from incremental_manager import get_state, merge_data, update_state, get_resume_point
            old_data = []
            raw_path = os.path.join(
                os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                "data", f"{code}_raw.json"
            )
            if os.path.exists(raw_path):
                with open(raw_path, encoding="utf-8") as f:
                    old_raw = json.load(f)
                old_data = old_raw.get("xueqiu_posts", [])

            merged, new_count = merge_data(old_data, posts, key_field="title")
            update_state(code, "xueqiu_posts",
                         last_post_id=posts[0]["id"] if posts else "",
                         total_fetched=len(merged))
            print(f"  [xueqiu_posts] 增量: 新增 {new_count} 条 / 总计 {len(merged)} 条")
            return merged
        except Exception as e:
            print(f"  [xueqiu_posts] 增量合并失败: {e}")

    return posts


def collect_zhihu(code, name="", use_browser=True, incremental=False):
    """
    知乎 — 股票相关问答与文章

    Args:
        code: 股票代码
        name: 股票名称 (用于搜索)
        use_browser: 是否使用浏览器抓取
        incremental: 是否增量更新

    Returns:
        list[dict]: 知乎搜索结果列表
    """
    keyword = name if name else code
    results = []

    if use_browser:
        try:
            from browser_login import (load_cookies, BrowserSession,
                                       inject_cookies, scrape_zhihu, is_available)
            if is_available():
                ck = load_cookies("zhihu")
                if ck:
                    with BrowserSession("zhihu", headless=True) as (ctx, page):
                        inject_cookies(ctx, ck)
                        results = scrape_zhihu(page, keyword, max_count=20)
                    if not results:
                        print("  [zhihu] 已登录cookie无数据，请运行 login_and_scrape.py 重新登录")
                else:
                    print("  [zhihu] 无登录cookie，请先运行 login_and_scrape.py 完成知乎登录")
            else:
                print("  [zhihu] Playwright 未安装，尝试 API 抓取")
        except ImportError:
            pass

    # API 备用方案
    if not results:
        try:
            import urllib.parse
            encoded = urllib.parse.quote(keyword)
            url = f"https://www.zhihu.com/api/v4/search_v3?t=general&q={encoded}&correction=1&offset=0&limit=20"
            s = requests.Session()
            s.headers.update({
                "User-Agent": UA,
                "Referer": f"https://www.zhihu.com/search?type=content&q={encoded}",
            })
            # 先访问主页获取 cookie
            try:
                s.get("https://www.zhihu.com/", timeout=10)
            except Exception:
                pass
            r = s.get(url, timeout=10)
            data = r.json()
            items = data.get("data", []) or []
            for i, item in enumerate(items[:20]):
                obj = item.get("object", {})
                title = obj.get("title", "") or obj.get("question", {}).get("name", "")
                excerpt = obj.get("excerpt", "") or obj.get("content", "")[:400]
                author = obj.get("author", {}).get("name", "")
                zhihu_url = obj.get("url", "")
                if zhihu_url and not zhihu_url.startswith("http"):
                    zhihu_url = "https://www.zhihu.com" + zhihu_url
                votes = str(obj.get("voteup_count", 0))
                if title:
                    results.append({
                        "id": f"ZH-{i+1:02d}",
                        "title": title[:120],
                        "author": author,
                        "url": zhihu_url,
                        "excerpt": excerpt,
                        "votes": votes,
                        "source": "知乎",
                    })
        except Exception as e:
            print(f"  [zhihu] API 抓取失败: {e}")

    # 增量更新
    if incremental:
        try:
            from incremental_manager import merge_data, update_state
            old_data = []
            raw_path = os.path.join(
                os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                "data", f"{code}_raw.json"
            )
            if os.path.exists(raw_path):
                with open(raw_path, encoding="utf-8") as f:
                    old_raw = json.load(f)
                old_data = old_raw.get("zhihu", [])
            merged, new_count = merge_data(old_data, results, key_field="title")
            update_state(code, "zhihu",
                         last_keyword=keyword,
                         total_fetched=len(merged))
            print(f"  [zhihu] 增量: 新增 {new_count} 条 / 总计 {len(merged)} 条")
            return merged
        except Exception as e:
            print(f"  [zhihu] 增量合并失败: {e}")

    return results


def collect_comment(code):
    """东财 — 市场情绪/综合评价 (综合得分/机构参与度/主力成本/关注指数)"""
    comment_url = f"https://emweb.securities.eastmoney.com/pc_hsf10/pages/index.html?type=web&code={'SH' if code.startswith('6') else 'SZ'}{code}"
    try:
        # 新版 akshare: stock_comment_em() 无参，返回全市场，需按代码过滤
        df = _retry(lambda: ak.stock_comment_em())
        col = "代码" if "代码" in df.columns else ("股票代码" if "股票代码" in df.columns else None)
        if col:
            df = df[df[col].astype(str) == str(code)]
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
    """淘股吧 — 短线情绪/技术分析帖（浏览器爬取优先，requests 兜底）"""
    keyword = name if name else code
    # 优先：浏览器爬取（更抗反爬；已登录则复用 cookie）
    try:
        from browser_login import (load_cookies, BrowserSession,
                                   inject_cookies, scrape_taoguba, is_available)
        if is_available():
            ck = load_cookies("taoguba")
            if ck:  # 仅在曾登录过时才开浏览器，避免逐股无谓开销
                with BrowserSession("taoguba", headless=True) as (ctx, page):
                    inject_cookies(ctx, ck)
                    items = scrape_taoguba(page, keyword, max_count=limit)
                    if items:
                        return items
    except Exception as e:
        print(f"  [taoguba] 浏览器爬取失败: {e}")
    # 兜底：requests
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
# M3.1 数据维度采集 (北向 / 两融 / 股东户数 / 解禁 / 大宗)
# 说明: 全部依赖 akshare 实时接口, 网络缺失或损坏时返回
#       {"available": False, "reason": ...} 的结构化空值, 不影响既有流水线。
# ============================================================

def _empty(kind: str, reason: str = "") -> dict:
    """新维度采集的统一空值结构。"""
    return {"available": False, "kind": kind,
            "reason": (reason or "无数据 / 接口异常")[:120]}

def _num(x):
    if x is None:
        return float("nan")
    if isinstance(x, (int, float)):
        return float(x)
    s = str(x).strip().replace(",", "").replace("%", "").replace("亿", "")
    if s in ("", "-", "--", "None", "nan", "NaN"):
        return float("nan")
    try:
        return float(s)
    except Exception:
        return float("nan")

def collect_north_fund(code):
    """北向资金(沪深港通个股持股) — 单股。

    接口: ak.stock_hsgt_individual_detail_em(symbol="沪股通"/"深股通")
    解析: 按股票代码过滤, 取最新一行, 提取持股数/比例/市值及 1/5/10 日变化。
    """
    try:
        sym = "沪股通" if str(code).startswith("6") else "深股通"
        df = ak.stock_hsgt_individual_detail_em(symbol=sym)
        if df is None or (hasattr(df, "empty") and df.empty):
            return _empty("north_fund", "北向明细为空")
        col = ("股票代码" if "股票代码" in getattr(df, "columns", [])
                else ("代码" if "代码" in getattr(df, "columns", []) else None))
        if col is None:
            return _empty("north_fund", "北向明细无代码列")
        df = df[df[col].astype(str).str.contains(str(code))]
        if df.empty:
            return _empty("north_fund", "该股本向无持仓/未上榜")
        r = df.iloc[-1].to_dict()
        def g(*cands):
            for c in cands:
                if c in r and r[c] not in (None, ""):
                    return r[c]
            return None
        return {
            "available": True,
            "hold_shares": _num(g("持股数", "持股数量")),
            "hold_pct": _num(g("持股比例", "持股占流通股比")),
            "hold_market_cap": _num(g("持股市值", "持股市值(元)")),
            "chg_1d_shares": _num(g("持股数变化-1日", "持股变动")),
            "chg_1d_pct": _num(g("持股比例变化-1日")),
            "chg_5d_pct": _num(g("持股比例变化-5日")),
            "chg_10d_pct": _num(g("持股比例变化-10日")),
            "as_of": str(g("日期", "持股日期", "交易日期") or ""),
        }
    except Exception as e:
        return _empty("north_fund", str(e)[:80])

def collect_margin(code):
    """融资融券(单股) — 沪市 stock_margin_detail_sse / 深市 stock_margin_detail_szse。

    解析: 取最新一行, 融资买入额/融资余额/融券卖出量/融券余额。
    """
    try:
        fn = (ak.stock_margin_detail_sse if str(code).startswith("6")
              else ak.stock_margin_detail_szse)
        df = fn(symbol=code)
        if df is None or (hasattr(df, "empty") and df.empty):
            return _empty("margin", "两融明细为空")
        r = df.iloc[-1].to_dict()
        def g(*cands):
            for c in cands:
                if c in r and r[c] not in (None, ""):
                    return r[c]
            return None
        return {
            "available": True,
            "fin_buy": _num(g("融资买入额", "融资买入量")),
            "fin_balance": _num(g("融资余额")),
            "fin_balance_chg": _num(g("融资余额变化", "融资偿还额")),
            "sec_sell": _num(g("融券卖出量", "融券卖出额")),
            "sec_balance": _num(g("融券余额")),
            "as_of": str(g("日期", "交易日期") or ""),
        }
    except Exception as e:
        return _empty("margin", str(e)[:80])

def collect_holder_num(code):
    """股东户数(单股) — ak.stock_zh_a_gdhs。

    解析: 取最新一行, 股东户数 / 截止日期 / 较上期变化(户) / 变动比例(%)。
    """
    try:
        df = ak.stock_zh_a_gdhs(symbol=code)
        if df is None or (hasattr(df, "empty") and df.empty):
            return _empty("holder_num", "股东户数数据为空")
        r = df.iloc[-1].to_dict()
        def g(*cands):
            for c in cands:
                if c in r and r[c] not in (None, ""):
                    return r[c]
            return None
        return {
            "available": True,
            "holder_count": _num(g("股东户数", "股东总数")),
            "date": str(g("截止日期", "日期") or ""),
            "change_holders": _num(g("较上期变化(户)", "股东户数-变化")),
            "change_pct": _num(g("变动比例(%)", "股东户数-变化比例")),
            "price": _num(g("股东户数-股价(元)")),
        }
    except Exception as e:
        return _empty("holder_num", str(e)[:80])

def collect_unlock(code):
    """限售解禁(单股) — ak.stock_restricted_release_detail_em(symbol="SH"/"SZ"+code)。"""
    try:
        prefix = "SH" if str(code).startswith("6") else "SZ"
        df = ak.stock_restricted_release_detail_em(symbol=f"{prefix}{code}")
        if df is None or (hasattr(df, "empty") and df.empty):
            return _empty("unlock", "无解禁数据")
        out = []
        for r in df.to_dict("records")[:10]:
            out.append({
                "date": str(r.get("解禁日期", r.get("上市日", "")) or ""),
                "shares": _num(r.get("解禁数量", r.get("解禁股数"))),
                "market_cap": _num(r.get("解禁市值")),
                "pct": _num(r.get("解禁占比", r.get("占流通股比"))),
            })
        return {"available": True, "items": out}
    except Exception as e:
        return _empty("unlock", str(e)[:80])

def collect_block_trade(code):
    """大宗交易(单股) — ak.stock_dzjy_mrmx(symbol=code)。

    解析: 取近 15 笔, 成交日期/价/量/额/折溢价率/买卖方营业部。
    """
    try:
        df = ak.stock_dzjy_mrmx(symbol=code)
        if df is None or (hasattr(df, "empty") and df.empty):
            return _empty("block_trade", "无大宗交易")
        out = []
        for r in df.to_dict("records")[:15]:
            out.append({
                "date": str(r.get("成交日期", r.get("日期", "")) or ""),
                "price": _num(r.get("成交价")),
                "volume": _num(r.get("成交量", r.get("成交数量"))),
                "amount": _num(r.get("成交额")),
                "premium": _num(r.get("溢价率", r.get("折溢价率"))),
                "buyer": str(r.get("买方营业部", r.get("买方", "")) or ""),
                "seller": str(r.get("卖方营业部", r.get("卖方", "")) or ""),
            })
        return {"available": True, "items": out}
    except Exception as e:
        return _empty("block_trade", str(e)[:80])

# ============================================================
# 主采集函数
# ============================================================

def get_platform_list():
    """返回平台列表 (供前端展示)"""
    return [{"id": k, **v} for k, v in PLATFORM_REGISTRY.items()]


def _exchange_of(code):
    """根据代码前缀判断交易所。"""
    if code.startswith(("6", "9")):
        return "上交所(SH)"
    if code.startswith(("0", "3")):
        return "深交所(SZ)"
    if code.startswith(("8", "4")):
        return "北交所(BJ)"
    return "未知"


def collect_quote(code, name=None):
    """
    实时行情（新浪 hq），失败优雅降级到 K 线派生。
    返回 dict:
      available, source, name, code, exchange,
      price, open, prev_close, high, low,
      change, change_pct, volume(手), amount(元), date, time
    """
    info = {
        "available": False, "source": None,
        "name": name or code, "code": code,
        "exchange": _exchange_of(code),
        "price": None, "open": None, "prev_close": None,
        "high": None, "low": None, "change": None,
        "change_pct": None, "volume": None, "amount": None,
        "date": "", "time": "",
    }
    # 1) 新浪实时行情（最稳、字段无歧义）
    try:
        mkt = "sh" if code.startswith(("6", "9")) else ("sz" if code[0] in "03" else "bj")
        url = f"http://hq.sinajs.cn/list={mkt}{code}"
        r = requests.get(url, headers={"Referer": "https://finance.sina.com.cn",
                                       "User-Agent": UA}, timeout=8)
        txt = r.content.decode("gbk", errors="ignore")
        m = re.search(r'="(.*)"\s*;', txt)
        if m:
            parts = m.group(1).split(",")
            if len(parts) >= 11:
                name_q = parts[0]
                open_p = _num(parts[1]); prev = _num(parts[2])
                cur = _num(parts[3]); high = _num(parts[4]); low = _num(parts[5])
                vol = _num(parts[8])   # 手
                amt = _num(parts[9])   # 元
                date_m = re.search(r"\d{4}-\d{2}-\d{2}", txt)
                time_m = re.search(r"\d{2}:\d{2}:\d{2}", txt)
                date = date_m.group(0) if date_m else ""
                t = time_m.group(0) if time_m else ""
                if cur is not None and prev is not None and prev != 0:
                    chg = cur - prev
                    info.update({
                        "available": True, "source": "sina",
                        "name": name_q or name or code,
                        "price": cur, "open": open_p, "prev_close": prev,
                        "high": high, "low": low, "change": chg,
                        "change_pct": chg / prev * 100, "volume": vol,
                        "amount": amt, "date": date, "time": t,
                    })
                    return info
    except Exception:
        pass
    # 2) 降级：K 线最后两根
    try:
        kl = collect_kline(code)
        if isinstance(kl, list) and len(kl) >= 2:
            last = kl[-1]; prev_bar = kl[-2]
            cur = _num(last.get("close")); prev = _num(prev_bar.get("close"))
            if cur is not None and prev is not None and prev != 0:
                chg = cur - prev
                info.update({
                    "available": True, "source": "kline派生",
                    "price": cur,
                    "open": _num(last.get("open")),
                    "high": _num(last.get("high")),
                    "low": _num(last.get("low")),
                    "prev_close": prev, "change": chg,
                    "change_pct": chg / prev * 100,
                    "volume": _num(last.get("volume")),
                    "amount": None,
                    "date": str(last.get("date", "")), "time": "收盘",
                })
                return info
    except Exception:
        pass
    return info


def collect(code, name="", outdir="data", platforms=None, filter_emotion=True,
            use_browser=True, incremental=False):
    """
    主采集函数
    platforms: 平台 id 列表, None=全部
    filter_emotion: 是否过滤情绪帖 (仅影响 guba/taoguba)
    use_browser: 是否启用浏览器抓取 (用于雪球/知乎等需登录源)
    incremental: 是否增量更新 (仅影响 xueqiu_posts/zhihu/guba)
    """
    if platforms is None:
        platforms = DEFAULT_PLATFORMS

    os.makedirs(outdir, exist_ok=True)
    prefix = "SH" if code.startswith("6") else "SZ"
    stock_url = f"https://emweb.securities.eastmoney.com/pc_hsf10/pages/index.html?type=web&code={prefix}{code}"

    # 如果增量更新，尝试加载旧数据
    existing_data = {}
    if incremental:
        old_path = os.path.join(outdir, f"{code}_raw.json")
        if os.path.exists(old_path):
            try:
                with open(old_path, encoding="utf-8") as f:
                    existing_data = json.load(f)
                print(f"  [增量模式] 加载旧数据: {sum(len(v) for k,v in existing_data.items() if isinstance(v, list))} 条")
            except Exception:
                pass

    result = {
        "code": code, "name": name,
        "stock_url": stock_url,
        "guba_url": f"https://guba.eastmoney.com/list,{code}.html",
        "cninfo_url": f"http://www.cninfo.com.cn/new/disclosure/stock?stockCode={code}&orgId=",
        "fetch_time": datetime.now().isoformat(),
        "incremental": incremental,
    }
    print(f"\n>>> [{code}] {name} | 平台: {len(platforms)}个 | 浏览器: {'是' if use_browser else '否'} | 增量: {'是' if incremental else '否'}")

    # 平台调度表
    all_sources = [
        ("kline",         lambda: collect_kline(code)),
        ("news",          lambda: collect_news(code)),
        ("reports",       lambda: collect_reports(code)),
        ("financials",    lambda: collect_financials(code)),
        ("cninfo",        lambda: collect_cninfo(code)),
        ("ir",            lambda: collect_ir(code)),
        ("ths",           lambda: collect_ths(code)),
        ("sina_fund",     lambda: collect_sina_fund(code)),
        ("lhb",           lambda: collect_lhb(code)),
        ("xueqiu",        lambda: collect_xueqiu(code)),
        ("xueqiu_posts",  lambda: collect_xueqiu_posts(code, name, use_browser=use_browser, incremental=incremental)),
        ("zhihu",         lambda: collect_zhihu(code, name, use_browser=use_browser, incremental=incremental)),
        ("comment",       lambda: collect_comment(code)),
        ("guba",          lambda: collect_guba(code)),
        ("taoguba",       lambda: collect_taoguba(code, name)),
        # M3.1 数据维度
        ("north_fund",    lambda: collect_north_fund(code)),
        ("margin",        lambda: collect_margin(code)),
        ("holder_num",    lambda: collect_holder_num(code)),
        ("unlock",        lambda: collect_unlock(code)),
        ("block_trade",   lambda: collect_block_trade(code)),
    ]

    for key, fn in all_sources:
        if key not in platforms:
            continue

        # 增量模式下，核心数据源仍然全量采集
        is_core = PLATFORM_REGISTRY.get(key, {}).get("category") == "core"
        is_browser_platform = PLATFORM_REGISTRY.get(key, {}).get("browser", False)

        # 浏览器源在未启用浏览器时跳过
        if is_browser_platform and not use_browser:
            result[key] = []
            print(f"  [{key:15s}] 跳过 (需浏览器抓取)")
            continue

        try:
            data = fn()

            # 增量合并 (非核心数据)
            if incremental and not is_core and existing_data:
                old_list = existing_data.get(key, [])
                if isinstance(data, list) and isinstance(old_list, list) and old_list:
                    from incremental_manager import merge_data
                    data, new_count = merge_data(old_list, data, key_field="title")
                    print(f"  [{key:15s}] {len(data)} (增量新增 {new_count})")
                    result[key] = data
                    continue

            # 情绪帖过滤
            if filter_emotion and key in ("guba", "taoguba") and isinstance(data, list):
                original = len(data)
                data = _filter_emotional_posts(data, keep_threshold=1)
                filtered = original - len(data)
                if filtered > 0:
                    print(f"  [{key:15s}] {len(data)} (过滤{filtered}条情绪帖)")
                else:
                    print(f"  [{key:15s}] {len(data)}")
            else:
                n = len(data) if isinstance(data, list) else 1
                print(f"  [{key:15s}] {n}")
            result[key] = data
        except Exception as e:
            result[key] = []
            print(f"  [{key:15s}] FAIL: {e}")

    # 实时行情（独立于平台采集，graceful）
    try:
        result["quote"] = collect_quote(code, name)
    except Exception:
        result["quote"] = {"available": False, "source": None,
                              "code": code, "name": name}

    outf = os.path.join(outdir, f"{code}_raw.json")
    with open(outf, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, default=str, indent=2)
    print(f"  -> {outf}")

    # 统计
    total = 0
    plats = set()
    for k, v in result.items():
        if k in ("code", "name", "fetch_time", "stock_url", "guba_url", "cninfo_url", "incremental"):
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
