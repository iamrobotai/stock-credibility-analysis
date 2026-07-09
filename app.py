"""
股票可信度分析系统 - Flask Web 应用 v2.0
===================================
支持: 股票代码自动解析 / 多 AI 提供商 / 数据源平台选择 / 情绪帖过滤

启动: python app.py
访问: http://localhost:5000
"""
import os, sys, json, time, threading, traceback, glob
from pathlib import Path
from datetime import datetime

from flask import Flask, render_template, jsonify, request, send_file, Response

BASE_DIR = Path(__file__).parent
DATA_DIR = BASE_DIR / "data"
DATA_DIR.mkdir(exist_ok=True)
OUTPUT_DIR = BASE_DIR

app = Flask(__name__, template_folder=str(BASE_DIR / "templates"))

tasks = {}


class TaskState:
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
        if elapsed < 60:
            self.elapsed = f"{elapsed:.0f}s"
        else:
            self.elapsed = f"{elapsed/60:.1f}min"
        return {
            "status": self.status, "total": self.total, "done": self.done,
            "success": self.success, "fail": self.fail, "elapsed": self.elapsed,
            "logs": self.logs[-50:], "results": self.results, "zip": self.zip,
        }


def run_single(stock, state, use_llm=True, ai_provider=None, ai_config=None, platforms=None, filter_emotion=True):
    """单只股票全链路"""
    code = stock["code"]
    name = stock.get("name", "")
    industry = stock.get("industry", "")

    # 如果名称为空，自动解析
    if not name:
        try:
            from stock_resolver import resolve
            info = resolve(code)
            name = info.get("name", code)
            if not industry:
                industry = info.get("industry", "")
            state.log(f"[{code}] 自动解析: {name} | {industry}", "info")
        except Exception:
            name = code

    state.log(f"开始分析: {name} ({code})", "info")
    result = {"code": code, "name": name, "status": "pending", "docx": None}
    state.results.append(result)

    try:
        # Step 1: 数据采集
        plat_count = len(platforms) if platforms else 13
        state.log(f"[{name}] 采集数据 ({plat_count}平台)...", "info")
        from data_collector import collect
        collect(code, name, outdir=str(DATA_DIR),
                platforms=platforms, filter_emotion=filter_emotion)

        # 统计采集结果
        raw_path = DATA_DIR / f"{code}_raw.json"
        if raw_path.exists():
            with open(raw_path, encoding="utf-8") as f:
                raw_data = json.load(f)
            total_items = sum(len(v) for k, v in raw_data.items()
                             if isinstance(v, list) and k not in ("code", "name"))
            ok_plats = sum(1 for k, v in raw_data.items()
                          if isinstance(v, list) and v and k not in ("code", "name"))
            state.log(f"[{name}] 采集完成: {total_items} 数据点, {ok_plats} 平台", "ok")

        # Step 2: 价格分段
        state.log(f"[{name}] 价格分段...", "info")
        import segment as seg_mod
        seg_mod.run(code)
        state.log(f"[{name}] 分段完成", "ok")

        # Step 3: D1-D8 评分
        state.log(f"[{name}] D1-D9 评分...", "info")
        import score_rules as score_mod
        score_mod.run(code)
        scored_path = DATA_DIR / f"{code}_scored.json"
        ad_count = 0
        if scored_path.exists():
            with open(scored_path, encoding="utf-8") as f:
                scored_data = json.load(f)
            ad_count = sum(1 for p in scored_data.get("posts", []) if p.get("D8", {}).get("is_ad"))
            # 添加 D9 技术评分
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
        state.log(f"[{name}] 评分完成: 广告={ad_count}条", "ok")

        # Step 4: LLM 增强
        if use_llm:
            active = ai_provider or "ollama"
            state.log(f"[{name}] LLM 深度分析 ({active})...", "info")
            from llm_enhance import process_stock
            process_stock(code, provider=ai_provider, config=ai_config)
            state.log(f"[{name}] LLM 分析完成", "ok")

        # Step 5: 生成 docx + excel
        state.log(f"[{name}] 生成报告...", "info")
        from gen_docx_full import generate
        safe_name = name.replace("/", "_").replace(" ", "")
        generate(code, name, industry)
        docx_name = f"{safe_name}_{code}_完整分析.docx"
        docx_path = OUTPUT_DIR / docx_name

        # Excel 导出
        xlsx_name = None
        try:
            from gen_excel import generate as gen_xlsx
            gen_xlsx(code, name, industry)
            xlsx_name = f"{safe_name}_{code}_分析.xlsx"
            state.log(f"[{name}] Excel 已生成", "ok")
        except Exception as e:
            state.log(f"[{name}] Excel 跳过: {str(e)[:60]}", "warn")

        if docx_path.exists():
            result["status"] = "ok"
            result["docx"] = docx_name
            result["xlsx"] = xlsx_name
            result["code"] = code
            state.log(f"[{name}] 完成: {docx_name} ({docx_path.stat().st_size//1024}KB)", "ok")
            state.success += 1
        else:
            result["status"] = "fail"
            state.log(f"[{name}] docx 未生成", "fail")
            state.fail += 1

    except Exception as e:
        result["status"] = "fail"
        state.log(f"[{name}] ❌ 失败: {str(e)[:100]}", "fail")
        traceback.print_exc()
        state.fail += 1

    state.done += 1


