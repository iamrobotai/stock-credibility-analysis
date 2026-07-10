"""
quant/engine.py — 编排引擎
=========================
串联: 加载 raw.json → 构建特征 → 5 策略回测 → 量化资金识别 → 三维结论。
支持:
  - 行业 peer 构建(供配对交易/统计套利使用,来自 configs/config_full_*.json)
  - 单股 run_stock / 全量 run_all(176 只)
  - 输出 JSON 可序列化结果,写入 output/quant/

三维结论:
  维度一(数据导向): 策略绩效 + 量化资金识别 + 散户主导
  维度二(公司前景长期): 业绩增速 / 研报评级 / 新闻情绪
  维度三("股票市场赚了谁的钱"): 主体定位
"""

from __future__ import annotations

import glob
import json
import os
from pathlib import Path

import numpy as np
import pandas as pd

from . import features as F
from . import strategies as S
from . import backtest as BT
from . import quant_fund_id as QID
from . import risk as RK
from . import position as POS

__all__ = ["run_stock", "run_all", "build_peer_averages", "load_peer_map", "DATA_DIR"]

BASE_DIR = Path(__file__).resolve().parents[1]
DATA_DIR = BASE_DIR / "data"
CONFIG_DIR = BASE_DIR / "configs"
OUT_DIR = BASE_DIR / "output" / "quant"

DEFAULT_STRATS = ["trend", "meanrev", "momentum", "pairs", "statarb"]


# --------------------------------------------------------------------------- #
#  数据加载 & peer 构建
# --------------------------------------------------------------------------- #
def _load_raw(code: str) -> dict | None:
    p = DATA_DIR / f"{code}_raw.json"
    if not p.exists():
        return None
    try:
        return json.load(open(p, encoding="utf-8"))
    except Exception:
        return None


def load_peer_map() -> dict:
    """从 configs/config_full_*.json 构建 code -> 同行业其他 code 列表。"""
    pm = {}
    for f in glob.glob(str(CONFIG_DIR / "config_full_*.json")):
        try:
            d = json.load(open(f, encoding="utf-8"))
        except Exception:
            continue
        codes = [c.get("code") for c in (d.get("companies") or []) if c.get("code")]
        for c in codes:
            pm.setdefault(c, [])
            pm[c] += [x for x in codes if x != c]
    # 去重
    for k in pm:
        pm[k] = list(dict.fromkeys(pm[k]))
    return pm


def build_peer_averages(peer_map: dict) -> dict:
    """
    一次性加载所有 kline,计算每只股票在同行业 peer 上的平均收盘价序列。
    返回 {code: pd.Series(index=date, value=peer_avg_close)}。
    """
    closes = {}
    for code in peer_map:
        raw = _load_raw(code)
        if not raw:
            continue
        kf = F.load_kline(raw)
        if kf.empty:
            continue
        closes[code] = kf.set_index("date")["close"]
    avg = {}
    for code, peers in peer_map.items():
        if code not in closes:
            continue
        series = [closes[p] for p in peers if p in closes]
        if not series:
            continue
        df = pd.concat(series, axis=1)
        avg[code] = df.mean(axis=1)
    return avg


