# -*- mode: python ; coding: utf-8 -*-
"""
PyInstaller 打包规格（Windows 单文件 exe）。

构建命令（在项目根目录执行）：
    python -m PyInstaller build_exe.spec

产出：dist/StockCredibility.exe （单文件，含全部依赖与资源）。

设计要点：
- 入口为 launcher.py（启动本地 Flask 服务并自动开浏览器）；
- 资源 templates/static/configs 以 datas 形式打入，运行时由
  app.py 的 sys.frozen 分支定位到解压目录；
- 本地子包 core/quant/ai/export/services/common/annotation 用
  collect_submodules 全量收集，避免动态 import 漏打包；
- akshare 一并打包，保证「数据采集」功能在离线安装后依然可用。
"""

import os

from PyInstaller.utils.hooks import collect_submodules, collect_data_files

# ---- 路径 ----
# PyInstaller 6.x 的 spec 执行命名空间不注入 __file__ / SPECFILE，
# 故按优先级回退：SPECFILE → __file__ → 当前工作目录（文档要求从项目根构建）。
try:
    SPEC_DIR = os.path.dirname(os.path.abspath(SPECFILE))
except NameError:
    try:
        SPEC_DIR = os.path.dirname(os.path.abspath(__file__))
    except NameError:
        SPEC_DIR = os.getcwd()
project_dir = SPEC_DIR

block_cipher = None

# ---- 本地子包收集 ----
# 重要（修复 exe 内「No module named 'hot_stocks'」等裸导入失败）：
#   core/ai/export/scripts 这 4 个目录【没有 __init__.py】，源码里是当作
#   「扁平模块目录」靠 sys.path 注入使用的（裸导入 `from hot_stocks import`）。
#   collect_submodules 会把它们收成 `core.hot_stocks` 这种带前缀名塞进 PYZ，
#   而代码要的是裸名 `hot_stocks` —— 故 frozen 下裸导入全部失败。
#   修复：这 4 个目录改为 datas 实体解压（见下方 datas），运行时 sys.path
#   注入会自动把它们加进来，行为与源码完全一致（裸导入 + 命名空间包前缀导入都解析得到）。
#   quant/services/common/annotation 有 __init__.py，继续用 collect_submodules。
hiddenimports = (
    collect_submodules("quant")
    + collect_submodules("services")
    + collect_submodules("common")
    + collect_submodules("annotation")
)

# ---- 第三方关键依赖（防止 hook 漏判） ----
hiddenimports += [
    "flask", "jinja2", "werkzeug", "markupsafe", "itsdangerous",
    "click", "blinker", "pandas", "numpy",
    "requests", "lxml", "openpyxl", "bs4", "html5lib",
    # 注：akshare 不走 collect_submodules（会被塞进 PYZ 致 __file__ 虚拟，
    # 其 file_fold/calendar.json 等数据文件按 __file__ 定位会失败），
    # 改由下方 collect_all 以「真实文件」形式抽取（见 a = Analysis 之前）。
]

# ---- akshare 必须以「真实文件」打入 exe（非 PYZ 压缩） ----
# 原因：akshare.futures.cons.get_calendar() 在运行时按 __file__ 定位
#   os.path.dirname(os.path.dirname(__file__))/file_fold/calendar.json
# 若 akshare 被 PyInstaller 收进 PYZ，其 __file__ 为虚拟路径，
# 找不到数据文件 → FileNotFoundError → 分析任务 `import akshare` 即崩溃。
# collect_all 同时返回 (binaries, datas, hiddenimports)，使 akshare 的
# 模块与数据文件落在同一真实目录，__file__ 解析正确。
try:
    from PyInstaller.utils.hooks import collect_all
    ak_bin, ak_datas, ak_hidden = collect_all("akshare")
    akshare_binaries = list(ak_bin)
    akshare_datas = list(ak_datas)
    hiddenimports += list(ak_hidden)
except Exception:
    akshare_binaries, akshare_datas = [], []

# docx（Word 报告生成）同样以「真实文件」抽取：其内置 default.docx
# 模板按包内相对路径读取，若被塞进 PYZ 数据文件定位会失败。
try:
    docx_bin, docx_datas, docx_hidden = collect_all("docx")
    akshare_binaries += list(docx_bin)
    akshare_datas += list(docx_datas)
    hiddenimports += list(docx_hidden)
except Exception:
    pass

extra_datas = list(akshare_datas)

a = Analysis(
    ["launcher.py"],
    pathex=[project_dir],
    binaries=akshare_binaries,
    datas=[
        (os.path.join(project_dir, "templates"), "templates"),
        (os.path.join(project_dir, "static"), "static"),
        (os.path.join(project_dir, "configs"), "configs"),
        # 4 个「扁平模块目录」（无 __init__.py）：以实体文件解压，
        # 使 frozen 模式 sys.path 注入生效，裸导入 `from hot_stocks import` 等可解析。
        (os.path.join(project_dir, "core"), "core"),
        (os.path.join(project_dir, "ai"), "ai"),
        (os.path.join(project_dir, "export"), "export"),
        (os.path.join(project_dir, "scripts"), "scripts"),
    ] + extra_datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        "matplotlib", "scipy", "PyQt5", "PyQt6", "PySide2", "PySide6",
        "tkinter", "unittest", "test", "tests", "pandas.tests", "numpy.tests",
    ],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    [],
    name="StockCredibility",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    runtime_tmpdir=None,
    console=True,  # 保留控制台以显示服务日志，便于排查（可改 False 隐藏）
    # icon=os.path.join(project_dir, "deploy", "icon.ico"),  # 若提供图标取消注释
)
