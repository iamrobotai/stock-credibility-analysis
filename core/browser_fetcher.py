# -*- coding: utf-8 -*-
"""
browser_fetcher.py -- 本地浏览器数据抓取器 v1.0
====================================
通过 Playwright 驱动本地浏览器抓取需要登录或有反爬限制的数据源。

支持:
  - 雪球讨论帖 (需要 cookie / 登录态)
  - 知乎搜索结果 (反爬较严，需浏览器渲染)
  - 东财股吧 (验证码场景)
  - 通用页面抓取 (自定义 URL + 选择器)

使用模式:
  1. 直接调用: fetch_xueqiu_posts(code, max_count=30)
  2. 通用调用: fetch_page(url, selector, wait_for)
  3. 会话复用: with BrowserSession() as s: s.fetch(...)

依赖: playwright (pip install playwright && playwright install chromium)
"""
import os
import sys
import json
import time
from pathlib import Path
from datetime import datetime

# 项目根目录自适应
_PROJECT_ROOT = Path(__file__).resolve().parent
while _PROJECT_ROOT.name and not (_PROJECT_ROOT / "data").exists() and _PROJECT_ROOT.parent != _PROJECT_ROOT:
    _PROJECT_ROOT = _PROJECT_ROOT.parent

DATA_DIR = _PROJECT_ROOT / "data"
DATA_DIR.mkdir(exist_ok=True)

# 浏览器 cookie 缓存目录
COOKIE_DIR = DATA_DIR / "browser_cookies"
COOKIE_DIR.mkdir(exist_ok=True)

# Playwright 可用性标志
_PLAYWRIGHT_AVAILABLE = False
try:
    from playwright.sync_api import sync_playwright, TimeoutError as PWTimeout
    _PLAYWRIGHT_AVAILABLE = True
except ImportError:
    pass


def is_available():
    """检查 Playwright 是否可用"""
    return _PLAYWRIGHT_AVAILABLE


def _get_browser_path():
    """获取本地已安装的 Chromium 路径 (优先使用系统 Chrome)"""
    # 尝试系统 Chrome
    chrome_paths = [
        r"C:\Program Files\Google\Chrome\Application\chrome.exe",
        r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
        os.path.expanduser(r"~\AppData\Local\Google\Chrome\Application\chrome.exe"),
        "/usr/bin/google-chrome",
        "/usr/bin/chromium-browser",
        "/usr/bin/chromium",
    ]
    for p in chrome_paths:
        if os.path.exists(p):
            return p
    return None  # 使用 Playwright 自带 Chromium


