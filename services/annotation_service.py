# -*- coding: utf-8 -*-
"""
annotation_service.py — 标注服务编排
====================================
对外暴露 API 友好的 dict 接口；内部委托 AnnotationStore 实现。
关联查询（标注↔分段）在此聚合，保证「分段讨论与实时标注可关联查询」。
"""
from common.interfaces import AnnotationStore
from common.registry import has, resolve


def _store() -> AnnotationStore:
    try:
        if has("AnnotationStore", "json"):
            return resolve("AnnotationStore", "json")
    except Exception:
        pass
    from annotation.store import JsonAnnotationStore
    return JsonAnnotationStore()


def list_annotations(code: str) -> dict:
    try:
        anns = _store().list(code)
        return {"ok": True, "code": code, "annotations": anns,
                "count": len(anns)}
    except Exception as e:
        return {"ok": False, "error": str(e)[:200]}


def add_annotation(code: str, payload: dict) -> dict:
    try:
        rec = _store().add(code, payload)
        return {"ok": True, "annotation": rec}
    except Exception as e:
        return {"ok": False, "error": str(e)[:200]}


def delete_annotation(code: str, annotation_id: str) -> dict:
    try:
        ok = _store().delete(code, annotation_id)
        return {"ok": ok}
    except Exception as e:
        return {"ok": False, "error": str(e)[:200]}


def annotations_by_segment(code: str, segment_id: str) -> dict:
    """关联查询：某分段下的全部标注。"""
    try:
        anns = _store().by_segment(code, segment_id)
        return {"ok": True, "code": code, "segment_id": segment_id,
                "annotations": anns, "count": len(anns)}
    except Exception as e:
        return {"ok": False, "error": str(e)[:200]}


def segment_of_annotation(code: str, date: str) -> dict:
    """关联查询（反向）：某日期所属的分段 id。"""
    try:
        seg = _store().segment_of(code, date)
        return {"ok": True, "code": code, "date": date, "segment_id": seg}
    except Exception as e:
        return {"ok": False, "error": str(e)[:200]}


__all__ = [
    "list_annotations", "add_annotation", "delete_annotation",
    "annotations_by_segment", "segment_of_annotation",
]
