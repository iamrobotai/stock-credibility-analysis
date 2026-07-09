"""
LLM 增强模块 v2.0 — 多 AI 提供商支持
通过 ai_provider.py 抽象层调用不同 AI (ollama/deepseek/qwen/openai/zhipu)

输入: data/{code}_raw.json + data/{code}_scored.json
输出: data/{code}_llm.json (结构化深度分析)

用法:
  python llm_enhance.py <code>                          # 使用默认 provider
  python llm_enhance.py <code> --provider deepseek      # 指定 provider
  python llm_enhance.py --batch                          # 批量处理
"""
import json, os, re, time, sys
from pathlib import Path

from ai_provider import call_ai, load_config, get_active_provider

DATA_DIR = Path(__file__).parent / "data"
SYSTEM_MSG = "你是专业股票分析API。只返回JSON对象,不要输出任何其他文字。"


def load_json(path):
    if not path.exists():
        return None
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def build_summary(code, raw, scored):
    """构建紧凑的股票数据摘要供 LLM 分析"""
    parts = []
    parts.append(f"股票: {code} {raw.get('name', code)}")

    # 分段
    segs = scored.get("segments", [])
    if segs:
        seg_lines = []
        for s in segs:
            pct = s.get("pct", 0)
            direction = "涨" if pct >= 0 else "跌"
            seg_lines.append(f"  {s.get('start_date','?')}~{s.get('end_date','?')}: {direction}{abs(pct):.1f}%")
        parts.append(f"价格分段({len(segs)}段):\n" + "\n".join(seg_lines))

    # 帖子/新闻/研报摘要 (前15条, 按可信度排序)
    posts = scored.get("posts", [])
    if posts:
        post_lines = []
        for p in posts[:15]:
            title = str(p.get("title", ""))[:50]
            src = str(p.get("source_type", ""))[:8]
            avg_d = p.get("avg_d", "")
            post_lines.append(f"  [{src}] D={avg_d} | {title}")
        parts.append(f"信息源({len(posts)}条,展示前15):\n" + "\n".join(post_lines))

    # 研报摘要 (前5份)
    reports = raw.get("reports", [])
    if reports:
        rep_lines = []
        for r in reports[:5]:
            org = str(r.get("org", ""))[:10]
            rating = r.get("rating", "")
            eps = r.get("eps_2026", "")
            pe = r.get("pe_2026", "")
            rep_lines.append(f"  {org}|评级={rating} EPS26={eps} PE26={pe}")
        parts.append(f"机构研报({len(reports)}份,展示前5):\n" + "\n".join(rep_lines))

    # 公告摘要 (前3条)
    cninfo = raw.get("cninfo", [])
    if cninfo:
        cn_lines = []
        for c in cninfo[:3]:
            cn_lines.append(f"  {c.get('date','')[:10]} | {str(c.get('title',''))[:50]}")
        parts.append(f"官方公告({len(cninfo)}条,展示前3):\n" + "\n".join(cn_lines))

    # 互动易摘要 (前3条)
    ir = raw.get("ir", [])
    if ir:
        ir_lines = []
        for i in ir[:3]:
            q = str(i.get("question", ""))[:40]
            ir_lines.append(f"  Q: {q}")
        parts.append(f"互动易问答({len(ir)}条,展示前3):\n" + "\n".join(ir_lines))

    # 新闻摘要 (前3条)
    news = raw.get("news", [])
    if news:
        news_lines = []
        for n in news[:3]:
            news_lines.append(f"  {n.get('time','')[:10]} {n.get('source','')[:8]} | {n.get('title','')[:50]}")
        parts.append(f"新闻({len(news)}条,展示前3):\n" + "\n".join(news_lines))

    # D8 广告帖统计
    ads = [p for p in posts if p.get("D8", {}).get("is_ad")]
    if ads:
        parts.append(f"广告检测: {len(ads)}条疑似广告/喊单帖")

    return "\n".join(parts)


