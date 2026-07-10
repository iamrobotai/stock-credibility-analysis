# -*- coding: utf-8 -*-
"""
pipeline.py — 本地全链路编排器（零 agent token）
用法: python pipeline.py <config.json>
config 格式:
{
  "industry": "半导体设备",
  "fmatrix": {"F1":"...","F1_c":"🟡", ...},   // 可选, 行业级 F 矩阵
  "companies": [
    {"code":"002371", "name":"北方华创"},
    ...
  ]
}
流程: collect → segment → score → gen_docx (每只股票)
"""
import json, os, sys, time, traceback

from data_collector import collect
from segment import run as run_segment
from score_rules import run as run_score
from gen_docx_full import generate as gen_docx


def process_stock(code, name, industry, fmatrix):
    """处理单只股票：采集→分段→评分→生成docx"""
    print(f"\n{'='*60}")
    print(f"  {name}({code}) — {industry}")
    print(f"{'='*60}")

    # 1. 采集
    try:
        collect(code, name)
    except Exception as e:
        print(f"  [COLLECT] FAIL: {e}")
        traceback.print_exc()
        return None

    # 2. 分段
    try:
        run_segment(code)
    except Exception as e:
        print(f"  [SEGMENT] FAIL: {e}")

    # 3. 评分
    try:
        run_score(code)
    except Exception as e:
        print(f"  [SCORE] FAIL: {e}")

    # 4. 生成 docx
    try:
        path = gen_docx(code, name, industry, fmatrix)
        return path
    except Exception as e:
        print(f"  [DOCX] FAIL: {e}")
        traceback.print_exc()
        return None


def main():
    if len(sys.argv) < 2:
        print("用法: python pipeline.py <config.json>")
        sys.exit(1)

    cfg_path = sys.argv[1]
    cfg = json.load(open(cfg_path, encoding="utf-8"))
    industry = cfg.get("industry", "未命名")
    fmatrix = cfg.get("fmatrix", {})
    companies = cfg.get("companies", [])

    print(f"\n{'#'*60}")
    print(f"# 行业: {industry}")
    print(f"# 公司数: {len(companies)}")
    print(f"# F矩阵: {'有' if fmatrix else '无'}")
    print(f"{'#'*60}")

    results = []
    t0 = time.time()

    for i, c in enumerate(companies):
        code = c["code"]
        name = c["name"]
        print(f"\n[{i+1}/{len(companies)}] {name}({code})")
        path = process_stock(code, name, industry, fmatrix)
        results.append({"code": code, "name": name, "docx": path,
                        "status": "OK" if path else "FAIL"})
        time.sleep(1)  # 礼貌延迟

    elapsed = time.time() - t0
    ok = sum(1 for r in results if r["status"] == "OK")
    fail = len(results) - ok

    print(f"\n{'='*60}")
    print(f"  完成: {ok} 成功 / {fail} 失败 / 共 {len(results)}")
    print(f"  耗时: {elapsed:.0f}s ({elapsed/len(results):.1f}s/股)")
    print(f"{'='*60}")

    # 汇总
    summary_path = os.path.join(os.path.dirname(cfg_path),
                                f"pipeline_{industry}_summary.json")
    with open(summary_path, "w", encoding="utf-8") as f:
        json.dump({"industry": industry, "elapsed": elapsed,
                   "results": results}, f, ensure_ascii=False, indent=2)
    print(f"  汇总: {summary_path}")

    return results


if __name__ == "__main__":
    main()
