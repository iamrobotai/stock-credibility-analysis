# -*- coding: utf-8 -*-
"""
analysis_service.py — 单股/批量分析编排
=========================================
将原 app.py 中的 run_single / run_batch 业务逻辑迁移至此。
web 层通过注入 log(回调) 与 should_stop(回调) 与本层解耦，
本层不依赖 Flask，可独立单元测试。
"""
import os
import sys
import json
import zipfile
import traceback
from datetime import datetime
from pathlib import Path
from typing import Callable, Dict, List, Optional

from common.config import DATA_DIR, OUTPUT_DIR


def _safe_log(log: Optional[Callable], msg: str, type: str = "info"):
    if callable(log):
        try:
            log(msg, type)
        except Exception:
            pass


def run_single(stock: Dict, log: Optional[Callable] = None,
               use_llm: bool = True, ai_provider: Optional[str] = None,
               ai_config: Optional[dict] = None, platforms: Optional[List[str]] = None,
               filter_emotion: bool = True, use_browser: bool = True,
               incremental: bool = False, data_outdir: Optional[str] = None) -> Dict:
    """单只股票全链路（采集→分段→评分→LLM→导出）。

    入参:
        stock: {"code","name","industry"}
        log:    LogSink 回调 log(msg, type)
    返回 result: {"code","name","status","docx","xlsx"}
    """
    code = stock["code"]
    name = stock.get("name", "")
    industry = stock.get("industry", "")
    if not name:
        try:
            from stock_resolver import resolve
            info = resolve(code)
            name = info.get("name", code)
            if not industry:
                industry = info.get("industry", "")
        except Exception:
            name = code

    _safe_log(log, f"开始分析: {name} ({code})", "info")
    result = {"code": code, "name": name, "status": "pending", "docx": None, "xlsx": None}

    try:
        # Step1: 数据采集
        plat_count = len(platforms) if platforms else 15
        _safe_log(log, f"[{name}] 采集数据 ({plat_count}平台 | 浏览器:{'是' if use_browser else '否'} | 增量:{'是' if incremental else '否'})...", "info")
        from data_collector import collect, DEFAULT_PLATFORMS
        outdir = data_outdir or str(DATA_DIR)
        collect(code, name, outdir=outdir,
                platforms=platforms or DEFAULT_PLATFORMS, filter_emotion=filter_emotion,
                use_browser=use_browser, incremental=incremental)

        raw_path = DATA_DIR / f"{code}_raw.json"
        if raw_path.exists():
            with open(raw_path, encoding="utf-8") as f:
                raw_data = json.load(f)
            total_items = sum(len(v) for k, v in raw_data.items()
                             if isinstance(v, list) and k not in ("code", "name"))
            ok_plats = sum(1 for k, v in raw_data.items()
                          if isinstance(v, list) and v and k not in ("code", "name"))
            _safe_log(log, f"[{name}] 采集完成: {total_items} 数据点, {ok_plats} 平台", "ok")

        # Step2: 价格分段
        _safe_log(log, f"[{name}] 价格分段...", "info")
        import segment as seg_mod
        seg_mod.run(code)
        _safe_log(log, f"[{name}] 分段完成", "ok")

        # Step3: D1-D9 评分
        _safe_log(log, f"[{name}] D1-D9 评分...", "info")
        import score_rules as score_mod
        score_mod.run(code)
        scored_path = DATA_DIR / f"{code}_scored.json"
        ad_count = 0
        if scored_path.exists():
            with open(scored_path, encoding="utf-8") as f:
                scored_data = json.load(f)
            ad_count = sum(1 for p in scored_data.get("posts", []) if p.get("D8", {}).get("is_ad"))
            try:
                raw_path = DATA_DIR / f"{code}_raw.json"
                raw = json.load(open(raw_path, encoding="utf-8"))
                kline = raw.get("kline", [])
                if kline:
                    from technical import compute_technical_score
                    d9 = compute_technical_score(kline)
                    scored_data["D9"] = d9
                    with open(scored_path, "w", encoding="utf-8") as f:
                        json.dump(scored_data, f, ensure_ascii=False, indent=2)
            except Exception:
                pass
        # Step3.5: 量化多周期 × 综合可信度（M7 集成）
        try:
            from credibility_service import (
                analyze as cred_analyze, persist as cred_persist)
            cred = cred_analyze(code)
            if cred.get("ok"):
                cred_persist(code, cred)
                comp = cred.get("comprehensive", {})
                _safe_log(log,
                           f"[{name}] 量化多周期+综合可信度: "
                           f"{comp.get('comprehensive_score')} ({comp.get('grade','')})", "ok")
        except Exception as e:
            _safe_log(log, f"[{name}] 综合可信度跳过: {str(e)[:60]}", "warn")

        _safe_log(log, f"[{name}] 评分完成: 广告={ad_count}条", "ok")

        # Step4: LLM 增强
        if use_llm:
            active = ai_provider or "ollama"
            _safe_log(log, f"[{name}] LLM 深度分析 ({active})...", "info")
            from llm_enhance import process_stock
            process_stock(code, provider=ai_provider, config=ai_config)
            _safe_log(log, f"[{name}] LLM 分析完成", "ok")

        # Step5: 生成 docx + excel
        _safe_log(log, f"[{name}] 生成报告...", "info")
        from gen_docx_full import generate
        safe_name = name.replace("/", "_").replace(" ", "")
        generate(code, name, industry)
        docx_name = f"{safe_name}_{code}_完整分析.docx"
        docx_path = OUTPUT_DIR / docx_name

        xlsx_name = None
        try:
            from gen_excel import generate as gen_xlsx
            gen_xlsx(code, name, industry)
            xlsx_name = f"{safe_name}_{code}_分析.xlsx"
            _safe_log(log, f"[{name}] Excel 已生成", "ok")
        except Exception as e:
            _safe_log(log, f"[{name}] Excel 跳过: {str(e)[:60]}", "warn")

        if docx_path.exists():
            result["status"] = "ok"
            result["docx"] = docx_name
            result["xlsx"] = xlsx_name
            result["code"] = code
            _safe_log(log, f"[{name}] 完成: {docx_name} ({docx_path.stat().st_size//1024}KB)", "ok")
        else:
            result["status"] = "fail"
            _safe_log(log, f"[{name}] docx 未生成", "fail")

    except Exception as e:
        result["status"] = "fail"
        _safe_log(log, f"[{name}] 失败: {str(e)[:100]}", "fail")
        traceback.print_exc()

    return result