# --------------------------------------------------------------------------- #
#  单股分析
# --------------------------------------------------------------------------- #
def run_stock(code: str, raw: dict | None = None, peer_avg: dict | None = None,
              strat_names: list | None = None) -> dict:
    raw = raw or _load_raw(code)
    if not raw:
        return {"code": code, "error": "raw.json 不存在"}
    feat = F.build_feature_frame(raw)
    if feat.empty or "close" not in feat.columns:
        return {"code": code, "name": raw.get("name", ""), "error": "无行情数据"}

    name = raw.get("name", "")
    close = feat["close"]
    dates = feat["date"]
    strat_names = strat_names or DEFAULT_STRATS

    peer = None
    if peer_avg and code in peer_avg:
        peer = peer_avg[code].reindex(feat["date"]).interpolate().ffill().bfill()
        if peer.notna().sum() == 0:
            peer = None
    peer_provided = peer is not None
    ctx = {"peer": peer}

    strategies = {}
    for nm in strat_names:
        try:
            strategies[nm] = S.get_strategy(nm)
        except KeyError:
            continue

    strat_results = {}
    for nm, strat in strategies.items():
        sig = strat.signal(feat, ctx)
        if sig is None:
            if strat.needs_peer and not peer_provided:
                reason = "需行业 peer(缺失)"
            elif strat.needs_peer:
                reason = "有 peer 但无有效背离信号(价差平稳)"
            else:
                reason = "数据不足"
            strat_results[nm] = {"skipped": True, "reason": reason,
                                  "label": strat.label}
            continue
        allow_short = bool(strat.needs_peer)
        res = BT.backtest(close, sig, allow_short=allow_short,
                          label=strat.label, dates=list(dates))
        d = res.to_dict()
        d["skipped"] = False
        d["category"] = strat.category
        strat_results[nm] = d

    qid = QID.identify(raw, feat)
    # 风控 + 持仓(基于最优策略)
    risk_info, pos_info = _analyze_risk_position(strat_results, qid, feat)
    three = _build_three(strat_results, qid, raw, feat, pos_info)

    return {
        "code": code,
        "name": name,
        "n_days": int(len(feat)),
        "date_start": str(dates.iloc[0]) if len(dates) else "",
        "date_end": str(dates.iloc[-1]) if len(dates) else "",
        "strategies": strat_results,
        "quant_fund": qid,
        "risk": risk_info,
        "position": pos_info,
        "three_dimensions": three,
        "data_dimensions": _build_data_dimensions(raw),
        "peer_used": peer is not None,
    }


# --------------------------------------------------------------------------- #
#  风控 + 持仓(基于最优策略)
# --------------------------------------------------------------------------- #
def _analyze_risk_position(strat_results: dict, qid: dict, feat: pd.DataFrame):
    best_nm = _best_strategy_name(strat_results)
    if not best_nm:
        return None, None
    b = strat_results[best_nm]
    if b.get("skipped") or not b.get("returns"):
        return None, None
    bret = b["returns"]
    bpos = b.get("positions") or []
    bbench = b.get("bench_returns") or None
    close_list = list(feat["close"].values) if not feat.empty else None
    risk_info = RK.analyze_both(bret, bbench, close_list)
    pos_info = POS.analyze(bpos, bret, qid)
    return risk_info, pos_info


def _best_strategy_name(strat_results: dict):
    best_nm, best_sh = None, -1e9
    for nm, r in strat_results.items():
        if r.get("skipped"):
            continue
        sh = r.get("metrics", {}).get("sharpe", -1e9)
        if sh > best_sh:
            best_sh, best_nm = sh, nm
    return best_nm


# --------------------------------------------------------------------------- #
#  三维结论
# --------------------------------------------------------------------------- #
def _best_strategy(strat_results: dict) -> dict:
    best_nm, best_sh = None, -1e9
    for nm, r in strat_results.items():
        if r.get("skipped"):
            continue
        sh = r.get("metrics", {}).get("sharpe", -1e9)
        if sh > best_sh:
            best_sh, best_nm = sh, nm
    if best_nm is None:
        return {"name": None, "label": None, "sharpe": None,
                "total_return": None, "max_drawdown": None}
    b = strat_results[best_nm]
    m = b.get("metrics", {})
    return {"name": best_nm, "label": b.get("label"),
            "sharpe": best_sh,
            "total_return": m.get("total_return"),
            "max_drawdown": m.get("max_drawdown")}


def _build_three(strat_results: dict, qid: dict, raw: dict, feat: pd.DataFrame,
                 pos_info: dict | None = None) -> dict:
    # 维度一:数据导向
    best = _best_strategy(strat_results)
    dim1 = {
        "best_strategy": best,
        "quant_score": qid["quant_score"],
        "suspected_type": qid["suspected_type"],
        "retail_score": qid["retail_score"],
        "is_retail_dominated": qid["is_retail_dominated"],
        "min_drawdown": qid["sub_scores"]["min_drawdown"],
        "ann_vol": qid["sub_scores"]["ann_vol"],
    }
    # 维度二:公司前景长期(业绩增速/研报/新闻)
    dim2 = _company_outlook(raw)
    # 维度三:赚了谁的钱
    holder_mix = (pos_info or {}).get("holder_mix")
    dim3 = _who_profits(qid, dim2, holder_mix)
    return {
        "data_driven": dim1,
        "company_outlook": dim2,
        "who_profits": dim3,
    }


