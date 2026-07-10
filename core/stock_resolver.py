# -*- coding: utf-8 -*-
"""
stock_resolver.py — 股票代码自动解析
输入股票代码 → 返回 {code, name, industry, industry_l1, region}
数据源:
  1. 东财 datacenter API (BOARD_NAME = 行业, BOARD_LEVEL 1/2)
  2. 东财 push2 API (f58=name, f127=industry, f128=region) — 备用
  3. akshare stock_info_a_code_name — name fallback
缓存: data/stock_cache.json
"""
import json, os, time, sys
from pathlib import Path
import requests

# 支持目录重组：从子目录中找到项目根
_PROJECT_ROOT = Path(__file__).resolve().parent
while _PROJECT_ROOT.name and not (_PROJECT_ROOT / "data").exists() and _PROJECT_ROOT.parent != _PROJECT_ROOT:
    _PROJECT_ROOT = _PROJECT_ROOT.parent

DATA_DIR = _PROJECT_ROOT / "data"
CACHE_FILE = DATA_DIR / "stock_cache.json"
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"

_cache = None
_name_df = None


def _load_cache():
    global _cache
    if _cache is not None:
        return _cache
    if CACHE_FILE.exists():
        try:
            with open(CACHE_FILE, encoding="utf-8") as f:
                _cache = json.load(f)
        except Exception:
            _cache = {}
    else:
        _cache = {}
    return _cache


def _save_cache():
    DATA_DIR.mkdir(exist_ok=True)
    with open(CACHE_FILE, "w", encoding="utf-8") as f:
        json.dump(_cache, f, ensure_ascii=False, indent=2)


def _query_datacenter(code):
    """东财 datacenter: 返回 name + industry (L1+L2)"""
    url = (
        "https://datacenter-web.eastmoney.com/api/data/v1/get"
        "?sortColumns=SECURITY_CODE&sortTypes=1&pageSize=10&pageNumber=1"
        "&reportName=RPT_F10_CORETHEME_BOARDTYPE&columns=ALL"
        f"&filter=(SECURITY_CODE=\"{code}\")(BOARD_TYPE=\"行业\")"
    )
    headers = {"User-Agent": UA, "Referer": "https://data.eastmoney.com/"}
    for attempt in range(3):
        try:
            r = requests.get(url, headers=headers, timeout=10)
            data = r.json()
            rows = data.get("result", {}).get("data", [])
            if not rows:
                return None
            name = rows[0].get("SECURITY_NAME_ABBR", "")
            industry_l1 = ""
            industry_l2 = ""
            for row in rows:
                if row.get("BOARD_LEVEL") == "1":
                    industry_l1 = row.get("BOARD_NAME", "")
                elif row.get("BOARD_LEVEL") == "2":
                    industry_l2 = row.get("BOARD_NAME", "")
            industry = industry_l2 or industry_l1
            return {
                "code": code,
                "name": name,
                "industry": industry,
                "industry_l1": industry_l1,
                "region": "",
            }
        except Exception:
            if attempt < 2:
                time.sleep(1.0 * (attempt + 1))
    return None


def _query_push2(code):
    """东财 push2: 返回 name + industry + region (备用)"""
    market = "1" if str(code).startswith("6") else "0"
    url = (
        f"https://push2.eastmoney.com/api/qt/stock/get"
        f"?secid={market}.{code}&fields=f57,f58,f127,f128"
    )
    headers = {"User-Agent": UA, "Referer": "https://quote.eastmoney.com/"}
    try:
        r = requests.get(url, headers=headers, timeout=8)
        data = r.json().get("data")
        if data and data.get("f58"):
            return {
                "code": str(data.get("f57", code)),
                "name": str(data.get("f58", "")),
                "industry": str(data.get("f127", "")),
                "industry_l1": "",
                "region": str(data.get("f128", "")),
            }
    except Exception:
        pass
    return None


def _query_akshare_name(code):
    """akshare 全量股票名表 (仅 name)"""
    global _name_df
    try:
        if _name_df is None:
            import akshare as ak
            _name_df = ak.stock_info_a_code_name()
        row = _name_df[_name_df["code"] == code]
        if not row.empty:
            return str(row.iloc[0]["name"]).strip()
    except Exception:
        pass
    return ""


def resolve(code):
    """
    输入股票代码 → 返回 {code, name, industry, industry_l1, region}
    """
    code = str(code).strip()
    if code.isdigit() and len(code) <= 6:
        code = code.zfill(6)

    cache = _load_cache()
    # 缓存命中: 仅当有 name 且有 industry 时才直接返回
    if code in cache and cache[code].get("name") and cache[code].get("industry"):
        return cache[code]

    # 1. datacenter API (name + industry L1/L2)
    result = _query_datacenter(code)

    # 2. push2 API (name + industry + region)
    if not result or not result.get("name"):
        result = _query_push2(code)

    # 3. akshare fallback (name only)
    if not result or not result.get("name"):
        name = _query_akshare_name(code)
        if name:
            result = {"code": code, "name": name, "industry": "", "industry_l1": "", "region": ""}

    # 补充: datacenter 有 name 但无 region → push2 补 region
    if result and result.get("name") and not result.get("region"):
        p2 = _query_push2(code)
        if p2 and p2.get("region"):
            result["region"] = p2["region"]

    if result and result.get("name"):
        cache[code] = result
        _save_cache()
        return result

    return {"code": code, "name": "", "industry": "", "industry_l1": "", "region": ""}


def resolve_batch(codes):
    """批量解析"""
    results = {}
    for code in codes:
        results[code] = resolve(code)
        time.sleep(0.15)
    return results


if __name__ == "__main__":
    code = sys.argv[1] if len(sys.argv) > 1 else "002371"
    info = resolve(code)
    print(f"代码: {info['code']}")
    print(f"名称: {info['name']}")
    print(f"行业: {info['industry']}")
    print(f"一级行业: {info.get('industry_l1', '')}")
    print(f"地域: {info.get('region', '')}")
