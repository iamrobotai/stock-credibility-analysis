# -*- coding: utf-8 -*-
"""
股票可信度分析系统 - Flask Web 应用 (表现层 / Presentation Layer)
====================================================================
职责边界（分层架构）：
  - 本文件 = 表现层：仅定义 HTTP 路由、解析请求/响应、维护任务状态。
  - 业务逻辑全部委托 services.*（服务编排层），不在此内联。
  - services 依赖 common.interfaces 定义的契约，面向接口而非具体实现。

依赖方向： web(app) → services → domain(core/quant/export/ai) → data
启动: python app.py   访问: http://localhost:5000
"""
import os
import sys
import json
import time
import glob
import threading
import traceback
from pathlib import Path
from datetime import datetime

from flask import Flask, render_template, jsonify, request, send_file, Response

# ---- 基础设施层 ----
from common.config import BASE_DIR, DATA_DIR, OUTPUT_DIR, VERSION, APP_NAME
from common.registry import bootstrap as registry_bootstrap

# 关键顺序约束：sys.path 子目录注入必须位于「from services import ...」之前。
# services.credibility_service 在模块级调用 registry.bootstrap() 注册
# TimeframeAnalyzer / CredibilityIntegrator 契约，其内部 `from core...` /
# `from quant...` 依赖 core、quant 已进入 sys.path；若顺序颠倒，注册会
# 被模块级 try/except 静默吞掉，导致后续 resolve 报「未注册」错误。
# PyInstaller 打包后：
#  - one-file 模式：templates/static/configs 由 bootloader 解压到临时目录 sys._MEIPASS；
#  - one-folder 模式：资源与 exe 同目录（sys.executable 父目录）。
# 因此 frozen 时优先用 sys._MEIPASS，缺失时回退到 exe 父目录。
if getattr(sys, "frozen", False):
    _mei = getattr(sys, "_MEIPASS", None)
    BASE_DIR = Path(_mei).resolve() if _mei else Path(sys.executable).resolve().parent
else:
    BASE_DIR = Path(__file__).resolve().parent
# 兼容旧脚本目录结构：将子目录加入 sys.path，使 domain 模块可被 import
for _subdir in ["core", "ai", "export", "scripts"]:
    _subdir_path = BASE_DIR / _subdir
    if _subdir_path.exists():
        sys.path.insert(0, str(_subdir_path))

# ---- 服务编排层（业务逻辑的唯一定义处）----
from services import (
    analysis_service, preview_service, quant_service,
    export_service, data_service, annotation_service,
    credibility_service,
)

app = Flask(__name__, template_folder=str(BASE_DIR / "templates"))

tasks = {}
quant_runs = {}


class TaskState:
    """表现层任务状态（Web 关注点，不混入业务逻辑）。"""
    def __init__(self, run_id, payload):
        self.run_id = run_id
        self.payload = payload
        self.status = "running"
        self.total = 0
        self.done = 0
        self.success = 0
        self.fail = 0
        self.elapsed = "0s"
        self.logs = []
        self.results = []
        self.zip = None
        self.start_time = time.time()
        self.stop_flag = False

    def log(self, msg, type="info"):
        self.logs.append({"msg": msg, "type": type, "time": datetime.now().strftime("%H:%M:%S")})
        if len(self.logs) > 500:
            self.logs = self.logs[-300:]

    def to_dict(self):
        elapsed = time.time() - self.start_time
        self.elapsed = f"{elapsed:.0f}s" if elapsed < 60 else f"{elapsed/60:.1f}min"
        return {
            "status": self.status, "total": self.total, "done": self.done,
            "success": self.success, "fail": self.fail, "elapsed": self.elapsed,
            "logs": self.logs[-50:], "results": self.results, "zip": self.zip,
        }


# ============================================================
# Web 任务编排（仅协调，逻辑在 services）
# ============================================================

