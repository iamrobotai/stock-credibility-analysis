# -*- coding: utf-8 -*-
"""
config.py — 全局配置与路径集中管理
=====================================
所有模块统一从此处获取根目录、数据目录、输出目录与版本号，
避免在业务代码中散落 os.getcwd() / 相对路径推断，降低耦合。
"""
from pathlib import Path

# ---- 目录结构 (common 位于 <ROOT>/common) ----
BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data"
OUTPUT_DIR = BASE_DIR / "output"
CONFIGS_DIR = BASE_DIR / "configs"
TEMPLATES_DIR = BASE_DIR / "templates"
COMMON_DIR = BASE_DIR / "common"
SERVICES_DIR = BASE_DIR / "services"
ANNOTATION_DIR = BASE_DIR / "annotation"

# 确保核心目录存在
for _d in (DATA_DIR, OUTPUT_DIR, CONFIGS_DIR):
    try:
        _d.mkdir(parents=True, exist_ok=True)
    except Exception:
        pass

# ---- 版本管理 ----
# 语义化版本: MAJOR.MINOR.PATCH
#   MAJOR: 不兼容的架构/接口变更
#   MINOR: 向后兼容的功能新增 (对应里程碑 M0..M6)
#   PATCH: 向后兼容的问题修复
VERSION = "2.8.0"
VERSION_MAJOR = 2
VERSION_MINOR = 8
VERSION_PATCH = 0

# 里程碑 → 版本映射 (见 docs/DEV_PLAN.md)
MILESTONE_VERSION = {
    "M0": "2.5.0",   # 可信度评估系统
    "M1": "2.6.0",   # 回测引擎 + 量化资金识别
    "M2": "2.7.0",   # 持仓分析 + 风险控制
    "M3": "2.8.0",   # 分层架构重构 + 图表实时标注
    "M4": "2.9.0",   # LLM 分析维度
    "M5": "3.0.0",   # 在线一键部署
    "M6": "3.1.0",   # 三维报告导出
}

# ---- 通用常量 ----
DEFAULT_PORT = 5000
APP_NAME = "股票可信度分析系统"


def data_path(code: str, suffix: str) -> Path:
    """统一数据文件路径: data/<code>_<suffix>.json"""
    return DATA_DIR / f"{code}_{suffix}.json"


def ensure_dir(p) -> Path:
    Path(p).mkdir(parents=True, exist_ok=True)
    return Path(p)
