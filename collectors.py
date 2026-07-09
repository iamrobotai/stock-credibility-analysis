"""
多平台数据采集器 v2.0
====================
本地零-token 数据采集，覆盖以下平台：
  1. 新浪财经      - K线(前复权全历史)
  2. 东方财富      - 新闻/研报(直连API)/股吧/财务摘要/龙虎榜
  3. 巨潮资讯      - 官方公告(年报/定增/回购/减持)
  4. 互动易        - 投资者问答(公司回应)
  5. 同花顺        - 个股页面(千股千评/资金流向/财务指标)
  6. 雪球          - 个股页面(行情/讨论/关注度)
  7. 淘股吧        - 搜索(短线情绪/技术分析帖)
  8. 新浪财经      - 资金流向(主力净流入)
"""
import os, sys, json, time, re, traceback
from datetime import datetime, timedelta
from pathlib import Path

import requests
from bs4 import BeautifulSoup

# akshare only for a few stable endpoints
import akshare as ak

UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
HEADERS = {"User-Agent": UA, "Accept": "application/json,text/html,*/*"}
DATA_DIR = Path(__file__).parent / "data"
DATA_DIR.mkdir(exist_ok=True)


def _retry(fn, retries=3, delay=1.0):
    for i in range(retries):
        try:
            return fn()
        except Exception as e:
            if i < retries - 1:
                time.sleep(delay * (i + 1))
            else:
                raise


# ============================================================
# 1. K线 (新浪源, 稳定)
# ============================================================
def collect_kline(code, days=1095):
    """新浪前复权日线"""
    prefix = "sh" if code.startswith("6") else "sz"
    sym = f"{prefix}{code}"
    df = _retry(lambda: ak.stock_zh_a_daily(symbol=sym, adjust="qfq"))
    # 截取近 days 天
    if len(df) > days:
        df = df.tail(days)
    bars = []
    for _, r in df.iterrows():
        bars.append({
            "date": str(r["date"]) if "date" in df.columns else str(r.iloc[0]),
            "open": float(r["open"]), "close": float(r["close"]),
            "high": float(r["high"]), "low": float(r["low"]),
            "volume": float(r.get("volume", 0)),
        })
    return bars


# ============================================================
# 2. 东财新闻
# ============================================================
def collect_news(code, limit=20):
    df = _retry(lambda: ak.stock_news_em(symbol=code))
    items = []
    for _, r in df.head(limit).iterrows():
        items.append({
            "title": str(r.get("新闻标题", "")),
            "content": str(r.get("新闻内容", ""))[:500],
            "time": str(r.get("发布时间", "")),
            "source": str(r.get("文章来源", "")),
            "url": str(r.get("新闻链接", "")),
        })
    return items


# ============================================================
# 3. 东财研报 (直连API, 更稳定)
# ============================================================
def collect_reports(code, limit=30):
    """直连 reportapi.eastmoney.com"""
    end = datetime.now().strftime("%Y-%m-%d")
    start = (datetime.now() - timedelta(days=548)).strftime("%Y-%m-%d")
    url = (
        "https://reportapi.eastmoney.com/report/list"
        f"?industryCode=*&pageSize={limit}&pageNo=1"
        f"&code={code}&beginTime={start.replace('-','')}&endTime={end.replace('-','')}"
        "&fields=&qType=0"
    )
    resp = _retry(lambda: requests.get(url, headers=HEADERS, timeout=15))
    data = resp.json()
    reports = data.get("data", []) or []
    items = []
    for r in reports:
        items.append({
            "title": r.get("title", ""),
            "org": r.get("orgSName", r.get("orgName", "")),
            "rating": r.get("emRatingName", ""),
            "publish_date": r.get("publishDate", "")[:10],
            "researcher": r.get("researcher", ""),
            "eps_next": r.get("predictNextTwoYearEps", ""),
            "pe_next": r.get("predictNextTwoYearPe", ""),
            "eps_year1": r.get("predictThisYearEps", ""),
            "pe_year1": r.get("predictThisYearPe", ""),
            "target_price": r.get("predictNextTwoYearPrice", ""),
            "url": f"https://data.eastmoney.com/report/zw_stock.jshtml?infoCode={r.get('infoCode','')}",
        })
    return items