def run_batch_task(state):
    """批量任务线程：解析股票清单 → 委托 analysis_service.run_batch。"""
    try:
        payload = state.payload
        if payload["mode"] == "industry":
            sys.path.insert(0, str(BASE_DIR))
            from run_all_20 import INDUSTRIES
            stocks = []
            for ind in INDUSTRIES:
                for c in ind["companies"]:
                    stocks.append({"code": c["code"], "name": c["name"], "industry": ind["name"]})
            state.total = len(stocks)
        elif payload["mode"] == "batch":
            stocks = payload["stocks"]
            state.total = len(stocks)
        else:
            stocks = [{"code": payload["code"],
                       "name": payload.get("name", ""),
                       "industry": payload.get("industry", "")}]
            state.total = 1

        use_llm = payload.get("use_llm", True)
        ai_provider = payload.get("ai_provider")
        ai_config = payload.get("ai_config")
        platforms = payload.get("platforms")
        filter_emotion = payload.get("filter_emotion", True)
        use_browser = payload.get("use_browser", True)
        incremental = payload.get("incremental", False)
        data_outdir = payload.get("data_outdir")

        summary = analysis_service.run_batch(
            stocks, log=state.log, should_stop=lambda: state.stop_flag,
            use_llm=use_llm, ai_provider=ai_provider, ai_config=ai_config,
            platforms=platforms, filter_emotion=filter_emotion,
            use_browser=use_browser, incremental=incremental, data_outdir=data_outdir,
        )
        state.total = summary["total"]
        state.success = summary["success"]
        state.fail = summary["fail"]
        for r in summary["results"]:
            state.results.append(r)
        state.zip = summary["zip"]
        state.status = "completed"
    except Exception as e:
        state.status = "completed"
        state.log(f"任务异常: {str(e)[:200]}", "fail")
        traceback.print_exc()


def _quant_run(target):
    rid = target["run_id"]
    try:
        result = quant_service.run_quant_all()
        quant_runs[rid].update({
            "status": "done", "progress": 100,
            "total": result["overview"]["total"],
            "overview": result["overview"],
        })
    except Exception as e:
        quant_runs[rid].update({"status": "error", "error": str(e)[:300]})


# ============================================================
# 路由 (Routes)
# ============================================================

@app.route("/")
def index():
    # 合并版单页：可信度分析 + 量化分析（回测/资金/融合）同页呈现
    return render_template("dashboard.html")


@app.route("/api/hot")
def api_hot():
    try:
        from hot_stocks import get_all_hot
        result = [None]
        def _fetch():
            result[0] = get_all_hot()
        t = threading.Thread(target=_fetch, daemon=True)
        t.start()
        t.join(timeout=10)
        if result[0]:
            return jsonify({"ok": True, "data": result[0]})
        return jsonify({"ok": True, "data": {
            "stocks": [], "industries": [], "concepts": [],
            "update_time": "数据源超时 (非交易时段或网络问题)"}})
    except Exception as e:
        return jsonify({"ok": True, "data": {
            "stocks": [], "industries": [], "concepts": [],
            "update_time": f"API异常: {str(e)[:40]}"}})


@app.route("/api/resolve/<code>")
def api_resolve(code):
    try:
        from stock_resolver import resolve
        return jsonify({"ok": True, "data": resolve(code)})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)[:200]})


@app.route("/api/platforms")
def api_platforms():
    from data_collector import get_platform_list, DEFAULT_PLATFORMS, HIGH_VALUE_PLATFORMS
    return jsonify({"platforms": get_platform_list(),
                    "default": DEFAULT_PLATFORMS,
                    "high_value": HIGH_VALUE_PLATFORMS})


@app.route("/api/ai/providers")
def ai_providers():
    from ai_provider import list_providers
    return jsonify({"providers": list_providers()})


@app.route("/api/ai/config", methods=["GET", "POST"])
def ai_config():
    from ai_provider import load_config, save_config, _LOCAL_PROVIDERS
    if request.method == "GET":
        cfg = load_config()
        safe = {"active_provider": cfg.get("active_provider"), "providers": {}}
        for k, v in cfg.get("providers", {}).items():
            safe["providers"][k] = {
                "model": v.get("model", ""), "label": v.get("label", k),
                "has_key": bool(v.get("api_key")),
                "needs_key": k not in _LOCAL_PROVIDERS,
                "url": v.get("url", ""),
            }
        return jsonify(safe)
    data = request.json
    cfg = load_config()
    if "active_provider" in data:
        cfg["active_provider"] = data["active_provider"]
    if "providers" in data:
        for pid, pval in data["providers"].items():
            if pid in cfg["providers"]:
                if "model" in pval:
                    cfg["providers"][pid]["model"] = pval["model"]
                if "api_key" in pval and pval["api_key"]:
                    cfg["providers"][pid]["api_key"] = pval["api_key"]
    save_config(cfg)
    return jsonify({"ok": True})


