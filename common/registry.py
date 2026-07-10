# -*- coding: utf-8 -*-
"""
registry.py — 依赖注册表 (Dependency Registry)
==============================================
解耦「服务层」与「具体实现」：services 通过接口名 + 实现名解析依赖，
而非硬编码 import。具体实现在应用启动时由 bootstrap() 注册，
便于替换实现（如：本地采集 ↔ 在线采集、JSON 存储 ↔ 数据库存储）。

使用示例：
    from common.registry import resolve
    ds = resolve("DataSource", "default")      # 返回 DataSource 实例
    ds.collect(code, name)
"""
from typing import Callable, Dict, Any, Optional


class Registry:
    def __init__(self):
        # 结构: _store[interface][name] = factory callable -> instance
        self._store: Dict[str, Dict[str, Callable[[], Any]]] = {}
        self._default: Dict[str, str] = {}

    def register(self, interface: str, name: str, factory: Callable[[], Any],
                 default: bool = False) -> None:
        self._store.setdefault(interface, {})[name] = factory
        if default:
            self._default[interface] = name

    def set_default(self, interface: str, name: str) -> None:
        if interface in self._store and name in self._store[interface]:
            self._default[interface] = name

    def resolve(self, interface: str, name: Optional[str] = None) -> Any:
        iface = self._store.get(interface)
        if not iface:
            raise KeyError(f"未注册的接口: {interface}")
        key = name or self._default.get(interface)
        if not key or key not in iface:
            raise KeyError(f"接口 {interface} 无实现: {key}")
        return iface[key]()

    def names(self, interface: str) -> list:
        return list(self._store.get(interface, {}).keys())

    def has(self, interface: str, name: str) -> bool:
        return interface in self._store and name in self._store[interface]


# 全局单例
_REGISTRY = Registry()


def register(interface: str, name: str, factory: Callable[[], Any], default: bool = False) -> None:
    _REGISTRY.register(interface, name, factory, default)


def set_default(interface: str, name: str) -> None:
    _REGISTRY.set_default(interface, name)


def resolve(interface: str, name: Optional[str] = None) -> Any:
    return _REGISTRY.resolve(interface, name)


def names(interface: str) -> list:
    return _REGISTRY.names(interface)


def has(interface: str, name: str) -> bool:
    return _REGISTRY.has(interface, name)


def bootstrap() -> None:
    """应用启动注册已知实现。失败的实现不阻断其他注册。"""
    # 数据采集 (DataSource) — core 以目录方式加入 sys.path，模块为顶层
    try:
        from data_collector import collect as _collect
        register("DataSource", "default", lambda: _collect, default=True)
    except Exception:
        pass

    # 标注存储 (AnnotationStore)
    try:
        from annotation.store import JsonAnnotationStore
        register("AnnotationStore", "json", lambda: JsonAnnotationStore(), default=True)
    except Exception:
        pass

    # AI 提供商 (AiProvider) — 仅注册工厂，避免重复加载配置
    try:
        from ai_provider import list_providers
        register("AiProvider", "default", lambda: list_providers, default=True)
    except Exception:
        pass

    # 多周期价格曲线动态分析 (TimeframeAnalyzer)
    try:
        from quant.timeframe import MultiTimeframeAnalyzer
        register("TimeframeAnalyzer", "default",
                 lambda: MultiTimeframeAnalyzer(), default=True)
    except Exception:
        pass

    # 可信度融合器 (CredibilityIntegrator)
    try:
        from core.credibility_integrator import WeightedIntegrator
        register("CredibilityIntegrator", "weighted",
                 lambda: WeightedIntegrator(), default=True)
    except Exception:
        pass


__all__ = ["Registry", "register", "resolve", "names", "has", "set_default", "bootstrap"]