def analyze_stock(code, raw, scored, provider=None, config=None):
    """LLM 深度分析单只股票"""
    summary = build_summary(code, raw, scored)

    user_msg = f"""{summary}

返回JSON,包含字段:
- overall_assessment: 总体可信度评价(80-100字,涵盖信息质量/预测准确性/市场情绪)
- key_risks: 数组,3条关键风险(每条15字内)
- catalysts: 数组,3条催化剂(每条15字内)
- ad_warning: 广告/喊单警示(20字,无广告则填'未检测到明显广告行为')
- investor_advice: 投资者注意建议(30字内,非投资建议)
- d1_source: 信息来源可信度(15字)
- d2_facts: 事实核查情况(15字)
- d3_predictions: 预测具体性(15字)
- d4_timing: 时间框架(15字)
- d5_reasoning: 推理质量(15字)
- d6_consensus: 共识偏离度(15字)
- d7_emotion: 情绪偏置(15字)
- d8_ads: 广告甄别总结(15字)"""

    messages = [
        {"role": "system", "content": SYSTEM_MSG},
        {"role": "user", "content": user_msg},
    ]

    try:
        content, stats = call_ai(
            messages, provider=provider, config=config,
            max_tokens=600, format_json=True, temperature=0.2, timeout=120,
        )
    except Exception as e:
        return {"raw_response": str(e)[:500], "stats": {}, "analysis": None,
                "success": False, "error": str(e)[:200]}

    active = provider or get_active_provider()
    result = {"raw_response": content[:500], "stats": stats,
              "provider": active, "model": stats.get("model", "")}

    try:
        parsed = json.loads(content)
        result["analysis"] = parsed
        result["success"] = True
    except json.JSONDecodeError:
        match = re.search(r'\{.*\}', content, re.DOTALL)
        if match:
            try:
                parsed = json.loads(match.group())
                result["analysis"] = parsed
                result["success"] = True
            except Exception:
                result["analysis"] = None
                result["success"] = False
                result["error"] = "JSON parse failed"
        else:
            result["analysis"] = None
            result["success"] = False
            result["error"] = "No JSON found"

    return result


def process_stock(code, provider=None, config=None):
    """处理单只股票"""
    raw = load_json(DATA_DIR / f"{code}_raw.json")
    scored = load_json(DATA_DIR / f"{code}_scored.json")
    if not raw or not scored:
        return False, f"数据缺失: raw={raw is not None} scored={scored is not None}"

    result = analyze_stock(code, raw, scored, provider=provider, config=config)
    out_path = DATA_DIR / f"{code}_llm.json"
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)

    status = "✅" if result["success"] else "❌"
    name = raw.get("name", code)
    dur = result.get("stats", {}).get("duration_s", 0)
    tps = result.get("stats", {}).get("tps", 0)
    model = result.get("model", "")
    print(f"  {status} {name}_{code} | {model} | {dur:.1f}s {tps:.0f}tok/s")
    return result["success"], result.get("error", "")


def batch_process(provider=None, config=None):
    """批量处理所有已有 scored 的股票"""
    scored_files = sorted(DATA_DIR.glob("*_scored.json"))
    codes = [f.stem.replace("_scored", "") for f in scored_files]
    todo = []
    for code in codes:
        llm_path = DATA_DIR / f"{code}_llm.json"
        if llm_path.exists():
            existing = load_json(llm_path)
            if existing and existing.get("success"):
                continue
        todo.append(code)

    active = provider or get_active_provider()
    cfg = config or load_config()
    model = cfg.get("providers", {}).get(active, {}).get("model", "?")
    print(f"总计 {len(codes)} 只, 待处理 {len(todo)} 只 (跳过 {len(codes)-len(todo)} 只已完成)")
    print(f"AI: {active} / {model}")
    print("=" * 60)

    ok, fail = 0, 0
    t0 = time.time()
    for i, code in enumerate(todo):
        success, err = process_stock(code, provider=provider, config=config)
        if success:
            ok += 1
        else:
            fail += 1
            if err:
                print(f"    err: {err}")
        if (i + 1) % 20 == 0:
            elapsed = time.time() - t0
            rate = (i + 1) / elapsed
            eta = (len(todo) - i - 1) / rate
            print(f"  --- 进度 {i+1}/{len(todo)} | {elapsed:.0f}s | ETA {eta:.0f}s ---")

    elapsed = time.time() - t0
    print("=" * 60)
    print(f"完成: {ok} 成功 / {fail} 失败 / {len(todo)} 总计 | 耗时 {elapsed:.0f}s ({elapsed/60:.1f}min)")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("用法: python llm_enhance.py <code> [--provider <name>]")
        print("      python llm_enhance.py --batch [--provider <name>]")
        print(f"当前 provider: {get_active_provider()}")
        sys.exit(1)

    # 解析 --provider 参数
    provider = None
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    if "--provider" in sys.argv:
        idx = sys.argv.index("--provider")
        if idx + 1 < len(sys.argv):
            provider = sys.argv[idx + 1]

    if sys.argv[1] == "--batch":
        batch_process(provider=provider)
    else:
        for code in args:
            process_stock(code, provider=provider)
