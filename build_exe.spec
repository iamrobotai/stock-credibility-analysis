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

# ---- 本地子包全量收集 ----
hiddenimports = (
    collect_submodules("core")
    + collect_submodules("quant")
    + collect_submodules("ai")
    + collect_submodules("export")
    + collect_submodules("services")
    + collect_submodules("common")
    + collect_submodules("annotation")
)

# ---- 第三方关键依赖（防止 hook 漏判） ----
hiddenimports += [
    "flask", "jinja2", "werkzeug", "markupsafe", "itsdangerous",
    "click", "blinker", "pandas", "numpy",
    "akshare", "requests", "lxml", "openpyxl", "bs4", "html5lib",
]

# akshare 可能用到的数据/模板文件
try:
    hiddenimports += collect_submodules("akshare")
except Exception:
    pass

a = Analysis(
    ["launcher.py"],
    pathex=[project_dir],
    binaries=[],
    datas=[
        (os.path.join(project_dir, "templates"), "templates"),
        (os.path.join(project_dir, "static"), "static"),
        (os.path.join(project_dir, "configs"), "configs"),
    ],
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
