# -*- coding: utf-8 -*-
"""
data_service.py — 数据管理编排
==============================
封装增量更新状态、数据保存路径等管理操作。
"""
from pathlib import Path

from common.config import DATA_DIR, OUTPUT_DIR


def incremental_summary() -> dict:
    from incremental_manager import get_summary
    return {"ok": True, "summary": get_summary()}


def incremental_detail(code: str) -> dict:
    from incremental_manager import get_state
    return {"ok": True, "code": code, "state": get_state(code)}


def incremental_clear(code: str) -> dict:
    from incremental_manager import clear_state
    clear_state(code)
    return {"ok": True}


def savepath_get() -> dict:
    return {"ok": True, "data_dir": str(DATA_DIR), "output_dir": str(OUTPUT_DIR)}


def savepath_set(path: str) -> dict:
    if not path or not path.strip():
        return {"ok": False, "error": "路径不能为空"}
    try:
        p = Path(path)
        p.mkdir(parents=True, exist_ok=True)
        return {"ok": True, "path": str(p)}
    except Exception as e:
        return {"ok": False, "error": str(e)[:200]}


__all__ = [
    "incremental_summary", "incremental_detail", "incremental_clear",
    "savepath_get", "savepath_set",
]