@app.route("/api/ai/test", methods=["POST"])
def ai_test():
    from ai_provider import test_provider
    data = request.json or {}
    return jsonify(test_provider(data.get("provider")))


@app.route("/api/ai/models/<provider>")
def ai_models(provider):
    from ai_provider import list_models
    try:
        models = list_models(provider)
        if models:
            return jsonify({"ok": True, "models": models})
        return jsonify({"ok": False, "error": "未检测到模型，请确认服务已启动"})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)[:200]})


@app.route("/api/run", methods=["POST"])
def api_run():
    payload = request.json
    run_id = f"run_{datetime.now().strftime('%Y%m%d%H%M%S')}"
    state = TaskState(run_id, payload)
    tasks[run_id] = state
    threading.Thread(target=run_batch_task, args=(state,), daemon=True).start()
    return jsonify({"ok": True, "run_id": run_id})


@app.route("/api/status/<run_id>")
def api_status(run_id):
    state = tasks.get(run_id)
    if not state:
        return jsonify({"ok": False, "error": "task not found"})
    return jsonify(state.to_dict())


@app.route("/api/stop/<run_id>", methods=["POST"])
def api_stop(run_id):
    state = tasks.get(run_id)
    if state:
        state.stop_flag = True
        return jsonify({"ok": True})
    return jsonify({"ok": False, "error": "task not found"})


# ============================================================
# 量化分析 API (services.quant_service)
# ============================================================

@app.route("/api/quant/<code>")
def api_quant(code):
    return jsonify(quant_service.run_quant(code))


@app.route("/api/quant/run", methods=["POST"])
def api_quant_run():
    rid = f"quant_{datetime.now().strftime('%Y%m%d%H%M%S')}"
    quant_runs[rid] = {"status": "running", "progress": 0, "total": 176}
    threading.Thread(target=_quant_run, args=({"run_id": rid},), daemon=True).start()
    return jsonify({"ok": True, "run_id": rid})


@app.route("/api/quant/status/<run_id>")
def api_quant_status(run_id):
    st = quant_runs.get(run_id)
    if not st:
        return jsonify({"ok": False, "error": "task not found"})
    return jsonify({"ok": True, **st})


@app.route("/api/quant/llm/<code>", methods=["POST", "GET"])
def api_quant_llm(code):
    """M4：LLM 自然语言三维归因（可选 provider，缺 AI 自动降级）。"""
    provider = None
    if request.method == "POST":
        provider = (request.json or {}).get("provider")
    else:
        provider = request.args.get("provider")
    return jsonify(quant_service.llm_report(code, provider))


@app.route("/quant")
def page_quant():
    return render_template("quant.html")


@app.route("/api/quant/stocks")
def api_quant_stocks():
    return jsonify(quant_service.list_quant_stocks())


# ============================================================
# 预览 / 图表 / 技术指标 (services.preview_service)
# ============================================================

@app.route("/api/preview/<code>")
def api_preview(code):
    return jsonify(preview_service.build_preview(code))


@app.route("/api/kline/<code>")
def api_kline(code):
    """返回完整 K 线序列 + 分段，供前端交互式图表实时标注。"""
    return jsonify(preview_service.build_kline(code))


@app.route("/api/quant/timeframe/<code>")
def api_quant_timeframe(code):
    """多周期（日K/周K/月K）动态量化分析。"""
    r = credibility_service.analyze(code)
    if not r.get("ok"):
        return jsonify({"ok": False, "error": r.get("error", "分析失败")}), 404
    return jsonify({"ok": True, "code": code, "name": r.get("name"),
                    "timeframe_analysis": r["timeframe_analysis"]})


@app.route("/api/credibility/<code>")
def api_credibility(code):
    """量化多周期 × 可信度评估 融合：综合可信度评分。"""
    r = credibility_service.analyze(code)
    if not r.get("ok"):
        return jsonify({"ok": False, "error": r.get("error", "分析失败")}), 404
    return jsonify(r)


