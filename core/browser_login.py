# -*- coding: utf-8 -*-
"""
browser_login.py — 本地浏览器 + 人机协同登录 爬取器 v1.0
============================================================
针对受反爬/登录限制的数据源（雪球基本面 / 雪球讨论帖 / 知乎 / 淘股吧），
通过本地浏览器（优先复用系统已装 Chrome）完成登录态获取，再爬取内容。

设计要点:
  1. 「本地浏览器」: 优先使用系统安装的 Chrome (executable_path)，而非额外下载的 Chromium。
  2. 「AI 登录（人机协同）」:
       - 首次运行用【可见】浏览器导航到登录页；
       - 脚本自动轮询检测登录态（登录成功 cookie 出现 / 登录墙消失）；
       - 用户在弹出的浏览器窗口中完成扫码/账号登录，无需在终端输入密码；
       - 登录成功后把 cookie 缓存到 data/browser_cookies/{platform}_cookies.json。
  3. 「会话复用」: 每个平台使用独立的持久化 profile 目录
       (data/browser_profiles/{platform}/)，登录态跨多次运行保留；
       批量爬取 176 只股票时，每平台只需登录【一次】。
  4. 「cookie 复用调 API」: 雪球基本面/讨论帖登录后直接带 cookie 调官方 JSON
       接口（比 DOM 解析更稳）；知乎/淘股吧用已登录的浏览器渲染 DOM 提取。

用法（低层）:
  from browser_login import BrowserSession, ensure_login, scrape_xueqiu_fundamentals
  with BrowserSession("xueqiu", headless=False) as (ctx, page):
      ensure_login(page, "xueqiu", login_timeout=180)
      cookies = ctx.cookies()
      fund = scrape_xueqiu_fundamentals(cookies, "300308")

依赖: playwright (pip install playwright && playwright install chromium)
"""
import os
import sys
import json
import time
import urllib.parse
from pathlib import Path
from datetime import datetime

# ── 项目根目录自适应 ──
_PROJECT_ROOT = Path(__file__).resolve().parent
while _PROJECT_ROOT.name and not (_PROJECT_ROOT / "data").exists() and _PROJECT_ROOT.parent != _PROJECT_ROOT:
    _PROJECT_ROOT = _PROJECT_ROOT.parent

DATA_DIR = _PROJECT_ROOT / "data"
DATA_DIR.mkdir(exist_ok=True)

COOKIE_DIR = DATA_DIR / "browser_cookies"
COOKIE_DIR.mkdir(exist_ok=True)
PROFILE_DIR = DATA_DIR / "browser_profiles"
PROFILE_DIR.mkdir(exist_ok=True)

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
       "(KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36")

# ── Playwright 可用性 ──
_PLAYWRIGHT_AVAILABLE = False
try:
    from playwright.sync_api import sync_playwright, TimeoutError as PWTimeout
    _PLAYWRIGHT_AVAILABLE = True
except ImportError:
    pass


def is_available():
    """Playwright 是否可用（决定能否走浏览器登录爬取）"""
    return _PLAYWRIGHT_AVAILABLE


# ============================================================
# 平台配置
# ============================================================
# auth_cookies: 登录成功后出现的 cookie 名（任一出现即视为已登录）
# login_url:    需用户登录的页面
# home_url:     用于检测登录态的主页
# needs_login:   是否必须登录才能取到内容（True=无 cookie 时提示登录）
PLATFORMS = {
    "xueqiu": {
        "label": "雪球",
        "login_url": "https://xueqiu.com/login",
        "home_url": "https://xueqiu.com/",
        "auth_cookies": ["xq_a_token", "xq_is_login", "u"],
        "needs_login": True,
    },
    "zhihu": {
        "label": "知乎",
        "login_url": "https://www.zhihu.com/signin",
        "home_url": "https://www.zhihu.com/",
        "auth_cookies": ["z_c0"],
        "needs_login": True,
    },
    "taoguba": {
        "label": "淘股吧",
        "login_url": "https://www.taoguba.com.cn/login",
        "home_url": "https://www.taoguba.com.cn/",
        "auth_cookies": ["user", "TOKEN", "UB_"],
        "needs_login": False,   # 搜索通常无需登录；取不到再提示
    },
}


