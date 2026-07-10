# -*- coding: utf-8 -*-
"""
login_and_scrape.py — 本地浏览器 + 人机协同登录 批量补采 4 大受限社交源
=====================================================================
针对受反爬/登录限制、当前为空的 4 个数据源：
    xueqiu (雪球基本面) / xueqiu_posts (雪球讨论帖)
    zhihu (知乎) / taoguba (淘股吧)

机制（对应需求「使用本地浏览器 + AI 登录爬取」）:
  1. 每平台【登录一次】：用本机已装 Chrome 弹出【可见】浏览器，
     脚本自动轮询检测登录态，用户在窗口内扫码/输密码完成登录，
     登录 cookie 缓存到 data/browser_cookies/，profile 持久化到
     data/browser_profiles/（跨运行保留）。
  2. 随后【无头批量爬取】全部股票：复用已登录 cookie，逐股填充
     对应源并合并回 data/{code}_raw.json。

用法:
  # 一键：对全部 176 只股票，4 源各自登录一次后批量补采
  python login_and_scrape.py

  # 仅补某几源（首次仍需各自登录）
  python login_and_scrape.py --platforms xueqiu_posts,zhihu

  # 指定股票
  python login_and_scrape.py --codes 300308,002371,300502

  # 仅用已缓存 cookie 重跑（不再弹登录窗，适合后续增量）
  python login_and_scrape.py --scrape-only

  # 调长登录等待时间（默认 180s）
  python login_and_scrape.py --login-timeout 300

  # 强制登录弹窗也用无头（仅当你已缓存 cookie、想后台跑）
  python login_and_scrape.py --scrape-only --headless

注意: 雪球/知乎必须登录；淘股吧游客通常可访问，取不到时再手动登录后重跑。
"""
import os
import sys
import json
import glob
import time
from datetime import datetime

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "core"))
DATA = os.path.join(ROOT, "data")

# 受支持的 4 源及其所属「登录平台」
PLATFORM_OF = {
    "xueqiu": "xueqiu",          # 雪球基本面
    "xueqiu_posts": "xueqiu",     # 雪球讨论帖（同 xueqiu 登录态）
    "zhihu": "zhihu",
    "taoguba": "taoguba",
}
ALL_SOURCES = ["xueqiu", "xueqiu_posts", "zhihu", "taoguba"]


def _list_stocks(codes_arg):
    """返回 [(code, name), ...]"""
    if codes_arg:
        stocks = []
        for c in [x.strip() for x in codes_arg.split(",") if x.strip()]:
            name = ""
            rp = os.path.join(DATA, f"{c}_raw.json")
            if os.path.exists(rp):
                try:
                    with open(rp, encoding="utf-8") as f:
                        name = json.load(f).get("name", "")
                except Exception:
                    pass
            stocks.append((c, name))
        return stocks
    files = sorted(glob.glob(os.path.join(DATA, "*_raw.json")))
    stocks = []
    for fp in files:
        c = os.path.basename(fp).replace("_raw.json", "")
        if not c.isdigit():
            continue
        name = ""
        try:
            with open(fp, encoding="utf-8") as f:
                name = json.load(f).get("name", "")
        except Exception:
            pass
        stocks.append((c, name))
    return stocks


def _merge_source(raw_path, key, data, force=False):
    """把 data 合并写回 {code}_raw.json 的 key 下；返回 'filled'/'skipped'/'empty'"""
    try:
        with open(raw_path, encoding="utf-8") as f:
            d = json.load(f)
    except Exception:
        return "skip"
    if not force and key in d and d[key]:
        return "skipped"   # 已有数据，幂等跳过
    has = (isinstance(data, list) and len(data) > 0) or (isinstance(data, dict) and len(data) > 0)
    if not has:
        return "empty"
    d[key] = data
    d["login_scrape_time"] = datetime.now().isoformat()
    try:
        with open(raw_path, "w", encoding="utf-8") as f:
            json.dump(d, f, ensure_ascii=False, default=str, indent=2)
        return "filled"
    except Exception:
        return "skip"


def run_xueqiu(stocks, login_timeout, scrape_only, headless_login, force,
                limit_posts):
    """登录雪球一次，批量补 xueqiu(基本面) + xueqiu_posts(讨论帖)"""
    from browser_login import (BrowserSession, ensure_login, load_cookies,
                              fetch_xueqiu_bundle, PLATFORMS)
    label = PLATFORMS["xueqiu"]["label"]
    # Phase A: 登录（可见，除非 scrape-only/headless）
    if not scrape_only:
        with BrowserSession("xueqiu", headless=headless_login) as (ctx, page):
            ok = ensure_login(page, "xueqiu", login_timeout=login_timeout, force=True)
            if not ok:
                print(f"[{label}] 未登录，跳过")
                return 0, 0
    ck = load_cookies("xueqiu")
    if not ck:
        print(f"[{label}] 无登录 cookie，请先正常登录一次")
        return 0, 0
    print(f"\n>>> [{label}] 批量爬取 {len(stocks)} 只（无头，复用登录态）")
    f_fund = f_post = 0
    for i, (code, name) in enumerate(stocks, 1):
        rp = os.path.join(DATA, f"{code}_raw.json")
        if not os.path.exists(rp):
            continue
        try:
            fund, posts = fetch_xueqiu_bundle(ck, code, max_posts=limit_posts)
        except Exception as e:
            print(f"  [{code}] 雪球爬取异常: {e}")
            continue
        r1 = _merge_source(rp, "xueqiu", [fund] if fund else [], force=force)
        r2 = _merge_source(rp, "xueqiu_posts", posts, force=force)
        if r1 == "filled":
            f_fund += 1
        if r2 == "filled":
            f_post += 1
        print(f"  [{i:3d}/{len(stocks)}] {code} {name}: 基本面={r1}, 讨论帖={r2}({len(posts)}条)")
    print(f"  → 雪球基本面 新填 {f_fund} 只；雪球讨论帖 新填 {f_post} 只")
    return f_fund, f_post


