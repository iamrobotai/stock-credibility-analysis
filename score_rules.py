# -*- coding: utf-8 -*-
"""
score_rules.py — 规则化 D1-D8 评分器（本地，零 token，无需 LLM）
对每条帖子/新闻/研报评分 D1-D8，并映射到分段。
D1 来源可信度 | D2 论据充分性 | D3 逻辑一致性 | D4 数据引用准确性
D5 时效性 | D6 独立性/广告 | D7 预测具体性 | D8 广告甄别
"""
import json, os, re, sys
from datetime import datetime

# ---- 关键词库 ----
KW_EVIDENCE = [
    "营收", "净利", "利润", "PE", "PB", "ROE", "订单", "产能", "市占率", "毛利率",
    "出货量", "渗透率", "增长率", "同比", "环比", "亿元", "万片", "GWh", "TPU",
    "良率", "制程", "nm", "良品率", "稼动率", "ASP", "单价", "毛利率",
]
KW_LOGIC = ["因为", "所以", "预计", "基于", "因此", "随着", "得益于", "受益于",
            "驱动", "导致", "意味着", "反映出", "佐证", "印证", "逻辑"]
KW_SPECIFIC = ["目标价", "EPS", "PE", "市值", "时间点", "年底", "2026", "2027",
               "预计达", "有望达", "将达", "增速", "对应", "估值"]
KW_AD = ["开户", "扫码", "加微信", "加群", "翻倍清单", "涨停板", "喊单",
         "限时", "免费领取", "点击链接", "知识星球", "内部消息"]
KW_PROMO = ["必涨", "稳赚", "暴涨", "起飞", "拉升", "主升浪",
            "翻倍潜力", "闭眼买", "钻石底", "黄金坑", "满仓", "抄底"]

SOURCE_CRED = {
    "研报": 0.90, "东财研报": 0.90,
    "公告": 0.95, "巨潮资讯": 0.95, "cninfo": 0.95,
    "互动易": 0.90, "ir": 0.90,
    "新闻": 0.70, "东财新闻": 0.70, "证券时报": 0.75, "证券时报网": 0.75,
    "同花顺": 0.60, "ths": 0.60,
    "雪球": 0.45,
    "股吧": 0.35, "东财股吧": 0.35,
    "淘股吧": 0.30, "taoguba": 0.30,
}


def score_d1(source):
    """来源可信度 0-1"""
    for k, v in SOURCE_CRED.items():
        if k in str(source):
            return round(v, 2)
    return 0.50


def score_d2(text):
    """论据充分性：关键词命中密度"""
    hits = sum(1 for kw in KW_EVIDENCE if kw in text)
    return round(min(1.0, 0.15 * hits + 0.1), 2)


def score_d3(text):
    """逻辑一致性：逻辑连接词"""
    hits = sum(1 for kw in KW_LOGIC if kw in text)
    return round(min(1.0, 0.12 * hits + 0.15), 2)


def score_d4(text, financials):
    """数据引用准确性：检查是否引用了真实财务数字"""
    if not financials:
        return 0.30
    # 提取文本中的数字（亿元级别）
    nums = re.findall(r"(\d+\.?\d*)\s*亿", text)
    if not nums:
        return 0.30
    # 从财务数据中提取真实数字
    real_nums = set()
    for f in financials[:20]:
        for v in f.values():
            try:
                fv = float(v)
                if 1e8 < abs(fv) < 1e12:  # 亿元级别
                    real_nums.add(round(fv / 1e8, 1))
            except (ValueError, TypeError):
                continue
    matches = sum(1 for n in nums if any(abs(float(n) - r) < 2 for r in real_nums))
    return round(min(1.0, 0.25 * matches + 0.2), 2) if matches else 0.25


def score_d5(post_date, segments):
    """时效性：帖子日期与最近分段端点的距离"""
    if not post_date or not segments:
        return 0.50
    try:
        pd = datetime.strptime(str(post_date)[:10], "%Y-%m-%d")
    except Exception:
        return 0.50
    best = 999
    for s in segments:
        for dkey in ("start_date", "end_date"):
            try:
                sd = datetime.strptime(s[dkey][:10], "%Y-%m-%d")
                gap = abs((pd - sd).days)
                if gap < best:
                    best = gap
            except Exception:
                continue
    if best <= 7:
        return 1.0
    elif best <= 30:
        return 0.80
    elif best <= 90:
        return 0.60
    elif best <= 180:
        return 0.40
    return 0.20


def score_d6(text):
    """独立性/广告：促销语言越多越低"""
    promo = sum(1 for kw in KW_PROMO if kw in text)
    ad = sum(1 for kw in KW_AD if kw in text)
    return round(max(0.1, 0.9 - 0.15 * promo - 0.25 * ad), 2)


