# -*- coding: utf-8 -*-
"""
services — 服务编排层 (Service / Orchestration Layer)
===================================================
本层承载「业务流程编排」，是 web 层与 domain 层之间的协调者：
  - 调用 core/quant/export/ai 等 domain 模块完成具体计算
  - 通过 LogSink（由 web 层注入）输出进度，自身不持有 Web 状态
  - 不 import flask / request，保持可独立测试

依赖方向：services → common + domain → data（严格单向）
"""
from . import analysis_service, preview_service, quant_service
from . import export_service, data_service, annotation_service

__all__ = [
    "analysis_service", "preview_service", "quant_service",
    "export_service", "data_service", "annotation_service",
]
