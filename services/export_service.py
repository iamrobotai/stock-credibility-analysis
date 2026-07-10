# -*- coding: utf-8 -*-
"""
export_service.py — 导出编排
==============================
封装 Excel/Word 等导出操作，web 层仅调用本服务。
"""
import os
import json
from common.config import DATA_DIR, OUTPUT_DIR


def export_excel(code: str) -> dict:
    """生成并下载 Excel，返回 {ok, path|error}。"""
    try:
        from gen_excel import generate as gen_xlsx
        name = code
        raw_path = DATA_DIR / f"{code}_raw.json"
        if raw_path.exists():
            raw = json.load(open(raw_path, encoding="utf-8"))
            name = raw.get("name", code)
        path = gen_xlsx(code, name, "")
        if path and os.path.exists(path):
            return {"ok": True, "path": path}
        return {"ok": False, "error": "Excel 生成失败"}
    except Exception as e:
        return {"ok": False, "error": str(e)[:200]}


def export_quant_word(code: str, with_llm: bool = True,
                      provider: str | None = None) -> dict:
    """M6：单股三维量化 Word 报告，返回 {ok, path|error}。"""
    try:
        from quant_to_word import generate as gen_word
        path = gen_word(code, with_llm=with_llm, provider=provider)
        if path and os.path.exists(path):
            return {"ok": True, "path": path}
        return {"ok": False, "error": "Word 生成失败"}
    except Exception as e:
        return {"ok": False, "error": str(e)[:300]}


def export_quant_industry(codes: list, title: str | None = None,
                          with_llm: bool = False) -> dict:
    """M6：行业整合三维 Word 报告，返回 {ok, path|error}。"""
    try:
        from quant_to_word import generate_industry as gen_ind
        path = gen_ind(codes, title=title, with_llm=with_llm)
        if path and os.path.exists(path):
            return {"ok": True, "path": path}
        return {"ok": False, "error": "行业 Word 生成失败"}
    except Exception as e:
        return {"ok": False, "error": str(e)[:300]}


__all__ = ["export_excel", "export_quant_word", "export_quant_industry"]
