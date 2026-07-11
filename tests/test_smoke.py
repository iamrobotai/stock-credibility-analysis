# -*- coding: utf-8 -*-
"""
统一综合分析视图 · 自动化冒烟测试
覆盖本次交付的核心能力：
  1) 首页正常加载、统一合并视图（无 Tab）
  2) 浅色/深色主题切换
  3) Word 文档浏览器内联免下载预览
"""
import pytest


def test_home_loads_and_merge_view(page):
    """首页 200，且已合并为统一视图（无 top-tabs，双 panel 同屏可见）。"""
    # merge-note 是合并视图的标记（注意其为 class 而非 id）
    assert page.locator(".merge-note").count() == 1
    # 旧的 Tab 切换应已被移除
    assert page.locator(".top-tabs").count() == 0
    # 可信度与量化两个面板均可见（不带 display:none）
    assert page.locator("#panel-cred").is_visible()
    assert page.locator("#panel-quant").is_visible()


def test_theme_toggle(page):
    """点击主题切换按钮，document 的 data-theme 应在 light/dark 间翻转。"""
    before = page.evaluate("() => document.documentElement.getAttribute('data-theme') || 'dark'")
    assert before in ("light", "dark")
    page.click("#theme-toggle")
    after = page.evaluate("() => document.documentElement.getAttribute('data-theme')")
    assert after != before
    assert after in ("light", "dark")


def test_word_inline_preview(page):
    """在预览模态框内点击「📄 预览Word」，应在不下载的情况下内联渲染 Word 内容。"""
    # 1) 取一个确实存在 Word 文档的股票
    data = page.evaluate("() => fetch('/api/stocks').then(r => r.json())")
    files = data.get("files", [])
    target = next((f for f in files if f.get("docx")), None)
    assert target, "output 中未找到可用的 Word 文档"

    code = target["code"]
    name = target["docx"]

    # 2) 直接打开预览模态框（避免触发重型 /api/preview 分析），
    #    并设置 previewCode / previewName，使「预览Word」按钮可定位文档
    page.evaluate(
        "([c, n]) => { previewCode = c; previewName = n; "
        "document.getElementById('preview-modal').classList.add('show'); }",
        [code, name],
    )
    page.wait_for_selector("#preview-modal.show", timeout=5000)

    # 3) 点击「📄 预览Word」，等待内联 HTML 渲染完成
    page.click("#preview-docx-view-btn")
    page.wait_for_selector("#docx-preview .docx-wrap", timeout=15000)

    # 4) 断言：内联预览可见且包含由 docx 转换出的真实内容
    assert page.locator("#docx-preview .docx-wrap").is_visible()
    # 转换后的 HTML 至少包含标题/段落/表格之一
    has_content = (
        page.locator("#docx-preview h1, #docx-preview h2, #docx-preview p, #docx-preview table").count()
        > 0
    )
    assert has_content, "Word 内联预览未渲染出任何内容"
