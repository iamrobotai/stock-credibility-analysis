#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
合并 index.html (可信度分析) 与 quant.html (量化分析) 为单一网页 dashboard.html。
- 以 index.html 为基底（head/style/header/控制面板/预览模态）
- 可信度内容包进 #panel-cred，quant.html 结果区+控件注入 #panel-quant
- 两分析「合并为统一综合分析视图」同屏展示（无 Tab 切换，见 merge-note）
- JS：index 脚本全留；quant 脚本做冲突改名后追加
冲突处理：
  * toggleTheme/applyThemeLabel：两文件同逻辑，保留 index 版，删 quant 重复副本
  * quant init() -> initQuant()；quant log() -> qlog()（占位符保护 $('#log') 选择器）
  * 统一引导：index init() 末尾追加 initQuant()
  * quant 的 #stock 为空时回退到主页 #stock_code（两分析共用代码）
用法：python scripts/build_dashboard.py
"""
import io, re, sys, os

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
IDX = os.path.join(BASE, "templates", "index.html")
QNT = os.path.join(BASE, "templates", "quant.html")
OUT = os.path.join(BASE, "templates", "dashboard.html")

# 安全护栏：dashboard.html 现在由人工直接维护（合并视图 / 浅色模式 /
# 在线预览 等改动均在 dashboard.html 上完成）。本脚本仅作为「从 index+quant
# 重新生成」的参考手段——默认拒绝覆盖已有文件，避免误执行导致手工改动丢失。
if os.path.exists(OUT) and "--force" not in sys.argv:
    sys.stderr.write(
        "⚠️  已存在 hand-maintained 的 dashboard.html，默认不覆盖。\n"
        "    若确需从 index.html + quant.html 重新生成，请显式加 --force：\n"
        "    python scripts/build_dashboard.py --force\n"
    )
    sys.exit(0)

def must(s, marker):
    if marker not in s:
        raise SystemExit("❌ 找不到锚点: %r" % marker)
    return s

idx = open(IDX, encoding="utf-8").read()
qnt = open(QNT, encoding="utf-8").read()

# ---------- 1) index 拆分 ----------
idx = must(idx, "</head>")
head_and_style = idx[: idx.index("</head>") + len("</head>")]      # 1..</head>
body = idx[idx.index("</head>") + len("</head>"):]                    # <body>..end
must(body, '<div class="container">')
idx_header = body[: body.index('<div class="container">')]               # <body>+header
idx_body_html = body[: body.index("<script>")]                         # 174..388 (HTML，无脚本)
idx_rest = idx_body_html[idx_body_html.index('<div class="container">'):]  # 184..388
# 主脚本 inner JS（389..1803 之间）
s = body[body.index("<script>"):]
idx_script_inner = s[s.index(">") + 1 : s.rindex("</script>")]

# ---------- 2) quant 拆分 ----------
q_body_part = qnt[qnt.index("</head>") + 7:]                          # <body>..end
must(q_body_part, '<div class="container">')
must(q_body_part, "<script>")
q_body = q_body_part[
    q_body_part.index('<div class="container">'):
    q_body_part.index("<script>")
]                                                                      # 70..189 完整容器（结果区+控件+#log+闭合</div>）
must(q_body_part, "const $=")
q_start = q_body_part.index("const $=")
q_script_inner = q_body_part[q_start : q_body_part.rindex("</script>")]     # 190..443 JS

# ---------- 3) 变换 quant 脚本 ----------
# 3a) init -> initQuant
assert "async function init(){" in q_script_inner, "quant init 锚点缺失"
q_script_inner = q_script_inner.replace("async function init(){", "async function initQuant(){")
# 3b) 保护 $('#log') 选择器，再批量 log( -> qlog(
q_script_inner = q_script_inner.replace("$('#log')", "__LOGSEL__")
q_script_inner = q_script_inner.replace("log(", "qlog(")
q_script_inner = q_script_inner.replace("__LOGSEL__", "$('#log')")
assert "function qlog(" in q_script_inner, "qlog 重命名失败"
# 3c) 删除 quant 重复的 主题切换 函数（保留 index 版）
q_script_inner = re.sub(r"/\* -+ 主题切换[^\n]*\n", "", q_script_inner)        # 注释行
q_script_inner = re.sub(r"function applyThemeLabel\(\)\s*\{[\s\S]*?\n\}\n", "", q_script_inner)
q_script_inner = re.sub(r"function toggleTheme\(\)\s*\{[\s\S]*?\n\}\n", "", q_script_inner)
assert "function toggleTheme()" not in q_script_inner, "quant toggleTheme 未删干净"
assert "function applyThemeLabel()" not in q_script_inner, "quant applyThemeLabel 未删干净"
# 3d) 删除 quant 末尾独立的 init(); 调用（由统一引导接管）
q_script_inner = q_script_inner.replace("\ninit();\n", "\n")
# 3e) 量化运行优先用主页已输入股票代码（两分析放在一起）
q_script_inner = q_script_inner.replace(
    "const code=$('#stock').value;if(!code)return;",
    "const code=($('#stock').value||'').trim()||($('#stock_code').value||'').trim();if(!code)return;"
)

# ---------- 4) 统一合并视图引导（替代原 Tab 切换） ----------
# 可信度分析(D1–D9) 与量化分析(回测·资金·多周期融合) 同屏展示
merge_note = (
    '<div class="merge-note">🧭 已合并为「统一综合分析视图」：可信度分析（D1–D9）与量化分析'
    '（回测 · 资金 · 多周期融合）同屏展示，向下滚动查看全部维度。</div>\n'
)
assert "</style>" in head_and_style
# 更新标题与版本标识
head_and_style = head_and_style.replace(
    "股票可信度分析系统 v2.6", "股票可信度分析系统 · 合并版 v3.4"
)

# ---------- 5) 统一引导（已取消 Tab 切换，仅保留量化初始化） ----------
bootstrap = (
    "\ninitQuant();\n"
)

# ---------- 6) 组装 ----------
out = []
out.append(head_and_style)          # </head>
out.append(idx_header)               # <body> + header(含主题切换)
# 统一合并视图引导：可信度分析 + 量化分析同屏展示（无 Tab 切换）
out.append(merge_note)
out.append('<div id="panel-cred">\n')
out.append(idx_rest)
out.append('</div>\n')
out.append('<div id="panel-quant">\n')
out.append(q_body)
out.append('</div>\n')
out.append('<script>\n')
out.append(idx_script_inner)
out.append(bootstrap)
out.append(q_script_inner)
out.append('\n</script>\n')
out.append('</body>\n</html>\n')

open(OUT, "w", encoding="utf-8").write("".join(out))
print("✅ 已生成", OUT)
print("   字节数:", len("".join(out)))
print("   init() 调用:", idx_script_inner.count("init();") and "保留(index)" or "缺失?")
print("   initQuant() 定义:", "async function initQuant(){" in q_script_inner)
print("   qlog() 定义:", "function qlog(" in q_script_inner)
print("   toggleTheme 仅一份:", idx_script_inner.count("function toggleTheme()") == 1)
print("   统一合并视图(无 Tab):", "merge-note" in "".join(out))