# ============================================================
# 工具函数
# ============================================================
def _chrome_path():
    """返回系统已装 Chrome 路径（优先复用本地浏览器）"""
    candidates = [
        r"C:\Program Files\Google\Chrome\Application\chrome.exe",
        r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
        os.path.expanduser(r"~\AppData\Local\Google\Chrome\Application\chrome.exe"),
        "/usr/bin/google-chrome",
        "/usr/bin/google-chrome-stable",
        "/usr/bin/chromium-browser",
        "/usr/bin/chromium",
    ]
    for p in candidates:
        if p and os.path.exists(p):
            return p
    return None  # 退回 Playwright 自带 Chromium


def _cookie_file(platform):
    return COOKIE_DIR / f"{platform}_cookies.json"


def load_cookies(platform):
    """读取缓存的 cookie（供非交互的逐股采集复用，无需再开浏览器）"""
    f = _cookie_file(platform)
    if f.exists():
        try:
            with open(f, "r", encoding="utf-8") as fh:
                return json.load(fh)
        except Exception:
            return None
    return None


def save_cookies(platform, cookies):
    """保存 cookie 到缓存"""
    try:
        with open(_cookie_file(platform), "w", encoding="utf-8") as fh:
            json.dump(cookies, fh, ensure_ascii=False, indent=2)
        return True
    except Exception:
        return False


def _cookie_header(cookies):
    """把 Playwright cookie 列表拼成 Cookie 请求头（最稳，全部带上）"""
    if not cookies:
        return ""
    return "; ".join(f"{c.get('name','')}={c.get('value','')}" for c in cookies)


def _is_logged_in(cookies, platform):
    """根据 auth_cookies 判断登录态"""
    if not cookies:
        return False
    names = {c.get("name") for c in cookies}
    auth = PLATFORMS[platform]["auth_cookies"]
    return any(a in names for a in auth)


# ============================================================
# 浏览器会话（持久化 profile，登录态跨运行保留）
# ============================================================
class BrowserSession:
    """
    上下文管理器：打开一个持久化浏览器会话。
      - 复用系统 Chrome（本地浏览器），profile 落在 data/browser_profiles/{platform}/
      - 启动时加载缓存 cookie；退出时保存 cookie
    用法:
      with BrowserSession("xueqiu", headless=False) as (ctx, page):
          ...
    """
    def __init__(self, platform, headless=True, extra_args=None):
        if not _PLAYWRIGHT_AVAILABLE:
            raise RuntimeError(
                "Playwright 未安装。请执行:\n"
                "  pip install playwright\n  playwright install chromium")
        self.platform = platform
        self.headless = headless
        self.profile = PROFILE_DIR / platform
        self.profile.mkdir(parents=True, exist_ok=True)
        self._pw = None
        self._browser = None
        self._extra_args = extra_args or []

    def __enter__(self):
        self._pw = sync_playwright().start()
        # 持久化 context：登录态（cookie + localStorage）跨运行保留
        opts = {
            "headless": self.headless,
            "user_data_dir": str(self.profile),
            "user_agent": UA,
            "viewport": {"width": 1366, "height": 900},
            "locale": "zh-CN",
            "accept_downloads": False,
            "args": [
                "--disable-blink-features=AutomationControlled",
                "--no-first-run",
                "--disable-infobars",
            ] + self._extra_args,
        }
        chrome = _chrome_path()
        if chrome:
            opts["executable_path"] = chrome
        self._browser = self._pw.chromium.launch_persistent_context(**opts)
        # 再叠加一份 JSON 缓存 cookie（保证 requests 接口也能复用）
        cached = load_cookies(self.platform)
        if cached:
            try:
                self._browser.add_cookies(cached)
            except Exception:
                pass
        self._ctx = self._browser
        self._page = self._browser.new_page()
        self._page.set_default_timeout(20000)
        return self._browser, self._page

    def __exit__(self, *exc):
        try:
            cookies = self._browser.cookies()
            save_cookies(self.platform, cookies)
        except Exception:
            pass
        try:
            self._browser.close()
        except Exception:
            pass
        try:
            self._pw.stop()
        except Exception:
            pass