def _load_cookies(domain):
    """加载缓存的 cookie"""
    cookie_file = COOKIE_DIR / f"{domain}_cookies.json"
    if cookie_file.exists():
        try:
            with open(cookie_file, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return None


def _save_cookies(domain, cookies):
    """保存 cookie 到缓存"""
    cookie_file = COOKIE_DIR / f"{domain}_cookies.json"
    try:
        with open(cookie_file, "w", encoding="utf-8") as f:
            json.dump(cookies, f, ensure_ascii=False, indent=2)
    except Exception:
        pass


# ============================================================
# 雪球讨论帖抓取
# ============================================================

def fetch_xueqiu_posts(code, max_count=30, headless=True):
    """
    通过浏览器抓取雪球个股讨论帖

    Args:
        code: 股票代码 (如 "002371")
        max_count: 最大帖子数
        headless: 是否无头模式

    Returns:
        list[dict]: 帖子列表 [{id, title, author, time, url, content, replies}]
    """
    if not _PLAYWRIGHT_AVAILABLE:
        raise RuntimeError("Playwright 未安装，请运行: pip install playwright && playwright install chromium")

    sym = f"SH{code}" if code.startswith("6") else f"SZ{code}"
    url = f"https://xueqiu.com/S/{sym}"
    posts = []

    with sync_playwright() as p:
        launch_opts = {"headless": headless}
        browser_path = _get_browser_path()
        if browser_path:
            launch_opts["executable_path"] = browser_path

        browser = p.chromium.launch(**launch_opts)
        context = browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0 Safari/537.36",
            viewport={"width": 1280, "height": 900},
            locale="zh-CN",
        )

        # 加载缓存的 cookie
        cached = _load_cookies("xueqiu")
        if cached:
            context.add_cookies(cached)

        page = context.new_page()
        page.set_default_timeout(20000)

        try:
            page.goto(url, wait_until="domcontentloaded")
            page.wait_for_timeout(2000)

            # 滚动加载更多
            for _ in range(3):
                page.evaluate("window.scrollBy(0, 800)")
                page.wait_for_timeout(1500)

            # 保存 cookie
            cookies = context.cookies()
            if cookies:
                _save_cookies("xueqiu", cookies)

            # 提取帖子
            items = page.query_selector_all(".timeline__item, .status-item, .timeline_item")
            if not items:
                # 尝试备用选择器
                items = page.query_selector_all("[class*='timeline'] article, [class*='status'] article")

            for item in items[:max_count]:
                try:
                    title_el = item.query_selector("h3 a, .title a, .status-title")
                    title = title_el.inner_text().strip() if title_el else ""
                    href = title_el.get_attribute("href") if title_el else ""
                    if href and not href.startswith("http"):
                        href = "https://xueqiu.com" + href

                    author_el = item.query_selector(".user-info .name, .author, [class*='author']")
                    author = author_el.inner_text().strip() if author_el else ""

                    time_el = item.query_selector(".time, .date, [class*='time']")
                    pub_time = time_el.inner_text().strip() if time_el else ""

                    content_el = item.query_selector(".content, .text, [class*='content']")
                    content = content_el.inner_text().strip()[:500] if content_el else ""

                    replies_el = item.query_selector(".reply-count, .comments, [class*='reply']")
                    replies = replies_el.inner_text().strip() if replies_el else "0"

                    if title or content:
                        posts.append({
                            "id": f"XQ-{len(posts)+1:02d}",
                            "title": title[:100],
                            "author": author,
                            "time": pub_time,
                            "url": href,
                            "content": content,
                            "replies": replies,
                            "source": "雪球",
                        })
                except Exception:
                    continue

        except PWTimeout:
            pass
        except Exception as e:
            print(f"  [browser_fetcher] 雪球抓取异常: {e}")
        finally:
            browser.close()

    return posts


# ============================================================
# 知乎搜索结果抓取
# ============================================================

def fetch_zhihu_search(keyword, max_count=20, headless=True):
    """
    通过浏览器抓取知乎搜索结果

    Args:
        keyword: 搜索关键词 (如股票名称)
        max_count: 最大结果数
        headless: 是否无头模式

    Returns:
        list[dict]: 结果列表 [{id, title, author, url, excerpt, votes, answers}]
    """
    if not _PLAYWRIGHT_AVAILABLE:
        raise RuntimeError("Playwright 未安装，请运行: pip install playwright && playwright install chromium")

    import urllib.parse
    encoded = urllib.parse.quote(keyword)
    url = f"https://www.zhihu.com/search?type=content&q={encoded}"
    results = []

    with sync_playwright() as p:
        launch_opts = {"headless": headless}
        browser_path = _get_browser_path()
        if browser_path:
            launch_opts["executable_path"] = browser_path

        browser = p.chromium.launch(**launch_opts)
        context = browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0 Safari/537.36",
            viewport={"width": 1280, "height": 900},
            locale="zh-CN",
        )

        cached = _load_cookies("zhihu")
        if cached:
            context.add_cookies(cached)

        page = context.new_page()
        page.set_default_timeout(20000)

        try:
            page.goto(url, wait_until="domcontentloaded")
            page.wait_for_timeout(3000)

            # 滚动加载
            for _ in range(2):
                page.evaluate("window.scrollBy(0, 600)")
                page.wait_for_timeout(1500)

            cookies = context.cookies()
            if cookies:
                _save_cookies("zhihu", cookies)

            # 提取搜索结果
            cards = page.query_selector_all(".SearchResult-Card, .Card, .List-item")
            if not cards:
                cards = page.query_selector_all("[class*='SearchResult'], [class*='ContentItem']")

            for card in cards[:max_count]:
                try:
                    title_el = card.query_selector("h2 a, .ContentItem-title a, [class*='title'] a")
                    title = title_el.inner_text().strip() if title_el else ""
                    href = title_el.get_attribute("href") if title_el else ""
                    if href and not href.startswith("http"):
                        href = "https://www.zhihu.com" + href

                    author_el = card.query_selector(".AuthorInfo-name, .meta .author, [class*='Author'] a")
                    author = author_el.inner_text().strip() if author_el else ""

                    excerpt_el = card.query_selector(".RichContent-inner, .abstract, [class*='excerpt'], [class*='content']")
                    excerpt = excerpt_el.inner_text().strip()[:400] if excerpt_el else ""

                    votes_el = card.query_selector(".VoteButton--up, .like-count, [class*='vote']")
                    votes = votes_el.inner_text().strip() if votes_el else "0"

                    answers_el = card.query_selector(".meta .answer, [class*='answer']")
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

        except PWTimeout:
            pass
        except Exception as e:
            print(f"  [browser_fetcher] 知乎抓取异常: {e}")
        finally:
            browser.close()

    return results