def _company_outlook(raw: dict) -> dict:
    out = {"net_profit_growth": None, "report_rating_avg": None,
            "report_count": 0, "news_sentiment": None, "news_count": 0}
    # 业绩:从 financials 取 归母净利润 最新两期
    for r in (raw.get("financials") or []):
        if isinstance(r, dict) and r.get("指标") == "归母净利润":
            vals = [r.get(k) for k in ("20260331", "20251231") if k in r]
            vals = [v for v in vals if isinstance(v, (int, float))]
            if len(vals) >= 2 and vals[1] != 0:
                g = vals[0] / vals[1] - 1.0
                out["net_profit_growth"] = round(g, 4)
            break
    # 研报评级均值(买入=1,增持=0.7,中性=0.4,减持=0.2,卖出=0)
    rating_map = {"买入": 1.0, "增持": 0.7, "中性": 0.4,
                  "减持": 0.2, "卖出": 0.0}
    rs = []
    for r in (raw.get("reports") or []):
        if isinstance(r, dict) and r.get("rating") in rating_map:
            rs.append(rating_map[r["rating"]])
    if rs:
        out["report_rating_avg"] = round(float(np.mean(rs)), 3)
        out["report_count"] = len(rs)
    # 新闻情绪(极简:含"增长/利好/超预期"为正,"下滑/风险/减持"为负)
    pos = ("增长", "利好", "超预期", "突破", "中标", "扩产")
    neg = ("下滑", "风险", "减持", "亏损", "诉讼", "下修")
    sc, n = 0, 0
    for r in (raw.get("news") or []):
        if not isinstance(r, dict):
            continue
        t = str(r.get("title") or "") + str(r.get("content") or "")
        n += 1
        if any(p in t for p in pos):
            sc += 1
        if any(g in t for g in neg):
            sc -= 1
    if n:
        out["news_sentiment"] = round(sc / n, 3)
        out["news_count"] = n
    return out


def _build_data_dimensions(raw: dict) -> dict:
    """汇总 M3.1 新增的 5 类数据维度,供 Web 展示(缺失则不计入)。"""
    out = {}
    for key in ("north_fund", "margin", "holder_num", "unlock", "block_trade"):
        v = raw.get(key)
        if isinstance(v, dict) and v.get("available"):
            out[key] = v
    return out

