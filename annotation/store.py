# -*- coding: utf-8 -*-
"""
store.py — 标注存储实现 (AnnotationStore)
=========================================
基于 JSON 文件的轻量持久化（零外部依赖，可后续替换为数据库实现）。
数据契约: data/<code>_annotations.json = [Annotation, ...]

Annotation 字段:
  id         str   唯一 id (服务端生成)
  type       "point" | "range"
  label      str   简短标题
  note       str   备注 (可选)
  created_at str   ISO 时间
  # point 类型:
  date       str   "YYYY-MM-DD"
  price      float (可选)
  # range 类型:
  start_date str   "YYYY-MM-DD"
  end_date   str   "YYYY-MM-DD"
  # 以下为读取时派生的关联字段（不持久化）:
  segment_id str   所属/重叠的分段 id (来自 <code>_segments.json)

关联查询核心：以「日期」为纽带，将标注挂到分段讨论机制上，
满足需求「分段讨论与实时标注之间应可关联查询」。
"""
import json
import os
import uuid
from datetime import datetime
from typing import Any, Dict, List, Optional

from common.config import DATA_DIR
from common.interfaces import AnnotationStore


def _seg_path(code: str) -> str:
    return str(DATA_DIR / f"{code}_segments.json")


def _ann_path(code: str) -> str:
    return str(DATA_DIR / f"{code}_annotations.json")


def load_segments(code: str) -> List[Dict[str, Any]]:
    p = _seg_path(code)
    if os.path.exists(p):
        try:
            return json.load(open(p, encoding="utf-8"))
        except Exception:
            return []
    return []


def segment_id_for_date(segments: List[Dict[str, Any]], date: str) -> Optional[str]:
    """返回包含给定日期的分段 id（按 start<=date<=end 判定）。"""
    if not date:
        return None
    for s in segments:
        sd, ed = s.get("start_date"), s.get("end_date")
        if sd and ed and sd <= date <= ed:
            return s.get("id")
    return None


def enrich_segment_link(code: str, ann: Dict[str, Any]) -> Dict[str, Any]:
    """为单条标注派生关联的 segment_id（不修改入参，返回新 dict）。"""
    seg = load_segments(code)
    if ann.get("type") == "range":
        key_date = ann.get("start_date") or ann.get("end_date")
    else:
        key_date = ann.get("date")
    out = dict(ann)
    out["segment_id"] = segment_id_for_date(seg, key_date) if key_date else None
    return out


class JsonAnnotationStore(AnnotationStore):
    """JSON 文件实现的标注存储。"""

    def list(self, code: str) -> List[Dict[str, Any]]:
        p = _ann_path(code)
        if not os.path.exists(p):
            return []
        try:
            raw = json.load(open(p, encoding="utf-8"))
        except Exception:
            return []
        return [enrich_segment_link(code, a) for a in raw]

    def add(self, code: str, annotation: Dict[str, Any]) -> Dict[str, Any]:
        ann_type = annotation.get("type")
        if ann_type not in ("point", "range"):
            raise ValueError("type 必须为 'point' 或 'range'")
        if ann_type == "point":
            if not annotation.get("date"):
                raise ValueError("point 标注需要 date")
        else:
            if not annotation.get("start_date") or not annotation.get("end_date"):
                raise ValueError("range 标注需要 start_date 与 end_date")

        record = {
            "id": f"a_{datetime.now().strftime('%Y%m%d%H%M%S')}_{uuid.uuid4().hex[:4]}",
            "type": ann_type,
            "label": str(annotation.get("label", "")).strip(),
            "note": str(annotation.get("note", "")).strip(),
            "created_at": datetime.now().isoformat(timespec="seconds"),
        }
        if ann_type == "point":
            record["date"] = annotation["date"]
            if annotation.get("price") is not None:
                try:
                    record["price"] = float(annotation["price"])
                except Exception:
                    pass
        else:
            record["start_date"] = annotation["start_date"]
            record["end_date"] = annotation["end_date"]

        store = self.list_raw(code)
        store.append(record)
        self._save(code, store)
        return enrich_segment_link(code, record)

    def delete(self, code: str, annotation_id: str) -> bool:
        store = self.list_raw(code)
        new_store = [a for a in store if a.get("id") != annotation_id]
        if len(new_store) == len(store):
            return False
        self._save(code, new_store)
        return True

    def by_segment(self, code: str, segment_id: str) -> List[Dict[str, Any]]:
        return [a for a in self.list(code) if a.get("segment_id") == segment_id]

    def segment_of(self, code: str, date: str) -> Optional[str]:
        return segment_id_for_date(load_segments(code), date)

    # ---- 内部工具 ----
    def list_raw(self, code: str) -> List[Dict[str, Any]]:
        p = _ann_path(code)
        if not os.path.exists(p):
            return []
        try:
            return json.load(open(p, encoding="utf-8"))
        except Exception:
            return []

    def _save(self, code: str, data: List[Dict[str, Any]]) -> None:
        p = _ann_path(code)
        os.makedirs(os.path.dirname(p), exist_ok=True)
        with open(p, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)


__all__ = ["JsonAnnotationStore", "enrich_segment_link",
            "segment_id_for_date", "load_segments"]