# ============================================================
# 4. 东财股吧 (HTML 爬取)
# ============================================================
def collect_guba(code, limit=30):
    """东财股吧 - 带cookie session + 重试"""
    s = requests.Session()
    s.headers.update(HEADERS)
    s.headers["Referer"] = "https://guba.eastmoney.com/"
    # 先访问主页获取cookie
    try:
        s.get("https://guba.eastmoney.com/", timeout=5)
    except:
        pass

    items = []
    page = 1
    while len(items) < limit and page <= 3:
        url = f"https://guba.eastmoney.com/list,{code}_{page}.html"
        try:
            resp = s.get(url, timeout=10)
            # 检查是否被验证码拦截
            if len(resp.text) < 5000 and "captcha" in resp.text.lower():
                # 被拦截，跳过
                break
            soup = BeautifulSoup(resp.text, "html.parser")
            # 多种选择器
            rows = soup.find_all("div", class_="articleh")
            if not rows:
                rows = soup.find_all("span", class_="l3")
            if not rows:
                # 尝试找所有帖子链接
                for a in soup.find_all("a", href=True):
                    href = a["href"]
                    if f"/news,{code}," in href or f"/guba,{code}," in href:
                        title = a.get_text(strip=True)
                        if title and len(title) > 2:
                            items.append({"title": title, "page": page})
                            if len(items) >= limit:
                                break
                page += 1
                time.sleep(0.5)
                continue
            for row in rows:
                title_el = row.find("a") if hasattr(row, 'find') else row
                title = title_el.get_text(strip=True) if title_el else ""
                if title and len(title) > 2:
                    items.append({"title": title, "page": page})
                    if len(items) >= limit:
                        break
            page += 1
            time.sleep(0.5)
        except:
            break
    return items


# ============================================================
# 5. 东财财务摘要
# ============================================================
def collect_financials(code):
    df = _retry(lambda: ak.stock_financial_abstract(symbol=code))
    return df.to_dict("records")


# ============================================================
# 6. 东财龙虎榜
# ============================================================
def collect_lhb(code):
    """近3月龙虎榜"""
    end = datetime.now().strftime("%Y%m%d")
    start = (datetime.now() - timedelta(days=90)).strftime("%Y%m%d")
    try:
        df = ak.stock_lhb_detail_em(start_date=start, end_date=end)
        if "代码" in df.columns:
            df = df[df["代码"] == code]
        elif "股票代码" in df.columns:
            df = df[df["股票代码"] == code]
        return df.to_dict("records")
    except:
        return []


# ============================================================
# 7. 巨潮资讯 - 官方公告
# ============================================================
def collect_cninfo(code, limit=15):
    """巨潮资讯官方公告"""
    # 1. 查 orgId
    try:
        r = requests.post("http://www.cninfo.com.cn/new/information/topSearch/query",
                          headers=HEADERS, data={"keyWord": code, "maxNum": 5}, timeout=10)
        arr = r.json()
        if isinstance(arr, list) and arr:
            org_id = arr[0].get("orgId", "")
        elif isinstance(arr, dict) and arr.get("arr"):
            org_id = arr["arr"][0].get("orgId", "")
        else:
            return []
    except:
        return []

    # 2. 查公告
    plate = "sh" if code.startswith("6") else "sz"
    column = "sse" if code.startswith("6") else "szse"
    end = datetime.now().strftime("%Y-%m-%d")
    start = (datetime.now() - timedelta(days=365)).strftime("%Y-%m-%d")
    try:
        r2 = requests.post("http://www.cninfo.com.cn/new/hisAnnouncement/query",
                           headers=HEADERS,
                           data={"pageNum": 1, "pageSize": limit,
                                 "column": column, "tabName": "fulltext",
                                 "stock": f"{code},{org_id}",
                                 "searchkey": "", "secid": "",
                                 "category": "", "plate": plate,
                                 "seDate": f"{start}~{end}"},
                           timeout=10)
        anns = r2.json().get("announcements", []) or []
        return [{"title": a.get("announcementTitle", ""),
                 "date": datetime.fromtimestamp(
                     a.get("announcementTime", 0) / 1000
                 ).strftime("%Y-%m-%d") if a.get("announcementTime") else "",
                 "type": a.get("announcementTypeName", ""),
                 "url": f"http://static.cninfo.com.cn/{a.get('adjunctUrl', '')}"
                 } for a in anns[:limit]]
    except:
        return []


# ============================================================
# 8. 互动易 - 投资者问答
# ============================================================
def collect_ir(code, limit=15):
    """互动易投资者问答"""
    try:
        df = ak.stock_irm_cninfo(symbol=code)
        items = []
        for _, r in df.head(limit).iterrows():
            items.append({
                "question": str(r.get("提问内容", r.get("问题", "")))[:200],
                "answer": str(r.get("回答内容", r.get("回复", "")))[:300],
                "date": str(r.get("提问时间", r.get("日期", ""))),
            })
        return items
    except:
        return []


# ============================================================
# 9. 同花顺 - 个股页面(千股千评/财务指标)
# ============================================================
def collect_ths(code):
    """同花顺个股页面"""
    url = f"http://basic.10jqka.com.cn/{code}/"
    try:
        resp = _retry(lambda: requests.get(url, headers=HEADERS, timeout=10))
        soup = BeautifulSoup(resp.text, "html.parser")

        data = {"tables": [], "evaluation": ""}

        # 评价
        eval_el = soup.find("span", id="evaluation")
        if eval_el:
            data["evaluation"] = eval_el.get_text(strip=True)

        # 所有表格
        for table in soup.find_all("table"):
            rows = []
            for tr in table.find_all("tr"):
                cells = [td.get_text(strip=True) for td in tr.find_all(["td", "th"])]
                if cells:
                    rows.append(cells)
            if rows:
                data["tables"].append(rows)

        # 公司亮点
        highlight = soup.find("span", class_="company-highlight")
        if highlight:
            data["highlight"] = highlight.get_text(strip=True)

        return data
    except:
        return {"tables": [], "evaluation": ""}