def inject_cookies(context, cookies):
    """向已打开的 context 注入 cookie（复用缓存登录态，免二次登录）"""
    if cookies:
        try:
            context.add_cookies(cookies)
            return True
        except Exception:
            return False
    return False


# ============================================================
# 人机协同登录
# ============================================================
def ensure_login(page, platform, login_timeout=180, verbose=True, force=True):
    """
    确保已登录某平台（人机协同）。
      - 已缓存 cookie 且含 auth_cookie → 直接返回 True
      - force=True（如雪球/知乎）: 未登录则导航到登录页，打印指引，
        轮询等待用户在本机浏览器窗口完成登录（扫码 / 账号密码），最长 login_timeout 秒
      - force=False（如淘股吧，游客即可访问）: 未登录也直接返回 True，
        交由上层做游客式抓取，避免无谓等待
    返回: bool（是否处于登录态）
    """
    cfg = PLATFORMS[platform]
    label = cfg["label"]

    # 1) 先访问主页，刷新/确认 cookie 与登录态
    try:
        page.goto(cfg["home_url"], wait_until="domcontentloaded", timeout=20000)
        page.wait_for_timeout(1500)
    except Exception:
        pass

    cookies = page.context.cookies()
    if _is_logged_in(cookies, platform):
        if verbose:
            print(f"  [{label}] 已检测到登录态，跳过登录")
        return True

    # 不需要强制登录的平台（游客可访问）：直接放行，交给上层游客抓取
    if not force:
        if verbose:
            print(f"  [{label}] 未登录，按游客模式尝试抓取（如需登录请在其站点登录后重跑）")
        return True

    # 2) 未登录 → 去登录页，等待用户操作
    if verbose:
        print(f"\n{'='*56}")
        print(f"  ⏳ 请在【弹出的 {label} 浏览器窗口】中完成登录：")
        print(f"     · 支持扫码 / 手机号 / 账号密码")
        print(f"     · 登录成功后本脚本会自动继续，无需在终端输入")
        print(f"     · 超时 {login_timeout}s 后若仍未登录则跳过该源")
        print(f"{'='*56}")

    try:
        page.goto(cfg["login_url"], wait_until="domcontentloaded", timeout=20000)
    except Exception:
        # 有些站点登录页会 302，忽略导航异常
        pass

    deadline = time.time() + login_timeout
    logged = False
    while time.time() < deadline:
        try:
            cookies = page.context.cookies()
            if _is_logged_in(cookies, platform):
                logged = True
                break
        except Exception:
            pass
        time.sleep(3)

    if logged:
        try:
            save_cookies(platform, page.context.cookies())
        except Exception:
            pass
        if verbose:
            print(f"  [{label}] ✅ 登录成功，已缓存 cookie")
        return True

    if verbose:
        print(f"  [{label}] ⚠️ 登录超时/未成功，跳过该源（后续可重跑补采）")
    return False


# ============================================================
# 爬取器
# ============================================================
def _strip_html(html):
    if not html:
        return ""
    import re
    txt = re.sub(r"<br\s*/?>", "\n", html)
    txt = re.sub(r"<[^>]+>", "", txt)
    txt = re.sub(r"&nbsp;", " ", txt)
    txt = re.sub(r"&amp;", "&", txt)
    txt = re.sub(r"&lt;|&gt;", "", txt)
    return re.sub(r"\n{2,}", "\n", txt).strip()


