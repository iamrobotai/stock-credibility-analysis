# -*- coding: utf-8 -*-
"""
common — 基础设施层 (Infrastructure Layer)
=========================================
本层不依赖任何业务/领域模块，仅提供：
  - config : 全局路径、版本、常量
  - interfaces : 模块间通信的抽象契约 (ABC/Protocol)
  - registry : 依赖注册表 (解耦具体实现)

分层依赖方向（严格单向，禁止反向）：
  web(app)  →  services  →  domain(core/quant/export/ai)  →  data
  所有层均可依赖 common，但 common 不得依赖任何上层。
"""
from . import config, interfaces, registry

__all__ = ["config", "interfaces", "registry"]