# ============================================================
# 东财股吧 (验证码场景浏览器抓取)
# ============================================================

def fetch_guba_browser(code, max_count=30, headless=True):
    """
    通过浏览器抓取东财股吧帖子 (应对验证码)

    Args:
        code: 股票代码
        max_count: 最大帖子数
        headless: 是否无头模式

    Returns:
        list[dict]: 帖子列表
    """
    if not _PLAYWRIGHT_AVAILABLE:
        raise RuntimeError("Playwright 未安装")

    url = f"https://guba.eastmoney.com/list,{code}.html"
    posts = []

    with sync_playwright() as p:
        launch_opts = {"headless": headless}
        browser_path = _get_browser_path()
        if browser_path:
            launch_opts["executable_path"] = browser_path

        browser = p.chromium.launch(**launch_opts)
        context = browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0 Safari/537.36",
            viewport={"width": 1280, "height": 900},
            locale="zh-CN",
        )
        page = context.new_page()
        page.set_default_timeout(15000)

        try:
            page.goto(url, wait_until="domcontentloaded")
            page.wait_for_timeout(2000)

            # 检查是否被验证码拦截
            content = page.content()
            if "captcha" in content.lower() or "验证" in content:
                # 非无头模式下可以手动处理验证码
                if not headless:
                    print("  [browser_fetcher] 检测到验证码，请在浏览器中手动完成验证...")
                    page.wait_for_timeout(10000)  # 等待用户手动处理
                else:
                    print("  [browser_fetcher] 检测到验证码，切换为非无头模式重试")
                    browser.close()
                    return fetch_guba_browser(code, max_count, headless=False)

            # 提取帖子
            rows = page.query_selector_all(".articleh, .l3")
            if not rows:
                rows = page.query_selector_all("[class*='article']")

            for row in rows[:max_count]:
                try:
                    a = row.query_selector("a")
                    if a:
                        title = a.inner_text().strip()
                        href = a.get_attribute("href") or ""
                        if href and not href.startswith("http"):
                            href = "https://guba.eastmoney.com" + href
                        if title and len(title) > 2:
                            posts.append({
                                "id": f"GB-{len(posts)+1:02d}",
                                "title": title[:100],
                                "url": href,
                                "source": "股吧(浏览器)",
                            })
                except Exception:
                    continue

        except Exception as e:
            print(f"  [browser_fetcher] 股吧抓取异常: {e}")
        finally:
            browser.close()

    return posts


# ============================================================
# 通用页面抓取
# ============================================================