# ============================================================
# 10. 雪球 - 个股页面(行情/关注度)
# ============================================================
def collect_xueqiu(code):
    """雪球个股行情"""
    prefix = "SH" if code.startswith("6") else "SZ"
    sym = f"{prefix}{code}"
    s = requests.Session()
    s.headers.update(HEADERS)
    try:
        s.get("https://xueqiu.com/", timeout=10)  # 获取 cookie
        url = f"https://stock.xueqiu.com/v5/stock/quote.json?symbol={sym}&extend=detail"
        r = s.get(url, timeout=10)
        d = r.json()
        quote = d.get("data", {}).get("quote", {})
        return {
            "price": quote.get("current", 0),
            "pe_ttm": quote.get("pe_ttm", 0),
            "pb": quote.get("pb", 0),
            "market_capital": quote.get("market_capital", 0),
            "float_market_capital": quote.get("float_market_capital", 0),
            "turnover_rate": quote.get("turnover_rate", 0),
            "volume": quote.get("volume", 0),
            "amount": quote.get("amount", 0),
            "name": quote.get("name", ""),
        }
    except:
        return {}


# ============================================================
# 11. 淘股吧 - 搜索(短线情绪帖)
# ============================================================
def collect_taoguba(code, name="", limit=15):
    """淘股吧搜索"""
    keyword = name if name else code
    url = f"https://www.taoguba.com.cn/search?keyword={keyword}"
    try:
        resp = _retry(lambda: requests.get(url, headers=HEADERS, timeout=10))
        soup = BeautifulSoup(resp.text, "html.parser")
        items = []
        # 找文章链接
        for a in soup.find_all("a", href=True):
            href = a["href"]
            if "/article/" in href:
                title = a.get_text(strip=True)
                if title and len(title) > 3:
                    items.append({"title": title[:100], "url": href})
                    if len(items) >= limit:
                        break
        return items
    except:
        return []


# ============================================================
# 12. 新浪资金流向
# ============================================================
def collect_sina_fund(code):
    """新浪资金流向"""
    prefix = "sh" if code.startswith("6") else "sz"
    sym = f"{prefix}{code}"
    url = f"http://vip.stock.finance.sina.com.cn/quotes_service/api/json_v2.php/MoneyFlow.ssl_bkzj_bk?page=1&num=10&sort=opendate&asc=0&fenlei=1&node={sym}"
    try:
        r = requests.get(url, headers=HEADERS, timeout=10)
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
    except:
        return []


# ============================================================
# 主采集函数
# ============================================================
def collect_all(code, name=""):
    """全平台采集"""
    t0 = time.time()
    result = {
        "code": code, "name": name,
        "collect_time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "platforms": {},
    }

    collectors = [
        ("kline",      lambda: collect_kline(code)),
        ("news",       lambda: collect_news(code)),
        ("reports",    lambda: collect_reports(code)),
        ("guba",       lambda: collect_guba(code)),
        ("financials", lambda: collect_financials(code)),
        ("lhb",        lambda: collect_lhb(code)),
        ("cninfo",     lambda: collect_cninfo(code)),
        ("ir",         lambda: collect_ir(code)),
        ("ths",        lambda: collect_ths(code)),
        ("xueqiu",     lambda: collect_xueqiu(code)),
        ("taoguba",    lambda: collect_taoguba(code, name)),
        ("sina_fund",  lambda: collect_sina_fund(code)),
    ]

    for plat_name, fn in collectors:
        try:
            t1 = time.time()
            data = fn()
            elapsed = time.time() - t1
            count = len(data) if isinstance(data, (list, dict)) else 1
            result["platforms"][plat_name] = {
                "status": "ok",
                "count": count,
                "time": f"{elapsed:.1f}s",
                "data": data,
            }
            print(f"  ✅ {plat_name}: {count} items, {elapsed:.1f}s")
        except Exception as e:
            result["platforms"][plat_name] = {"status": "fail", "error": str(e)[:200]}
            print(f"  ❌ {plat_name}: {e}")

    elapsed = time.time() - t0
    result["total_time"] = f"{elapsed:.1f}s"
    result["total_items"] = sum(
        p.get("count", 0) for p in result["platforms"].values() if p.get("status") == "ok"
    )

    # 保存
    out_path = DATA_DIR / f"{code}_raw.json"
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2, default=str)

    print(f"\n总计: {result['total_items']} 数据点, {elapsed:.1f}s")
    print(f"保存: {out_path}")
    return result


if __name__ == "__main__":
    code = sys.argv[1] if len(sys.argv) > 1 else "002371"
    name = sys.argv[2] if len(sys.argv) > 2 else ""
    print(f"全平台采集: {code} {name}")
    print("=" * 60)
    collect_all(code, name)