def run_batch_task(state):
    """批量任务线程"""
    try:
        if state.payload["mode"] == "industry":
            state.log("加载 20 行业配置...", "info")
            sys.path.insert(0, str(BASE_DIR))
            from run_all_20 import INDUSTRIES
            stocks = []
            for ind in INDUSTRIES:
                for c in ind["companies"]:
                    stocks.append({"code": c["code"], "name": c["name"], "industry": ind["name"]})
            state.total = len(stocks)
            state.log(f"共 {state.total} 只股票, {len(INDUSTRIES)} 个行业", "info")
        elif state.payload["mode"] == "batch":
            stocks = state.payload["stocks"]
            state.total = len(stocks)
        else:
            stocks = [{"code": state.payload["code"],
                       "name": state.payload.get("name", ""),
                       "industry": state.payload.get("industry", "")}]
            state.total = 1

        use_llm = state.payload.get("use_llm", True)
        ai_provider = state.payload.get("ai_provider")
        ai_config = state.payload.get("ai_config")
        platforms = state.payload.get("platforms")
        filter_emotion = state.payload.get("filter_emotion", True)

        # 如果未指定 platforms，使用默认全平台
        if platforms is None:
            from data_collector import DEFAULT_PLATFORMS
            platforms = DEFAULT_PLATFORMS

        active_ai = ai_provider or "ollama"
        state.log(f"配置: AI={active_ai} | 平台={len(platforms)}个 | 情绪过滤={'是' if filter_emotion else '否'}", "info")

        for i, stock in enumerate(stocks):
            if state.stop_flag:
                state.log("用户停止", "warn")
                break
            state.log(f"[{i+1}/{state.total}] {stock.get('name', stock['code'])} ({stock['code']})", "info")
            run_single(stock, state, use_llm, ai_provider, ai_config, platforms, filter_emotion)

        # 打包 zip
        if state.success > 1:
            state.log("打包 ZIP...", "info")
            import zipfile
            zip_name = f"股票可信度分析_{datetime.now().strftime('%Y%m%d_%H%M')}.zip"
            zip_path = OUTPUT_DIR / zip_name
            with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as z:
                for r in state.results:
                    if r.get("docx"):
                        docx_path = OUTPUT_DIR / r["docx"]
                        if docx_path.exists():
                            industry = next((s.get("industry", "other") for s in stocks if s["code"] == r["code"]), "other")
                            z.write(docx_path, f"{industry}/{r['docx']}")
                    if r.get("xlsx"):
                        xlsx_path = OUTPUT_DIR / r["xlsx"]
                        if xlsx_path.exists():
                            industry = next((s.get("industry", "other") for s in stocks if s["code"] == r["code"]), "other")
                            z.write(xlsx_path, f"{industry}/{r['xlsx']}")
            state.zip = zip_name
            state.log(f"ZIP 完成: {zip_name} ({zip_path.stat().st_size//1024//1024}MB)", "ok")

        state.status = "completed"
        state.log(f"全部完成! 成功 {state.success} / 失败 {state.fail} / 耗时 {state.elapsed}", "ok")

    except Exception as e:
        state.status = "completed"
        state.log(f"任务异常: {str(e)[:200]}", "fail")
        traceback.print_exc()