@app.route("/api/chart/<code>")
def api_chart(code):
    res = preview_service.render_chart(code)
    if res.get("ok"):
        return send_file(str(DATA_DIR / res["chart"]), mimetype="image/png")
    return "Chart not found", 404


@app.route("/api/technical/<code>")
def api_technical(code):
    return jsonify(preview_service.build_technical(code))


@app.route("/api/industry/chart", methods=["POST"])
def api_industry_chart():
    data = request.json or {}
    return jsonify(preview_service.build_industry_chart(
        data.get("codes", []), data.get("industry", "行业对比")))


@app.route("/api/industry/preview")
def api_industry_preview():
    return jsonify(preview_service.build_industry_preview())


@app.route("/api/export/excel/<code>")
def api_export_excel(code):
    res = export_service.export_excel(code)
    if res.get("ok"):
        return send_file(res["path"], as_attachment=True,
                        download_name=os.path.basename(res["path"]))
    return jsonify({"ok": False, "error": res.get("error", "Excel 生成失败")}), 500


@app.route("/api/export/quant-word/<code>")
def api_export_quant_word(code):
    """M6：导出单股三维量化 Word 报告。"""
    with_llm = request.args.get("llm", "1") != "0"
    res = export_service.export_quant_word(code, with_llm=with_llm)
    if res.get("ok"):
        return send_file(res["path"], as_attachment=True,
                        download_name=os.path.basename(res["path"]))
    return jsonify({"ok": False, "error": res.get("error", "Word 生成失败")}), 500


@app.route("/api/export/quant-industry", methods=["POST"])
def api_export_quant_industry():
    """M6：导出行业整合三维 Word 报告。"""
    data = request.json or {}
    codes = data.get("codes") or []
    if not codes:
        return jsonify({"ok": False, "error": "缺少 codes"}), 400
    res = export_service.export_quant_industry(
        codes, title=data.get("title"), with_llm=bool(data.get("llm")))
    if res.get("ok"):
        return send_file(res["path"], as_attachment=True,
                        download_name=os.path.basename(res["path"]))
    return jsonify({"ok": False, "error": res.get("error", "行业 Word 生成失败")}), 500


# ============================================================
# 图表实时标注 API (services.annotation_service)
# 关联查询：标注 ↔ 分段讨论
# ============================================================

@app.route("/api/annotations/<code>", methods=["GET", "POST", "DELETE"])
def api_annotations(code):
    if request.method == "GET":
        return jsonify(annotation_service.list_annotations(code))
    if request.method == "POST":
        return jsonify(annotation_service.add_annotation(code, request.json or {}))
    # DELETE：支持 JSON body 或 query 参数传入 id
    aid = (request.json or {}).get("id") or request.args.get("id")
    if not aid:
        return jsonify({"ok": False, "error": "缺少 id"}), 400
    return jsonify(annotation_service.delete_annotation(code, aid))


@app.route("/api/annotations/<code>/segment/<seg_id>")
def api_ann_by_segment(code, seg_id):
    """关联查询：某分段下的全部标注。"""
    return jsonify(annotation_service.annotations_by_segment(code, seg_id))


@app.route("/api/annotations/<code>/segment-of/<date>")
def api_seg_of(code, date):
    """关联查询（反向）：某日期所属分段。"""
    return jsonify(annotation_service.segment_of_annotation(code, date))


# ============================================================
# 数据管理 API (services.data_service)
# ============================================================

@app.route("/api/data/savepath", methods=["GET", "POST"])
def api_data_savepath():
    if request.method == "GET":
        return jsonify(data_service.savepath_get())
    return jsonify(data_service.savepath_set((request.json or {}).get("path", "")))


@app.route("/api/data/incremental")
def api_incremental_summary():
    return jsonify(data_service.incremental_summary())


@app.route("/api/data/incremental/<code>")
def api_incremental_detail(code):
    return jsonify(data_service.incremental_detail(code))


@app.route("/api/data/incremental/<code>", methods=["DELETE"])
def api_incremental_clear(code):
    return jsonify(data_service.incremental_clear(code))