def scrape_xueqiu_fundamentals(cookies, code):
    """
    雪球个股基本面（登录后带 cookie 调官方 quote 接口，最稳）。
    返回 dict: 市值/PE(TTM)/PB/PS/股息率/总股本等。
    """
    sym = f"SH{code}" if code.startswith("6") else f"SZ{code}"
    url = f"https://stock.xueqiu.com/v5/stock/quote.json?symbol={sym}&extend=detail"
    headers = {
        "User-Agent": UA,
        "Referer": f"https://xueqiu.com/S/{sym}",
        "Cookie": _cookie_header(cookies),
        "X-Requested-With": "XMLHttpRequest",
    }
    try:
        import requests
        r = requests.get(url, headers=headers, timeout=15)
        d = r.json()
        q = (d.get("data") or {}).get("quote") or {}
        if not q:
            return {}
        def num(x):
            try:
                return float(x)
            except Exception:
                return 0.0
        return {
            "symbol": sym,
            "name": q.get("name", ""),
            "current": num(q.get("current")),
            "pct_change": num(q.get("percent")),
            "pe_ttm": num(q.get("pe_ttm")),
            "pe_lyr": num(q.get("pe_lyr")),
            "pb": num(q.get("pb")),
            "ps": num(q.get("ps")),
            "market_capital": num(q.get("market_capital")),      # 总市值(元)
            "float_market_capital": num(q.get("float_market_capital")),
            "dividend_yield": num(q.get("dividend_yield")),
            "roe": num(q.get("roe")),
            "eps": num(q.get("eps")),
            "turnover_rate": num(q.get("turnover_rate")),
            "volume": num(q.get("volume")),
            "amount": num(q.get("amount")),
            "high52w": num(q.get("high52w")),
            "low52w": num(q.get("low52w")),
            "url": f"https://xueqiu.com/S/{sym}",
            "source": "雪球(登录爬取)",
        }
    except Exception as e:
        print(f"  [xueqiu] 基本面接口失败: {e}")
        return {}


def scrape_xueqiu_posts(cookies, code, max_count=30):
    """
    雪球个股讨论帖（登录后带 cookie 调 timeline 接口）。
    返回 list[dict]: {id,title,author,time,url,content,replies,source}
    """
    sym = f"SH{code}" if code.startswith("6") else f"SZ{code}"
    url = (f"https://xueqiu.com/v4/statuses/symbol_timeline.json"
           f"?symbol={sym}&count={max_count}&source=user&sort=time")
    headers = {
        "User-Agent": UA,
        "Referer": f"https://xueqiu.com/S/{sym}",
        "Cookie": _cookie_header(cookies),
        "X-Requested-With": "XMLHttpRequest",
    }
    posts = []
    try:
        import requests
        r = requests.get(url, headers=headers, timeout=15)
        d = r.json()
        statuses = d.get("statuses") or d.get("list") or []
        for i, st in enumerate(statuses[:max_count]):
            title = (st.get("title") or st.get("description") or st.get("text") or "")[:100]
            body = st.get("description") or st.get("text") or ""
            body = _strip_html(body)[:500]
            author = (st.get("user") or {}).get("screen_name", "")
            ts = st.get("created_at") or 0
            try:
                tstr = datetime.fromtimestamp(ts / 1000).strftime("%Y-%m-%d %H:%M")
            except Exception:
                tstr = ""
            target = st.get("target") or st.get("id") or ""
            if target and not str(target).startswith("http"):
                target = f"https://xueqiu.com{target}"
            posts.append({
                "id": f"XQ-{i+1:02d}",
                "title": title[:100],
                "author": author,
                "time": tstr,
                "url": target,
                "content": body,
                "replies": str(st.get("reply_count", st.get("comment_count", 0))),
                "retweets": str(st.get("retweet_count", 0)),
                "source": "雪球",
            })
    except Exception as e:
        print(f"  [xueqiu_posts] 接口失败: {e}")
    return posts