# ── API 路由 ──

@app.route("/")
def index():
    return render_template("index.html")


@app.route("/api/hot")
def api_hot():
    """获取实时热门股票与行业 (简化版，无线程嵌套)"""
    try:
        from hot_stocks import get_all_hot
        data = get_all_hot()
        return jsonify({"ok": True, "data": data})
    except Exception as e:
        return jsonify({
            "ok": True,
            "data": {
                "stocks": [],
                "industries": [],
                "concepts": [],
                "update_time": f"API限流: {str(e)[:40]}",
            }
        })


@app.route("/api/resolve/<code>")
def api_resolve(code):
    """股票代码自动解析 → {name, industry}"""
    try:
        from stock_resolver import resolve
        info = resolve(code)
        return jsonify({"ok": True, "data": info})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)[:200]})


@app.route("/api/platforms")
def api_platforms():
    """获取数据源平台列表"""
    from data_collector import get_platform_list, DEFAULT_PLATFORMS, HIGH_VALUE_PLATFORMS
    return jsonify({
        "platforms": get_platform_list(),
        "default": DEFAULT_PLATFORMS,
        "high_value": HIGH_VALUE_PLATFORMS,
    })


@app.route("/api/ai/providers")
def ai_providers():
    """获取 AI 提供商列表"""
    from ai_provider import list_providers
    return jsonify({"providers": list_providers()})


@app.route("/api/ai/config", methods=["GET", "POST"])
def ai_config():
    """获取/设置 AI 配置"""
    from ai_provider import load_config, save_config
    if request.method == "GET":
        cfg = load_config()
        # 隐藏 api_key 只返回是否已设置
        safe = {"active_provider": cfg.get("active_provider"), "providers": {}}
        for k, v in cfg.get("providers", {}).items():
            safe["providers"][k] = {
                "model": v.get("model", ""),
                "label": v.get("label", k),
                "has_key": bool(v.get("api_key")),
                "needs_key": k != "ollama",
                "url": v.get("url", ""),
            }
        return jsonify(safe)

    # POST: 更新配置
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
    """测试 AI 提供商连通性"""
    from ai_provider import test_provider
    data = request.json or {}
    provider = data.get("provider")
    result = test_provider(provider)
    return jsonify(result)


@app.route("/api/run", methods=["POST"])
def api_run():
    payload = request.json
    run_id = f"run_{datetime.now().strftime('%Y%m%d%H%M%S')}"
    state = TaskState(run_id, payload)
    tasks[run_id] = state
    thread = threading.Thread(target=run_batch_task, args=(state,), daemon=True)
    thread.start()
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
        # Extract code from filename
        parts = name.rsplit("_", 2)
        code = parts[-2] if len(parts) >= 2 else ""
        xlsx_name = name.replace("_完整分析.docx", "_分析.xlsx")
        has_xlsx = (OUTPUT_DIR / xlsx_name).exists()
        files.append({
            "name": name, "size": os.path.getsize(f) // 1024,
            "code": code, "xlsx": xlsx_name if has_xlsx else None,
        })
    return jsonify({"total": len(files), "files": files})