@app.route("/api/data/browser-test", methods=["POST"])
def api_browser_test():
    try:
        from browser_login import is_available
        available = is_available()
        return jsonify({"ok": True, "available": available,
                        "message": "Playwright 可用" if available else "Playwright 未安装"})
    except Exception as e:
        return jsonify({"ok": True, "available": False, "message": f"检测失败: {str(e)[:100]}"})


@app.route("/api/data/browser-fetch", methods=["POST"])
def api_browser_fetch():
    data = request.json or {}
    source = data.get("source", "")
    code = data.get("code", "")
    name = data.get("name", "")
    from browser_login import is_available
    if not is_available():
        return jsonify({"ok": False, "error": "Playwright 未安装，请运行: pip install playwright && playwright install chromium"})
    try:
        if source in ("xueqiu_posts", "xueqiu"):
            from browser_login import (load_cookies, scrape_xueqiu_posts, scrape_xueqiu_fundamentals)
            ck = load_cookies("xueqiu")
            if not ck:
                return jsonify({"ok": False, "error": "雪球未登录，请先运行: python scripts/login_and_scrape.py"})
            if source == "xueqiu_posts":
                posts = scrape_xueqiu_posts(ck, code, max_count=30)
                return jsonify({"ok": True, "data": posts, "count": len(posts)})
            fund = scrape_xueqiu_fundamentals(ck, code)
            return jsonify({"ok": True, "data": [fund] if fund else [], "count": 1 if fund else 0})
        elif source == "zhihu":
            from browser_login import (load_cookies, BrowserSession, inject_cookies, scrape_zhihu)
            ck = load_cookies("zhihu")
            if not ck:
                return jsonify({"ok": False, "error": "知乎未登录，请先运行: python scripts/login_and_scrape.py"})
            with BrowserSession("zhihu", headless=True) as (ctx, page):
                inject_cookies(ctx, ck)
                results = scrape_zhihu(page, name if name else code, max_count=20)
            return jsonify({"ok": True, "data": results, "count": len(results)})
        elif source == "taoguba":
            from browser_login import (load_cookies, BrowserSession, inject_cookies, scrape_taoguba)
            ck = load_cookies("taoguba")
            with BrowserSession("taoguba", headless=True) as (ctx, page):
                if ck:
                    inject_cookies(ctx, ck)
                items = scrape_taoguba(page, name if name else code, max_count=15)
            return jsonify({"ok": True, "data": items, "count": len(items)})
        else:
            return jsonify({"ok": False, "error": f"不支持的源: {source}"})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)[:200]})


# ============================================================
# 工具 / 下载
# ============================================================

@app.route("/download/<path:filename>")
def download(filename):
    path = OUTPUT_DIR / filename
    if path.exists():
        return send_file(str(path), as_attachment=True)
    return "File not found", 404


@app.route("/api/stocks")
def api_stocks():
    docx_files = sorted(glob.glob(str(OUTPUT_DIR / "*完整分析.docx")), key=os.path.getmtime, reverse=True)
    files = []
    for f in docx_files[:100]:
        name = os.path.basename(f)
        parts = name.rsplit("_", 2)
        code = parts[-2] if len(parts) >= 2 else ""
        xlsx_name = name.replace("_完整分析.docx", "_分析.xlsx")
        has_xlsx = (OUTPUT_DIR / xlsx_name).exists()
        files.append({"name": name, "size": os.path.getsize(f) // 1024,
                      "code": code, "xlsx": xlsx_name if has_xlsx else None})
    return jsonify({"total": len(files), "files": files})


if __name__ == "__main__":
    # 启动注册已知实现（解耦具体依赖）
    try:
        registry_bootstrap()
    except Exception:
        pass

    print("=" * 50)
    print(f"{APP_NAME} v{VERSION} - 本地版 (分层架构)")
    print("=" * 50)
    print(f"数据目录: {DATA_DIR}")
    print(f"输出目录: {OUTPUT_DIR}")
    print("架构: web(app) → services → domain(core/quant/export/ai) → data")
    print("新增: /api/kline 交互式图表 | /api/annotations 实时标注")
    print("访问: http://localhost:5000")
    print("=" * 50)
    app.run(host="0.0.0.0", port=5000, debug=False, threaded=True)
