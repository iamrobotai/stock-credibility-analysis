# -*- coding: utf-8 -*-
"""M7 终验：boot + 契约注册 + 路由 + 真实数据 analyze/persist。"""
import json
import sys
from pathlib import Path

PROJ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJ))
# 确保 core/quant 等子目录可导入（与 app.py 启动逻辑一致）
for _s in ["core", "ai", "export", "scripts"]:
    _p = PROJ / _s
    if _p.exists():
        sys.path.insert(0, str(_p))

CODE = "000021"

ok = True
def check(label, cond, extra=""):
    global ok
    mark = "✅" if cond else "❌"
    if not cond:
        ok = False
    print(f"{mark} {label}{('  ' + extra) if extra else ''}")

# 1) 导入 app（触发 services.credibility_service 模块级 bootstrap）
import app
check("import app 成功", True)

from common.registry import names
tf_names = names("TimeframeAnalyzer")
ci_names = names("CredibilityIntegrator")
check("TimeframeAnalyzer 已注册", bool(tf_names), f"names={tf_names}")
check("CredibilityIntegrator 已注册", bool(ci_names), f"names={ci_names}")

# 2) 新路由存在
rules = {str(r) for r in app.app.url_map.iter_rules()}
check("/api/quant/timeframe/<code> 路由存在",
      any("<code>" in r and "quant/timeframe" in r for r in rules))
check("/api/credibility/<code> 路由存在",
      any("<code>" in r and "credibility" in r and "quant" not in r for r in rules))

# 3) 通过 Flask test_client 调用路由
client = app.app.test_client()
r1 = client.get(f"/api/quant/timeframe/{CODE}")
check("GET /api/quant/timeframe 返回 200", r1.status_code == 200,
      f"status={r1.status_code}")
if r1.status_code == 200:
    j1 = r1.get_json()
    tf = j1.get("timeframe_analysis") if isinstance(j1, dict) else None
    has_tf = isinstance(tf, dict) and "composite_quant_score" in tf
    check("  含 composite_quant_score", has_tf,
          f"score={tf.get('composite_quant_score') if isinstance(tf, dict) else None}")

r2 = client.get(f"/api/credibility/{CODE}")
check("GET /api/credibility 返回 200", r2.status_code == 200,
      f"status={r2.status_code}")
if r2.status_code == 200:
    j2 = r2.get_json()
    comp = j2.get("comprehensive") if isinstance(j2, dict) else None
    has_comp = isinstance(comp, dict) and "comprehensive_score" in comp
    check("  含 comprehensive_score", has_comp,
          f"score={comp.get('comprehensive_score') if isinstance(comp, dict) else None}")

# 4) 真实数据 analyze + persist
from services import credibility_service as cs
res = cs.analyze(CODE)
check("credibility_service.analyze 成功", res.get("ok"), str(res.get("error", "")))
if res.get("ok"):
    comp = res["comprehensive"]
    check("  comprehensive.grade 存在", bool(comp.get("grade")), comp.get("grade"))
    score = comp.get("comprehensive_score")
    check("  comprehensive_score ∈ [1,99]", isinstance(score, (int, float)) and 1 <= score <= 99,
          f"score={score}")
    tf = res["timeframe_analysis"]
    check("  timeframe_analysis 含 day/week/month",
          all(k in tf.get("timeframes", {}) for k in ("day", "week", "month")))

p = cs.persist(CODE, res)
check("persist 写入成功", p)

# 5) 校验 scored.json 持久化结构
sp = PROJ / "data" / f"{CODE}_scored.json"
data = json.load(open(sp, encoding="utf-8"))
check("scored.json 含 D10_quant", "D10_quant" in data,
      f"D10_quant={data.get('D10_quant')}")
check("scored.json 含 credibility 块", "credibility" in data)
if "credibility" in data:
    cb = data["credibility"]
    check("  credibility 含 comprehensive", "comprehensive" in cb)
    check("  credibility 含 timeframe_analysis", "timeframe_analysis" in cb)

print("\n" + ("FINAL OK ✅" if ok else "FINAL FAIL ❌"))
sys.exit(0 if ok else 1)