def score_d7(text):
    """预测具体性：是否含具体目标/数字"""
    hits = sum(1 for kw in KW_SPECIFIC if kw in text)
    nums = len(re.findall(r"\d+\.?\d*", text))
    return round(min(1.0, 0.10 * hits + 0.02 * nums + 0.1), 2)


def score_d8(text):
    """广告甄别：命中广告关键词 → 标记"""
    ad_hits = [kw for kw in KW_AD if kw in text]
    promo_hits = [kw for kw in KW_PROMO if kw in text]
    is_ad = len(ad_hits) >= 1 or len(promo_hits) >= 2
    return {
        "is_ad": is_ad,
        "ad_keywords": ad_hits,
        "promo_keywords": promo_hits,
        "level": "⚠️⚠️⚠️" if is_ad and len(ad_hits) >= 2 else ("⚠️" if is_ad else ""),
    }


def score_post(post, source_type, financials, segments):
    """对单条帖子评分 D1-D8"""
    text = str(post.get("title", "")) + " " + str(post.get("content", ""))
    source = str(post.get("source", source_type))
    post_date = str(post.get("time", "") or post.get("date", ""))

    d8 = score_d8(text)
    return {
        **post,
        "source_type": source_type,
        "D1": score_d1(source),
        "D2": score_d2(text),
        "D3": score_d3(text),
        "D4": score_d4(text, financials),
        "D5": score_d5(post_date, segments),
        "D6": score_d6(text),
        "D7": score_d7(text),
        "D8": d8,
        "avg_d": round(
            sum([score_d1(source), score_d2(text), score_d3(text),
                 score_d4(text, financials), score_d5(post_date, segments),
                 score_d6(text), score_d7(text)]) / 7, 2),
    }


def run(code, datadir="data"):
    raw_path = os.path.join(datadir, f"{code}_raw.json")
    seg_path = os.path.join(datadir, f"{code}_segments.json")
    if not os.path.exists(raw_path):
        print(f"[score] {raw_path} not found")
        return None

    raw = json.load(open(raw_path, encoding="utf-8"))
    segments = []
    if os.path.exists(seg_path):
        segments = json.load(open(seg_path, encoding="utf-8"))

    financials = raw.get("financials", [])
    scored = {"code": code, "name": raw.get("name", ""),
              "segments": segments, "posts": []}

    # 评分股吧帖 (情绪源, 可信度低)
    for p in raw.get("guba", []):
        scored["posts"].append(score_post(p, "股吧", financials, segments))

    # 评分淘股吧 (情绪源, 可信度低)
    for p in raw.get("taoguba", []):
        scored["posts"].append(score_post(p, "淘股吧", financials, segments))

    # 评分新闻 (中等可信度)
    for n in raw.get("news", []):
        scored["posts"].append(score_post(n, "新闻", financials, segments))

    # 评分研报 (高可信度)
    for r in raw.get("reports", []):
        scored["posts"].append(score_post(r, "研报", financials, segments))

    # 评分巨潮公告 (高可信度, 官方信息)
    for c in raw.get("cninfo", []):
        scored["posts"].append(score_post(
            {"title": c.get("title", ""), "content": c.get("type", ""),
             "source": "巨潮资讯", "time": c.get("date", "")},
            "公告", financials, segments))

    # 评分互动易 (高可信度, 公司回应)
    for ir in raw.get("ir", []):
        scored["posts"].append(score_post(
            {"title": ir.get("question", "")[:80], "content": ir.get("answer", ""),
             "source": "互动易", "time": ir.get("date", "")},
            "互动易", financials, segments))

    # 统计
    ads = [p for p in scored["posts"] if p["D8"]["is_ad"]]
    by_type = {}
    for p in scored["posts"]:
        t = p["source_type"]
        by_type.setdefault(t, []).append(p["avg_d"])

    print(f"[score] {code}: {len(scored['posts'])} posts scored, {len(ads)} ads flagged")
    for t, scores in by_type.items():
        avg = round(sum(scores) / len(scores), 2) if scores else 0
        print(f"  {t}: {len(scores)} posts, avg_D={avg}")
    if ads:
        print(f"  ⚠️ ADS: {[a['title'][:40] for a in ads[:3]]}")

    outf = os.path.join(datadir, f"{code}_scored.json")
    with open(outf, "w", encoding="utf-8") as f:
        json.dump(scored, f, ensure_ascii=False, indent=2)
    print(f"  -> {outf}")
    return scored


if __name__ == "__main__":
    code = sys.argv[1] if len(sys.argv) > 1 else "002371"
    run(code)
