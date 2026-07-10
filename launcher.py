#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
桌面启动器（Windows exe 入口）。

- 在后台线程启动 Flask 本地服务（仅监听 127.0.0.1，避免暴露到局域网）；
- 启动后自动打开默认浏览器访问本地页面；
- 支持命令行参数：
    --port 5000      指定端口
    --no-browser     不自动打开浏览器（如服务器/远程场景）
    --host 127.0.0.1  指定监听地址
- 控制台关闭（Ctrl+C）即停止服务。
"""

import argparse
import os
import sys
import threading
import time
import webbrowser


def _open_browser(url: str, delay: float = 1.5):
    """延迟打开浏览器，等待 Flask 真正起来。"""
    time.sleep(delay)
    try:
        webbrowser.open(url)
    except Exception:
        pass


def main():
    parser = argparse.ArgumentParser(description="股票可信度分析系统 - 桌面启动器")
    parser.add_argument("--host", default="127.0.0.1", help="监听地址（默认 127.0.0.1）")
    parser.add_argument("--port", type=int, default=5000, help="监听端口（默认 5000）")
    parser.add_argument("--no-browser", action="store_true", help="不自动打开浏览器")
    args = parser.parse_args()

    # 让 app 模块在 import 时处于正确工作目录
    here = os.path.dirname(os.path.abspath(__file__))
    if here and os.getcwd() != here:
        try:
            os.chdir(here)
        except Exception:
            pass

    from app import app  # Flask 实例（全局 bootstrap 在 import 时已执行）

    url = f"http://{args.host}:{args.port}/"
    if not args.no_browser:
        threading.Thread(target=_open_browser, args=(url,), daemon=True).start()

    print("=" * 56)
    print("  股票可信度分析系统 (本地桌面版)")
    print("  访问地址:", url)
    print("  关闭本窗口 / Ctrl+C 即停止服务")
    print("=" * 56)

    try:
        app.run(host=args.host, port=args.port, debug=False, threaded=True, use_reloader=False)
    except KeyboardInterrupt:
        print("\n服务已停止。")


if __name__ == "__main__":
    main()