def fetch_page(url, selector=None, wait_for=None, headless=True, timeout=20000):
    """
    通用浏览器页面抓取

    Args:
        url: 目标 URL
        selector: CSS 选择器，提取元素文本列表
        wait_for: 等待元素出现的 CSS 选择器
        headless: 无头模式
        timeout: 超时毫秒

    Returns:
        dict: {html: 页面HTML, texts: [选择器匹配文本列表], title: 页面标题}
    """
    if not _PLAYWRIGHT_AVAILABLE:
        raise RuntimeError("Playwright 未安装")

    with sync_playwright() as p:
        launch_opts = {"headless": headless}
        browser_path = _get_browser_path()
        if browser_path:
            launch_opts["executable_path"] = browser_path

        browser = p.chromium.launch(**launch_opts)
        context = browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0 Safari/537.36",
            viewport={"width": 1280, "height": 900},
        )
        page = context.new_page()
        page.set_default_timeout(timeout)

        result = {"html": "", "texts": [], "title": ""}
        try:
            page.goto(url, wait_until="domcontentloaded")
            if wait_for:
                page.wait_for_selector(wait_for, timeout=timeout)
            else:
                page.wait_for_timeout(2000)

            result["html"] = page.content()
            result["title"] = page.title()

            if selector:
                elements = page.query_selector_all(selector)
                result["texts"] = [el.inner_text().strip() for el in elements if el.inner_text().strip()]
        except Exception as e:
            result["error"] = str(e)
        finally:
            browser.close()

    return result


# ============================================================
# 浏览器会话类 (复用浏览器实例)
# ============================================================

class BrowserSession:
    """浏览器会话上下文管理器，支持复用浏览器实例"""

    def __init__(self, headless=True):
        self.headless = headless
        self._pw = None
        self._browser = None

    def __enter__(self):
        if not _PLAYWRIGHT_AVAILABLE:
            raise RuntimeError("Playwright 未安装")
        self._pw = sync_playwright().start()
        launch_opts = {"headless": self.headless}
        browser_path = _get_browser_path()
        if browser_path:
            launch_opts["executable_path"] = browser_path
        self._browser = self._pw.chromium.launch(**launch_opts)
        return self

    def __exit__(self, *args):
        if self._browser:
            self._browser.close()
        if self._pw:
            self._pw.stop()

    def fetch(self, url, selector=None, wait_for=None, timeout=20000):
        """在当前浏览器会话中抓取页面"""
        context = self._browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0 Safari/537.36",
            viewport={"width": 1280, "height": 900},
        )
        page = context.new_page()
        page.set_default_timeout(timeout)
        result = {"html": "", "texts": [], "title": ""}
        try:
            page.goto(url, wait_until="domcontentloaded")
            if wait_for:
                page.wait_for_selector(wait_for, timeout=timeout)
            else:
                page.wait_for_timeout(2000)
            result["html"] = page.content()
            result["title"] = page.title()
            if selector:
                elements = page.query_selector_all(selector)
                result["texts"] = [el.inner_text().strip() for el in elements if el.inner_text().strip()]
        except Exception as e:
            result["error"] = str(e)
        finally:
            context.close()
        return result


# ============================================================
# 测试入口
# ============================================================

if __name__ == "__main__":
    if not is_available():
        print("Playwright 未安装。请执行:")
        print("  pip install playwright")
        print("  playwright install chromium")
        sys.exit(1)

    code = sys.argv[1] if len(sys.argv) > 1 else "002371"
    name = sys.argv[2] if len(sys.argv) > 2 else ""

    print(f"=== 雪球讨论帖 ({code}) ===")
    posts = fetch_xueqiu_posts(code, max_count=10)
    for p in posts:
        print(f"  [{p['id']}] {p['title']} | {p['author']} | {p['time']}")
    print(f"  共 {len(posts)} 条")

    if name:
        print(f"\n=== 知乎搜索 ({name}) ===")
        results = fetch_zhihu_search(name, max_count=10)
        for r in results:
            print(f"  [{r['id']}] {r['title']} | {r['author']} | 赞:{r['votes']}")
        print(f"  共 {len(results)} 条")
