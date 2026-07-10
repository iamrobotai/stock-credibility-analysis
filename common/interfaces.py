# -*- coding: utf-8 -*-
"""
interfaces.py — 模块间通信的抽象契约 (Contracts)
================================================
所有跨层调用一律面向接口（而非具体实现）编程。
业务模块（domain）实现下列 ABC；services 仅依赖接口，通过 registry 解析具体实现。

契约约定：
  - 每个接口只暴露「稳定、最小、内聚」的方法集合
  - 入参/出参以 dict / 基础类型为主，禁止传递框架对象（如 Flask request）
  - 方法失败时抛异常或返回 {"ok": False, "error": ...}，由调用层决定降级策略
"""
from abc import ABC, abstractmethod
from typing import Any, Dict, List, Optional


# =====================================================================
# 领域层接口 (Domain Interfaces)
# =====================================================================

class DataSource(ABC):
    """数据采集接口：将任意平台/渠道的数据归一为统一数据契约。"""

    @abstractmethod
    def collect(self, code: str, name: str = "", **kwargs) -> Dict[str, Any]:
        """采集单只股票数据，返回统一 raw 字典（含 kline/financials/news...）。"""
        ...


class Analyzer(ABC):
    """分析接口：对原始/中间数据做加工，产出结构化结论。"""

    @abstractmethod
    def analyze(self, code: str, **kwargs) -> Dict[str, Any]:
        """执行分析，返回结论字典。"""
        ...


class ChartRenderer(ABC):
    """图表渲染接口：由数据生成图表文件。"""

    @abstractmethod
    def render(self, code: str, **kwargs) -> Optional[str]:
        """渲染图表，返回生成文件的路径；失败返回 None。"""
        ...


class Exporter(ABC):
    """导出接口：将分析结果导出为目标文档。"""

    @abstractmethod
    def export(self, code: str, **kwargs) -> Optional[str]:
        """导出文档，返回文件路径；失败返回 None。"""
        ...


class TimeframeAnalyzer(ABC):
    """多周期价格曲线动态分析接口。

    将单一日 K 线动态重采样为多个时间维度（日/周/月），
    并按时间变化计算关键量化指标（均线趋势、波动率、成交量变化等）。
    其输出（quant contract）作为 CredibilityIntegrator 的输入之一，
    用于与可信度评估体系（D1–D9）融合为综合可信度评分。
    """

    TIMEFRAMES = ("day", "week", "month")

    @abstractmethod
    def resample(self, kline: List[Dict[str, Any]], tf: str) -> List[Dict[str, Any]]:
        """将日 K 线重采样为指定周期的 OHLCV 序列。

        入参: kline 为日线列表（含 date/open/high/low/close/volume/amount）。
        返回: 同结构列表，按时间升序；tf='day' 时原样返回。
        """
        ...

    @abstractmethod
    def analyze_timeframe(self, bars: List[Dict[str, Any]], tf: str) -> Dict[str, Any]:
        """对单个时间周期动态计算关键量化指标。

        入参: bars 为该周期的 OHLCV 序列。
        返回: 结构化指标 dict，含 ma_trend(均线排列) / volatility(年化波动) /
              volume_change(量能变化) / momentum(动量) / trend_strength(趋势强度) /
              signal(偏多/偏空/中性) / score(0-100 量化子评分)。
        """
        ...

    @abstractmethod
    def analyze(self, kline: List[Dict[str, Any]],
                timeframes=None) -> Dict[str, Any]:
        """多周期动态分析总入口。

        返回 quant contract:
            {"timeframes": {tf: analyze_timeframe(...), ...},
             "alignment": 跨周期共振描述,
             "composite_quant_score": 0-100 加权综合(月>周>日)}
        """
        ...


class CredibilityIntegrator(ABC):
    """可信度融合接口：量化多周期分析 ↔ 可信度评估体系。

    将既有可信度评估（D1–D9 内容评分 + D9 技术信号）
    与量化多周期分析（TimeframeAnalyzer 输出）融合，
    产出统一的「综合可信度评分」，供可信度系统与前端消费。
    """

    @abstractmethod
    def integrate(self, credibility: Dict[str, Any],
                  quant: Dict[str, Any]) -> Dict[str, Any]:
        """融合可信度评估与量化多周期分析。

        入参:
            credibility: {"content_avg":0-1, "d9":0-1, "ad_flag":bool,
                           "post_count":int, ...}（来自 D1–D8 均值 + D9）
            quant:      TimeframeAnalyzer.analyze() 的输出（quant contract）
        返回 comprehensive contract:
            {"comprehensive_score":0-100, "grade":str, "explanation":str,
             "components": {...}, "timeframe_detail": {...}}
        """
        ...


class AnnotationStore(ABC):
    """标注存储接口：图表实时标注的持久化与关联查询。"""

    @abstractmethod
    def list(self, code: str) -> List[Dict[str, Any]]:
        """列出某股票的全部标注。"""
        ...

    @abstractmethod
    def add(self, code: str, annotation: Dict[str, Any]) -> Dict[str, Any]:
        """新增一条标注，返回带 id/created_at 的完整记录。"""
        ...

    @abstractmethod
    def delete(self, code: str, annotation_id: str) -> bool:
        """删除一条标注，成功返回 True。"""
        ...

    @abstractmethod
    def by_segment(self, code: str, segment_id: str) -> List[Dict[str, Any]]:
        """查询与指定分段相关联的全部标注（关联查询）。"""
        ...

    @abstractmethod
    def segment_of(self, code: str, date: str) -> Optional[str]:
        """给定日期，返回其所属分段 id（关联查询反向路径）。"""
        ...


# =====================================================================
# 服务层接口 (Service Interfaces)
# =====================================================================

class Service(ABC):
    """服务层标记基类：所有 services 包内的服务应继承本类，便于统一注册与测试。"""
    name: str = "service"

    @abstractmethod
    def health(self) -> Dict[str, Any]:
        """服务自检，返回 {"ok": bool, ...}。"""
        ...


class LogSink:
    """日志回调契约：web 层向 services 注入日志输出，实现表现层与逻辑层解耦。

    典型用法：
        svc.run_single(stock, log=log_sink)
    其中 log_sink 由 Flask 的 TaskState.log 提供。
    """

    def __call__(self, msg: str, type: str = "info") -> None:
        raise NotImplementedError


__all__ = [
    "DataSource", "Analyzer", "ChartRenderer", "Exporter",
    "AnnotationStore", "Service", "LogSink",
    "TimeframeAnalyzer", "CredibilityIntegrator",
]