@app.route("/api/preview/<code>")
def api_preview(code):
    """结构化预览数据，前端渲染为 HTML"""
    try:
        raw_path = DATA_DIR / f"{code}_raw.json"
        scored_path = DATA_DIR / f"{code}_scored.json"
        llm_path = DATA_DIR / f"{code}_llm.json"

        if not raw_path.exists():
            return jsonify({"ok": False, "error": f"无 {code} 的数据，请先运行分析"})

        raw = json.load(open(raw_path, encoding="utf-8"))
        scored = json.load(open(scored_path, encoding="utf-8")) if scored_path.exists() else {"posts": [], "segments": []}
        llm_data = json.load(open(llm_path, encoding="utf-8")) if llm_path.exists() else {}

        kline = raw.get("kline", [])
        segments = scored.get("segments", [])
        posts = scored.get("posts", [])
        financials = raw.get("financials", [])
        news = raw.get("news", [])
        reports = raw.get("reports", [])

        # K线摘要
        kline_summary = {}
        if kline:
            last = kline[-1]
            first = kline[0]
            total_ret = (last["close"] - first["close"]) / first["close"] * 100
            highs = [b["high"] for b in kline]
            lows = [b["low"] for b in kline]
            # 计算日涨跌幅 >5% 的天数
            big_days = 0
            for i in range(1, len(kline)):
                prev = kline[i - 1]["close"]
                curr = kline[i]["close"]
                if prev > 0 and abs((curr - prev) / prev * 100) >= 5:
                    big_days += 1
            kline_summary = {
                "start_date": first["date"], "end_date": last["date"],
                "total_bars": len(kline), "total_return": round(total_ret, 1),
                "max_high": round(max(highs), 2), "min_low": round(min(lows), 2),
                "last_close": round(last["close"], 2),
                "big_move_days": big_days,
            }

        # 来源可信度均值
        by_type = {}
        for p in posts:
            t = p.get("source_type", "?")
            by_type.setdefault(t, []).append(p.get("avg_d", 0))
        source_avg = {t: round(sum(s) / len(s), 2) for t, s in by_type.items()}

        # 广告帖
        ads = [p for p in posts if p.get("D8", {}).get("is_ad")]

        # LLM 分析
        llm_analysis = None
        if llm_data.get("success") and llm_data.get("analysis"):
            llm_analysis = llm_data["analysis"]
            llm_analysis["stats"] = llm_data.get("stats", {})

        return jsonify({
            "ok": True,
            "data": {
                "code": code,
                "name": raw.get("name", code),
                "stock_url": raw.get("stock_url", ""),
                "guba_url": raw.get("guba_url", ""),
                "kline_summary": kline_summary,
                "segments": segments,
                "posts": posts[:50],
                "posts_total": len(posts),
                "source_avg": source_avg,
                "ads": ads[:10],
                "ads_total": len(ads),
                "news": news[:15],
                "reports": reports[:10],
                "financials": financials[:15],
                "llm": llm_analysis,
                "has_chart": (DATA_DIR / f"{code}_chart.png").exists(),
            }
        })
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)[:200]})


@app.route("/api/chart/<code>")
def api_chart(code):
    """返回图表 PNG"""
    # 先尝试已有图表
    chart_path = DATA_DIR / f"{code}_chart.png"
    if not chart_path.exists():
        # 动态生成
        raw_path = DATA_DIR / f"{code}_raw.json"
        seg_path = DATA_DIR / f"{code}_segments.json"
        if raw_path.exists():
            raw = json.load(open(raw_path, encoding="utf-8"))
            segs = json.load(open(seg_path, encoding="utf-8")) if seg_path.exists() else []
            try:
                from chart_gen import gen_stock_chart
                gen_stock_chart(code, raw.get("kline", []), segs, outdir=str(DATA_DIR))
            except Exception:
                pass
    if chart_path.exists():
        return send_file(str(chart_path), mimetype="image/png")
    return "Chart not found", 404


@app.route("/api/export/excel/<code>")
def api_export_excel(code):
    """生成并下载 Excel"""
    try:
        from gen_excel import generate as gen_xlsx
        # 从 scored 或 raw 获取名称
        name = code
        industry = ""
        scored_path = DATA_DIR / f"{code}_scored.json"
        raw_path = DATA_DIR / f"{code}_raw.json"
        if raw_path.exists():
            raw = json.load(open(raw_path, encoding="utf-8"))
            name = raw.get("name", code)
        path = gen_xlsx(code, name, industry)
        if path and os.path.exists(path):
            return send_file(path, as_attachment=True, download_name=os.path.basename(path))
        return jsonify({"ok": False, "error": "Excel 生成失败"}), 500
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)[:200]}), 500


@app.route("/api/industry/chart", methods=["POST"])
def api_industry_chart():
    """行业多股走势叠加图"""
    try:
        data = request.json or {}
        industry_name = data.get("industry", "行业对比")
        stock_codes = data.get("codes", [])

        if not stock_codes:
            return jsonify({"ok": False, "error": "请提供股票代码列表"})

        stocks_data = []
        for code in stock_codes:
            raw_path = DATA_DIR / f"{code}_raw.json"
            if raw_path.exists():
                raw = json.load(open(raw_path, encoding="utf-8"))
                stocks_data.append({
                    "code": code,
                    "name": raw.get("name", code),
                    "kline": raw.get("kline", []),
                })

        if not stocks_data:
            return jsonify({"ok": False, "error": "无可用数据，请先运行分析"})

        from chart_gen import gen_industry_chart
        path = gen_industry_chart(stocks_data, industry_name, outdir=str(DATA_DIR))
        if path:
            safe_name = industry_name.replace("/", "_").replace(" ", "")
            return jsonify({"ok": True, "chart": f"industry_{safe_name}_chart.png"})
        return jsonify({"ok": False, "error": "图表生成失败"})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)[:200]})