def scrape_zhihu(page, keyword, max_count=20):
    """
    知乎内容搜索（已登录浏览器渲染 DOM 提取）。
    返回 list[dict]: {id,title,author,url,excerpt,votes,answers,source}
    """
    encoded = urllib.parse.quote(keyword)
    url = f"https://www.zhihu.com/search?type=content&q={encoded}"
    try:
        page.goto(url, wait_until="domcontentloaded", timeout=20000)
    except Exception:
        pass
    page.wait_for_timeout(2500)
    # 滚动以触发懒加载
    for _ in range(3):
        try:
            page.evaluate("window.scrollBy(0, 700)")
        except Exception:
            pass
        page.wait_for_timeout(1200)

    results = []
    try:
        # 多选择器回退
        cards = page.query_selector_all(".SearchResult-Card, .ContentItem, .List-item, article")
        if not cards:
            cards = page.query_selector_all("[class*='SearchResult'], [class*='ContentItem']")
        for card in cards[:max_count]:
            try:
                title_el = card.query_selector("h2 a, .ContentItem-title a, [class*='title'] a")
                title = title_el.inner_text().strip() if title_el else ""
                href = title_el.get_attribute("href") if title_el else ""
                if href and not href.startswith("http"):
                    href = "https://www.zhihu.com" + href
                author_el = card.query_selector(".AuthorInfo-name, [class*='Author'] a, .meta .author")
                author = author_el.inner_text().strip() if author_el else ""
                excerpt_el = card.query_selector(".RichContent-inner, .ContentItem-summary, [class*='excerpt'], [class*='summary']")
                excerpt = excerpt_el.inner_text().strip()[:400] if excerpt_el else ""
                votes_el = card.query_selector(".VoteButton--up, [class*='vote'], .like-count")
                votes = votes_el.inner_text().strip() if votes_el else "0"
                answers_el = card.query_selector("[class*='answerCount'], [class*='answer']")
                answers = answers_el.inner_text().strip() if answers_el else ""
                if title:
                    results.append({
                        "id": f"ZH-{len(results)+1:02d}",
                        "title": title[:120],
                        "author": author,
                        "url": href,
                        "excerpt": excerpt,
                        "votes": votes,
                        "answers": answers,
                        "source": "知乎",
                    })
            except Exception:
                continue
    except Exception as e:
        print(f"  [zhihu] 提取失败: {e}")
    return results


def scrape_taoguba(page, keyword, max_count=15):
    """
    淘股吧搜索（已登录/游客浏览器渲染 DOM 提取）。
    返回 list[dict]: {id,title,url,author,source}
    """
    encoded = urllib.parse.quote(keyword)
    url = f"https://www.taoguba.com.cn/search?keyword={encoded}"
    try:
        page.goto(url, wait_until="domcontentloaded", timeout=20000)
    except Exception:
        pass
    page.wait_for_timeout(2500)
    for _ in range(2):
        try:
            page.evaluate("window.scrollBy(0, 600)")
        except Exception:
            pass
        page.wait_for_timeout(1000)

    items = []
    try:
        links = page.query_selector_all("a[href*='/article/']")
        for a in links:
            try:
                title = a.inner_text().strip()
                href = a.get_attribute("href") or ""
                if href and not href.startswith("http"):
                    href = "https://www.taoguba.com.cn" + href
                if title and len(title) > 3:
                    items.append({
                        "id": f"TG-{len(items)+1:02d}",
                        "title": title[:100],
                        "url": href,
                        "source": "淘股吧",
                    })
                    if len(items) >= max_count:
                        break
            except Exception:
                continue
    except Exception as e:
        print(f"  [taoguba] 提取失败: {e}")
    return items


# ============================================================
# 便捷封装（供逐股采集器 / 脚本调用）
# ============================================================
def fetch_xueqiu_bundle(cookies, code, max_posts=30):
    """
    一次拿齐「雪球基本面 + 雪球讨论帖」（共享同一登录 cookie）。
    返回 (fundamentals_dict, posts_list)
    """
    fund = scrape_xueqiu_fundamentals(cookies, code)
    posts = scrape_xueqiu_posts(cookies, code, max_count=max_posts)
    return fund, posts


# ============================================================
# 自检入口
# ============================================================
if __name__ == "__main__":
    if not is_available():
        print("Playwright 未安装。请执行:")
        print("  pip install playwright")
        print("  playwright install chromium")
        sys.exit(1)
    plat = sys.argv[1] if len(sys.argv) > 1 else "taoguba"
    kw = sys.argv[2] if len(sys.argv) > 2 else "中际旭创"
    print(f"=== 自检: {plat} / {kw} (无头, 不登录) ===")
    with BrowserSession(plat, headless=True) as (ctx, page):
        cookies = ctx.cookies()
        print(f"  登录态: {'是' if _is_logged_in(cookies, plat) else '否（无缓存cookie）'}")
        if plat == "zhihu":
            r = scrape_zhihu(page, kw, 10)
        elif plat == "taoguba":
            r = scrape_taoguba(page, kw, 10)
        else:
            r = []
        print(f"  取得 {len(r)} 条")
        for x in r[:5]:
            print("   -", x.get("title", "")[:60])
