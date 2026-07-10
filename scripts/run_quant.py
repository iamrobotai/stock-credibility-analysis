#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
scripts/run_quant.py — 量化分析一键执行
=======================================
用法:
  # 全量 176 只(回测 + 量化资金识别),结果写 output/quant/
  python scripts/run_quant.py --all

  # 指定个股 + 指定策略
  python scripts/run_quant.py --codes 000021 300308 --strategies trend,meanrev

  # 仅量化资金识别(跳过回测)
  python scripts/run_quant.py --codes 000021 --no-backtest

  # 打印某股三维结论(JSON)
  python scripts/run_quant.py --codes 000021 --print
"""
import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from quant import engine as QE  # noqa: E402


def main():
    ap = argparse.ArgumentParser(description="A股量化分析(回测+量化资金识别)")
    ap.add_argument("--all", action="store_true", help="全量 176 只")
    ap.add_argument("--codes", nargs="*", help="指定股票代码列表")
    ap.add_argument("--strategies", default=None,
                    help="逗号分隔策略: trend,meanrev,momentum,pairs,statarb")
    ap.add_argument("--no-backtest", action="store_true", help="仅做量化资金识别")
    ap.add_argument("--print", dest="do_print", action="store_true",
                    help="打印单股结果(JSON)")
    ap.add_argument("--out", default=None, help="输出目录(默认 output/quant)")
    args = ap.parse_args()

    if args.no_backtest:
        strats = []  # 空策略列表 -> 只跑识别
    elif args.strategies:
        strats = args.strategies.split(",")
    else:
        strats = None  # None -> engine 使用默认 5 策略

    if args.all:
        codes = None
    else:
        codes = args.codes
        if not codes:
            print("请指定 --all 或 --codes；或 --help 查看用法")
            return 1

    print(f"[run_quant] 启动 | 策略={strats or '仅识别'}"
          f" | 范围={'全量' if codes is None else codes}")
    result = QE.run_all(strat_names=strats, out_dir=args.out, codes=codes)

    ov = result["overview"]
    print(f"\n=== 概览 ===")
    print(f"  处理: {ov['total']} 只 | 错误: {ov['errors']}")
    print(f"  散户主导: {ov['retail_dominated_count']} 只")
    print(f"  量化评分 TOP10:")
    for r in ov["quant_top10"][:10]:
        print(f"    {r['code']} {r['name']:<8} 量化={r['quant_score']:>5} "
              f"散户={r['retail_score']:>5} | {r['suspected_type']}")

    if args.do_print and codes:
        for c in codes:
            r = result["per_stock"].get(c)
            if r:
                print(f"\n===== {c} {r.get('name','')} =====")
                print(json.dumps(r, ensure_ascii=False, indent=2)[:4000])
    print(f"\n结果已写入: {QE.OUT_DIR}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