def run_dom_platform(platform, source_key, stocks, login_timeout,
                     scrape_only, headless_login, force, limit, kw_fn):
    """知乎 / 淘股吧：登录一次，用已登录浏览器渲染 DOM 批量提取"""
    from browser_login import (BrowserSession, ensure_login, load_cookies,
                              inject_cookies, scrape_zhihu, scrape_taoguba,
                              PLATFORMS)
    label = PLATFORMS[platform]["label"]
    needs_login = PLATFORMS[platform]["needs_login"]
    # Phase A: 登录（游客可访问的平台不强制等待）
    if not scrape_only:
        with BrowserSession(platform, headless=headless_login) as (ctx, page):
            ok = ensure_login(page, platform, login_timeout=login_timeout, force=needs_login)
            if needs_login and not ok:
                print(f"[{label}] 未登录，跳过")
                return 0
    # Phase B: 无头批量（自动加载缓存 cookie → 已登录）
    print(f"\n>>> [{label}] 批量爬取 {len(stocks)} 只（无头，复用登录态）")
    filled = 0
    with BrowserSession(platform, headless=True) as (ctx, page):
        ck = load_cookies(platform)
        if ck:
            inject_cookies(ctx, ck)
        for i, (code, name) in enumerate(stocks, 1):
            rp = os.path.join(DATA, f"{code}_raw.json")
            if not os.path.exists(rp):
                continue
            kw = kw_fn(name, code)
            try:
                if platform == "zhihu":
                    res = scrape_zhihu(page, kw, max_count=limit)
                else:
                    res = scrape_taoguba(page, kw, max_count=limit)
            except Exception as e:
                print(f"  [{code}] {label} 爬取异常: {e}")
                continue
            r = _merge_source(rp, source_key, res, force=force)
            if r == "filled":
                filled += 1
            print(f"  [{i:3d}/{len(stocks)}] {code} {name}: {label}={r}({len(res)}条)")
    print(f"  → {label} 新填 {filled} 只")
    return filled


def main():
    import argparse
    ap = argparse.ArgumentParser(description="本地浏览器+登录 批量补采受限社交源")
    ap.add_argument("--platforms", default=",".join(ALL_SOURCES),
                    help="要补的源: xueqiu,xueqiu_posts,zhihu,taoguba")
    ap.add_argument("--codes", default="", help="指定股票代码,分隔; 默认全部")
    ap.add_argument("--login-timeout", type=int, default=180, help="登录等待秒数")
    ap.add_argument("--scrape-only", action="store_true", help="仅用已缓存cookie,不弹登录窗")
    ap.add_argument("--headless", action="store_true", help="登录阶段也用无头(需已缓存cookie)")
    ap.add_argument("--force", action="store_true", help="强制覆盖已填源")
    ap.add_argument("--limit-posts", type=int, default=30)
    ap.add_argument("--limit", type=int, default=20, help="知乎/淘股吧每支上限")
    args = ap.parse_args()

    try:
        from browser_login import is_available, PLATFORMS
    except ImportError:
        print("browser_login 模块缺失"); sys.exit(1)
    if not is_available():
        print("❌ Playwright 未安装。请先执行:")
        print("   pip install playwright && playwright install chromium")
        sys.exit(1)

    wanted = [s.strip() for s in args.platforms.split(",") if s.strip()]
    # 归并到登录平台
    plat_set = {}
    for s in wanted:
        if s not in PLATFORM_OF:
            print(f"⚠️ 未知源: {s} (可选: {ALL_SOURCES})")
            continue
        plat_set.setdefault(PLATFORM_OF[s], set()).add(s)

    stocks = _list_stocks(args.codes)
    if not stocks:
        print("⚠️ 未找到任何 {code}_raw.json，请先运行主采集生成基础数据")
        sys.exit(1)
    print(f"目标股票: {len(stocks)} 只 | 登录平台: {list(plat_set.keys())} | "
          f"登录等待: {args.login_timeout}s | scrape-only={args.scrape_only}")

    t0 = time.time()
    summary = {}
    for plat, sources in plat_set.items():
        if plat == "xueqiu":
            f1, f2 = run_xueqiu(stocks, args.login_timeout, args.scrape_only,
                                  args.headless, args.force, args.limit_posts)
            summary["xueqiu"] = f1
            summary["xueqiu_posts"] = f2
        elif plat == "zhihu":
            if "zhihu" in sources:
                n = run_dom_platform("zhihu", "zhihu", stocks, args.login_timeout,
                                     args.scrape_only, args.headless, args.force,
                                     args.limit, lambda n, c: n if n else c)
                summary["zhihu"] = n
        elif plat == "taoguba":
            if "taoguba" in sources:
                n = run_dom_platform("taoguba", "taoguba", stocks, args.login_timeout,
                                     args.scrape_only, args.headless, args.force,
                                     args.limit, lambda n, c: n if n else c)
                summary["taoguba"] = n

    print(f"\n{'='*56}")
    print(f"完成 | 用时 {time.time()-t0:.0f}s")
    for k, v in summary.items():
        print(f"  {k:<16} 新填 {v} 只")
    print(f"{'='*56}")
    if not args.scrape_only:
        print("提示: 后续增量补采可直接 `python login_and_scrape.py --scrape-only`")


if __name__ == "__main__":
    main()
