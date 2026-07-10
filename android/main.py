#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Android 入口（Kivy + WebView 壳）。

方案：在后台线程启动本地 Flask 服务，前端用 Kivy-Garden WebView
加载 http://127.0.0.1:5000/ ，从而把现有 Web 应用完整搬进 APK。

注意：
- 本项目根目录（含 app.py / core / quant / templates / static）需随包打入；
  buildozer.spec 已通过 source.dir = .. 与 include_patterns 处理。
- 本文件仅作「壳」，业务逻辑全部复用现有 Flask 应用，零重复。
"""

import os
import sys
import threading
import time

# 将项目根目录加入 path，使 `import app` 可用
_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.abspath(os.path.join(_HERE, ".."))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)


def _start_flask():
    try:
        from app import app
        app.run(
            host="127.0.0.1",
            port=5000,
            debug=False,
            threaded=True,
            use_reloader=False,
        )
    except Exception as e:  # pragma: no cover
        sys.stderr.write("Flask start failed: %s\n" % e)


def build_app():
    from kivy.app import App
    from kivy.uix.widget import Widget
    try:
        from kivy_garden.webview import WebView
    except Exception as e:
        class _Err(Widget):
            pass
        WebView = _Err

    class StockApp(App):
        def build(self):
            threading.Thread(target=_start_flask, daemon=True).start()
            time.sleep(2.0)  # 等待 Flask 就绪
            return WebView(url="http://127.0.0.1:5000/")

    return StockApp()


if __name__ == "__main__":
    build_app().run()