def run_batch(stocks: List[Dict], log: Optional[Callable] = None,
              should_stop: Optional[Callable[[], bool]] = None,
              use_llm: bool = True, ai_provider: Optional[str] = None,
              ai_config: Optional[dict] = None, platforms: Optional[List[str]] = None,
              filter_emotion: bool = True, use_browser: bool = True,
              incremental: bool = False, data_outdir: Optional[str] = None,
              zip_name: Optional[str] = None) -> Dict:
    """批量编排：遍历 stocks 调用 run_single，结束时可选打包 ZIP。

    入参 should_stop: 无参返回 bool，True 表示中止。
    返回 summary: {"total","success","fail","results":[...],"zip":name|None}
    """
    total = len(stocks)
    results: List[Dict] = []
    success = 0
    fail = 0
    _safe_log(log, f"批量开始: 共 {total} 只", "info")

    # 启动即探测数据源可达性，把「哪些源挂了」打到日志，避免笼统「网络超时」
    try:
        from data_collector import probe_sources
        _safe_log(log, "正在探测数据源可达性...", "info")
        for line in probe_sources():
            _safe_log(log, "  源探测: " + line, "info" if "✅" in line else "warn")
    except Exception:
        pass

    for i, stock in enumerate(stocks):
        if callable(should_stop) and should_stop():
            _safe_log(log, "用户停止", "warn")
            break
        _safe_log(log, f"[{i+1}/{total}] {stock.get('name', stock['code'])} ({stock['code']})", "info")
        r = run_single(stock, log, use_llm, ai_provider, ai_config, platforms,
                       filter_emotion, use_browser, incremental, data_outdir)
        results.append(r)
        if r.get("status") == "ok":
            success += 1
        else:
            fail += 1

    zip_file = None
    if success > 1:
        _safe_log(log, "打包 ZIP...", "info")
        import zipfile as _zf
        zname = zip_name or f"股票可信度分析_{datetime.now().strftime('%Y%m%d_%H%M')}.zip"
        zpath = OUTPUT_DIR / zname
        with _zf.ZipFile(zpath, "w", _zf.ZIP_DEFLATED) as z:
            for r in results:
                if r.get("docx"):
                    dp = OUTPUT_DIR / r["docx"]
                    if dp.exists():
                        ind = r.get("industry", "other")
                        z.write(dp, f"{ind}/{r['docx']}")
                if r.get("xlsx"):
                    xp = OUTPUT_DIR / r["xlsx"]
                    if xp.exists():
                        ind = r.get("industry", "other")
                        z.write(xp, f"{ind}/{r['xlsx']}")
        zip_file = zname
        _safe_log(log, f"ZIP 完成: {zname}", "ok")

    _safe_log(log, f"全部完成! 成功 {success} / 失败 {fail}", "ok")
    return {"total": total, "success": success, "fail": fail, "results": results, "zip": zip_file}


__all__ = ["run_single", "run_batch"]