@app.route("/api/industry/preview")
def api_industry_preview():
    """行业对比预览：返回所有已分析股票列表"""
    try:
        # 扫描 data 目录中的 raw 文件
        raw_files = sorted(DATA_DIR.glob("*_raw.json"), key=os.path.getmtime, reverse=True)
        stocks = []
        for f in raw_files[:200]:
            code = f.stem.replace("_raw", "")
            try:
                raw = json.load(open(f, encoding="utf-8"))
                kline = raw.get("kline", [])
                if kline:
                    stocks.append({
                        "code": code,
                        "name": raw.get("name", code),
                        "last_close": kline[-1]["close"],
                        "total_return": round((kline[-1]["close"] - kline[0]["close"]) / kline[0]["close"] * 100, 1),
                    })
            except Exception:
                continue
        return jsonify({"ok": True, "stocks": stocks})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)[:200]})


@app.route("/api/technical/<code>")
def api_technical(code):
    """获取技术指标数据"""
    try:
        raw_path = DATA_DIR / f"{code}_raw.json"
        if not raw_path.exists():
            return jsonify({"ok": False, "error": "无数据"})
        raw = json.load(open(raw_path, encoding="utf-8"))
        kline = raw.get("kline", [])
        if not kline:
            return jsonify({"ok": False, "error": "无K线数据"})
        from technical import (
            compute_macd, compute_kdj, compute_rsi, compute_boll,
            compute_cci, compute_wr, compute_atr, compute_technical_score,
            detect_patterns,
        )
        closes = [b["close"] for b in kline]
        highs = [b["high"] for b in kline]
        lows = [b["low"] for b in kline]
        volumes = [b.get("volume", 0) for b in kline]

        # 趋势 (最近50根K线)
        tail = min(100, len(kline))
        kline_tail = kline[-tail:]
        closes_tail = closes[-tail:]

        indicators = {
            "MACD": compute_macd(closes_tail),
            "KDJ": compute_kdj(highs[-tail:], lows[-tail:], closes_tail),
            "RSI": compute_rsi(closes_tail),
            "BOLL": compute_boll(closes_tail),
            "CCI": compute_cci(highs[-tail:], lows[-tail:], closes_tail) if len(closes_tail) >= 14 else None,
            "WR": compute_wr(highs[-tail:], lows[-tail:], closes_tail) if len(closes_tail) >= 10 else None,
            "ATR": compute_atr(highs[-tail:], lows[-tail:], closes_tail) if len(closes_tail) >= 14 else None,
        }
        patterns = detect_patterns(kline_tail)
        recent_patterns = [p for p in patterns if p["index"] >= len(kline_tail) - 20]
        d9 = compute_technical_score(kline_tail)

        return jsonify({
            "ok": True,
            "data": {
                "indicators": indicators,
                "patterns_total": len(patterns),
                "recent_patterns": recent_patterns[-15:],
                "d9_score": d9,
            }
        })
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)[:200]})


if __name__ == "__main__":
    print("=" * 50)
    print("股票可信度分析系统 v2.4 - 本地版")
    print("=" * 50)
    print(f"数据目录: {DATA_DIR}")
    print(f"输出目录: {OUTPUT_DIR}")
    print()
    print("新功能:")
    print("  - 14种技术指标 (MACD/KDJ/RSI/BOLL/CCI/WR/ATR等)")
    print("  - 50+K线形态识别 (锤头/吞噬/晨星/三白兵等)")
    print("  - D9 技术信号评分 (综合指标+形态)")
    print("  - 在线预览（6 Tab + 技术指标异步加载）")
    print()
    print("访问: http://localhost:5000")
    print("=" * 50)
    app.run(host="0.0.0.0", port=5000, debug=False, threaded=True)
