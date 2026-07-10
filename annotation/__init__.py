# -*- coding: utf-8 -*-
"""
annotation — 标注领域模块 (Domain: Annotation)
============================================
负责图表实时标注的持久化与「标注 ↔ 分段」关联查询。
不依赖 web 层；对外通过 annotation_service 暴露 API 友好的 dict。
"""
from .store import JsonAnnotationStore, enrich_segment_link

__all__ = ["JsonAnnotationStore", "enrich_segment_link"]
