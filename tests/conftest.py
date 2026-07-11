# -*- coding: utf-8 -*-
"""
pytest 共享 fixture：
  - base_url : 在随机端口启动 Flask 应用线程，返回可访问地址
  - browser  : 覆盖 pytest-playwright 的 browser fixture，使用本机已有的
               Chrome 二进制（沙箱内 Playwright 官方浏览器下载被屏蔽，
               故改用 executable_path 指向已安装的 Chrome for Testing）
  - page     : 每个测试一个独立 context + 已打开首页的 page

说明：本文件刻意「覆盖」pytest-playwright 自带的 browser/context/page fixture，
目的是规避 ms-playwright 浏览器缺失的问题，同时保持测试写法与官方一致。
"""
import os
import sys
import socket
import threading
import pathlib
import time
import urllib.request

import pytest

# ---- 将项目根目录加入 sys.path，确保 `import app` 与子模块可用 ----
ROOT = pathlib.Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# ---- 定位本机已有的 Chrome / Chromium 二进制 ----
HOME = pathlib.Path.home()
CHROME_CANDIDATES = [
    HOME / ".agent-browser" / "browsers" / "chrome-150.0.7871.49" / "chrome.exe",
    HOME / ".chromium-browser-snapshots" / "chromium" / "win64-1607698" / "chrome-win" / "chrome.exe",
]


def _find_chrome():
    for c in CHROME_CANDIDATES:
        if c.exists():
            return str(c)
    return None


CHROME = _find_chrome()


def _free_port():
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


def _wait_for_server(url, timeout=20):
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            urllib.request.urlopen(url + "/", timeout=1)
            return True
        except Exception:
            time.sleep(0.2)
    return False


@pytest.fixture(scope="session")
def base_url():
    from app import app  # 延迟导入，避免收集阶段触发重副作用

    port = _free_port()
    # 关键：threaded=True，否则 Werkzeug 开发服务器为单线程，
    # render_template 与浏览器并发请求会互相阻塞导致首页响应超时。
    srv = threading.Thread(
        target=lambda: app.run(
            host="127.0.0.1", port=port, debug=False,
            use_reloader=False, threaded=True,
        ),
        daemon=True,
    )
    srv.start()
    url = f"http://127.0.0.1:{port}"
    assert _wait_for_server(url), "Flask 测试服务器未能在预期时间内启动"
    yield url


@pytest.fixture(scope="session")
def browser():
    from playwright.sync_api import sync_playwright

    with sync_playwright() as p:
        if CHROME:
            b = p.chromium.launch(
                headless=True,
                executable_path=CHROME,
                args=["--no-sandbox", "--disable-dev-shm-usage"],
            )
        else:
            # 回退：若本机存在 ms-playwright 缓存则使用官方浏览器
            b = p.chromium.launch(headless=True, args=["--no-sandbox"])
        yield b
        try:
            b.close()
        except Exception:
            pass


@pytest.fixture
def page(browser, base_url):
    ctx = browser.new_context()
    # 放宽导航超时：本机冷启动首次渲染可能较慢
    ctx.set_default_timeout(30000)
    pg = ctx.new_page()
    pg.goto(base_url + "/", wait_until="domcontentloaded", timeout=30000)
    pg.wait_for_selector(".merge-note", timeout=30000)
    yield pg
    ctx.close()
