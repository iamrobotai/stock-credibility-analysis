#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
合并 index.html (可信度分析) 与 quant.html (量化分析) 为单一网页 dashboard.html。
- 以 index.html 为基底（head/style/header/控制面板/预览模态）
- 在 header 下注入顶层标签页 [可信度分析] [量化分析]
- 可信度内容包进 #panel-cred，quant.html 结果区+控件注入 #panel-quant（默认隐藏）
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

# ---------- 4) 顶层标签页 + CSS ----------
top_tabs = (
    '<div class="top-tabs">\n'
    '  <button class="top-tab active" id="tab-cred" onclick="showPanel(\'cred\')">📊 可信度分析</button>\n'
    '  <button class="top-tab" id="tab-quant" onclick="showPanel(\'quant\')">📈 量化分析（回测 · 资金 · 融合）</button>\n'
    '</div>\n'
)
top_tab_css = (
    "\n.top-tabs{display:flex;gap:8px;padding:12px 24px;background:var(--bg-card,#161b22);"
    "border-bottom:1px solid var(--border,#30363d);flex-wrap:wrap;}\n"
    ".top-tab{padding:8px 18px;font-size:14px;border-radius:8px;cursor:pointer;"
    "border:1px solid var(--border,#30363d);background:var(--bg,#0d1117);color:var(--text,#c9d1d9);"
    "transition:var(--t,.22s);}\n"
    ".top-tab:hover{border-color:var(--accent,#58a6ff);}\n"
    ".top-tab.active{background:linear-gradient(135deg,#238636,#2ea043);border-color:#238636;color:#fff;"
    "box-shadow:0 4px 14px rgba(35,134,54,.35);}\n"
)
assert "</style>" in head_and_style
head_and_style = head_and_style.replace("</style>", top_tab_css + "</style>", 1)
# 更新标题与版本标识
head_and_style = head_and_style.replace(
    "股票可信度分析系统 v2.6", "股票可信度分析系统 · 合并版 v3.4"
)

# ---------- 5) 统一引导 + showPanel ----------
bootstrap = (
    "\nfunction showPanel(n){\n"
    "  var pc=document.getElementById('panel-cred'),pq=document.getElementById('panel-quant');\n"
    "  var tc=document.getElementById('tab-cred'),tq=document.getElementById('tab-quant');\n"
    "  if(pc)pc.style.display=(n==='cred')?'block':'none';\n"
    "  if(pq)pq.style.display=(n==='quant')?'block':'none';\n"
    "  if(tc)tc.classList.toggle('active',n==='cred');\n"
    "  if(tq)tq.classList.toggle('active',n==='quant');\n"
    "}\n"
    "initQuant();\n"
)

# ---------- 6) 组装 ----------
out = []
out.append(head_and_style)          # </head>
out.append(idx_header)               # <body> + header(含主题切换)
out.append(top_tabs)
out.append('<div id="panel-cred">\n')
out.append(idx_rest)
out.append('</div>\n')
out.append('<div id="panel-quant" style="display:none">\n')
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
print("   showPanel 已注入:", "function showPanel(" in "".join(bootstrap))