def _who_profits(qid: dict, dim2: dict, holder_mix: dict | None = None) -> dict:
    qs = qid["quant_score"]
    rs = qid["retail_score"]
    isr = qid["is_retail_dominated"]
    typ = qid["suspected_type"]

    mix_txt = ""
    if holder_mix:
        mix_txt = (f"持有者结构估算:量化/机构约 {holder_mix.get('institution_quant')}% · "
                   f"散户/游资约 {holder_mix.get('retail_retail')}% · "
                   f"均衡约 {holder_mix.get('balanced')}%。")

    # 优先用 holder_mix(由 qid 评分派生,与持仓分析口径一致)
    if holder_mix:
        inst = float(holder_mix.get("institution_quant", 0.0))
        ret = float(holder_mix.get("retail_retail", 0.0))
        if inst >= 45.0 and inst >= ret:
            subject = "量化/机构资金主导"
            thesis = (f"该股呈现【{typ}】特征,量化/机构资金在波动中更易凭借"
                      f"速度、算法与资金优势获利;散户多为对手盘。{mix_txt}")
        elif ret >= 45.0:
            subject = "散户/游资主导"
            thesis = ("大资金净流出而散户/游资接盘特征显著,当前以散户博弈为主;"
                      "若你方为散户,则处于信息/速度劣势的被收割端。"
                      f"{mix_txt}")
        elif inst < 35.0 and ret < 35.0:
            subject = "存量均衡 / 无显著主导"
            thesis = "未见明确量化/机构或散户主导信号,以多空存量博弈为主。" + mix_txt
        else:
            subject = "机构与散户混合博弈"
            thesis = (f"存在【{typ}】迹象但散户参与度亦不低,资金结构呈混合态,"
                      "需结合龙虎榜席位的逐笔构成进一步确认。" + mix_txt)
    else:
        if qs >= 60 and not isr:
            subject = "量化/机构资金主导"
            thesis = (f"该股呈现【{typ}】特征,量化/机构资金在波动中更易凭借"
                      f"速度、算法与资金优势获利;散户多为对手盘。")
        elif isr:
            subject = "散户/游资主导"
            thesis = ("大资金净流出而散户/游资接盘特征显著,当前以散户博弈为主;"
                      "若你方为散户,则处于信息/速度劣势的被收割端。")
        elif qs < 35:
            subject = "存量均衡 / 无显著主导"
            thesis = "未见明确量化/机构或散户主导信号,以多空存量博弈为主。"
        else:
            subject = "机构与散户混合博弈"
            thesis = (f"存在【{typ}】迹象但散户参与度亦不低,资金结构呈混合态,"
                      "需结合龙虎榜席位的逐笔构成进一步确认。")
    return {
        "subject": subject,
        "thesis": thesis,
        "quant_score": qs,
        "retail_score": rs,
        "holder_mix": holder_mix,
    }


# --------------------------------------------------------------------------- #
#  全量运行
# --------------------------------------------------------------------------- #
def run_all(strat_names: list | None = None, out_dir: str | None = None,
            codes: list | None = None) -> dict:
    out_dir = Path(out_dir or OUT_DIR)
    out_dir.mkdir(parents=True, exist_ok=True)

    peer_map = load_peer_map()
    peer_avg = build_peer_averages(peer_map)

    files = codes or [Path(p).stem.replace("_raw", "")
                      for p in glob.glob(str(DATA_DIR / "*_raw.json"))]
    summary = []
    per_stock = {}
    for code in files:
        try:
            res = run_stock(code, peer_avg=peer_avg, strat_names=strat_names)
        except Exception as e:
            res = {"code": code, "error": f"{type(e).__name__}: {e}"}
        per_stock[code] = res
        # 落盘单股
        try:
            (out_dir / f"{code}_quant.json").write_text(
                json.dumps(res, ensure_ascii=False, indent=2), encoding="utf-8")
        except Exception:
            pass
        # 摘要行
        q = res.get("quant_fund", {})
        rk = (res.get("risk") or {}).get("strategy") or {}
        summary.append({
            "code": code,
            "name": res.get("name", ""),
            "quant_score": q.get("quant_score"),
            "retail_score": q.get("retail_score"),
            "is_retail_dominated": q.get("is_retail_dominated"),
            "suspected_type": q.get("suspected_type"),
            "risk_grade": rk.get("risk_grade"),
            "best_strategy": (res.get("three_dimensions", {})
                              .get("data_driven", {})
                              .get("best_strategy", {}) or {}).get("name"),
            "error": res.get("error"),
        })

    # 全局排名
    ranked_quant = sorted(
        [s for s in summary if s.get("quant_score") is not None],
        key=lambda x: x["quant_score"], reverse=True)
    retail_dom = [s for s in summary if s.get("is_retail_dominated")]
    n_err = sum(1 for s in summary if s.get("error"))

    overview = {
        "total": len(summary),
        "errors": n_err,
        "quant_top10": ranked_quant[:10],
        "retail_dominated_count": len(retail_dom),
        "retail_dominated": retail_dom,
        "generated_at": pd.Timestamp.now().strftime("%Y-%m-%d %H:%M:%S"),
    }
    (out_dir / "summary.json").write_text(
        json.dumps(overview, ensure_ascii=False, indent=2), encoding="utf-8")
    return {"overview": overview, "per_stock": per_stock}
