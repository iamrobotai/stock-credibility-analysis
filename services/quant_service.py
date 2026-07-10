# -*- coding: utf-8 -*-
"""
quant_service.py — 量化分析编排
================================
封装 quant 子系统的对外调用，web 层不直接 import quant.engine。
"""
import os
from pathlib import Path

from common.config import BASE_DIR, OUTPUT_DIR


def run_quant(code: str) -> dict:
    """单股量化分析：回测 + 量化资金识别 + 三维结论。"""
    try:
        from quant import engine as QE
        pm = QE.load_peer_map()
        pa = QE.build_peer_averages(pm)
        res = QE.run_stock(code, peer_avg=pa)
        if res.get("error"):
            return {"ok": False, "error": res["error"]}
        return {"ok": True, "data": res}
    except Exception as e:
        return {"ok": False, "error": str(e)[:300]}


def run_quant_all() -> dict:
    """全量(176只)运行量化分析，输出至 output/quant。"""
    from quant import engine as QE
    out_dir = str(OUTPUT_DIR / "quant")
    result = QE.run_all(out_dir=out_dir)
    return result


def llm_report(code: str, provider: str | None = None) -> dict:
    """M4：对单股量化结果生成 LLM 自然语言三维归因（失败自动降级）。"""
    try:
        from quant import engine as QE
        from quant import llm_report as LR
        pm = QE.load_peer_map()
        pa = QE.build_peer_averages(pm)
        res = QE.run_stock(code, peer_avg=pa)
        if res.get("error"):
            return {"ok": False, "error": res["error"]}
        rep = LR.generate(res, provider=provider)
        return {"ok": True, "code": code, "name": res.get("name", ""),
                "report": rep}
    except Exception as e:
        return {"ok": False, "error": str(e)[:300]}


def list_quant_stocks() -> dict:
    """返回 data/*_raw.json 的股票清单 (code,name) 供量化页面下拉框。"""
    from common.config import DATA_DIR
    import glob, json
    files = sorted(glob.glob(str(DATA_DIR / "*_raw.json")))
    out = []
    for f in files:
        try:
            d = json.load(open(f, encoding="utf-8"))
            out.append({"code": d.get("code", ""), "name": d.get("name", "")})
        except Exception:
            pass
    return {"ok": True, "stocks": out}


__all__ = ["run_quant", "run_quant_all", "list_quant_stocks", "llm_report"]
