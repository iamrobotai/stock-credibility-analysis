# -*- coding: utf-8 -*-
"""
export_obsidian_memory.py — 将采集的多源数据导出为 Obsidian 数据记忆库
========================================================================
产出:
  <VAULT>/A股分析/数据记忆/<name>(<code>).md   每股一个数据记忆笔记
  <VAULT>/A股分析/数据记忆/_数据记忆索引.md      总索引 (覆盖率 + 采集时间)

设计意图 (支持下次增量):
  - 笔记 frontmatter 记录各数据源条数 + fetch_time/supplement_time
  - 索引记录全量覆盖矩阵，下次运行 supplement_sources.py 即可只补新数据
用法:
  python export_obsidian_memory.py            # 全部
  python export_obsidian_memory.py 300308     # 单只
"""
import sys, os, json, glob
from datetime import datetime

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(ROOT, "data")
VAULT = r"D:\黑曜石笔记"
OUTDIR = os.path.join(VAULT, "A股分析", "数据记忆")

SRC_LABEL = {
    "kline": "K线", "news": "新闻", "reports": "研报", "financials": "财务",
    "cninfo": "公告", "ir": "互动易", "ths": "同花顺", "sina_fund": "资金流",
    "lhb": "龙虎榜", "xueqiu": "雪球", "xueqiu_posts": "雪球帖", "zhihu": "知乎",
    "comment": "东财评分", "guba": "股吧", "taoguba": "淘股吧",
}
ORDER = ["kline","news","reports","financials","cninfo","ir","ths",
         "sina_fund","lhb","comment","guba","xueqiu","xueqiu_posts","zhihu","taoguba"]

def _n(v):
    if isinstance(v, list): return len(v)
    if isinstance(v, dict): return 1 if v else 0
    if v: return 1
    return 0

def _g(v, i=0):
    return v[i] if isinstance(v, list) and len(v) > i else {}

def build_note(d):
    code = d.get("code",""); name = d.get("name","") or code
    cov = {k: _n(d.get(k)) for k in ORDER}
    ft = d.get("fetch_time",""); st = d.get("supplement_time","")
    L = []
    # frontmatter
    L.append("---")
    L.append(f"title: {name}({code}) - 多源数据记忆")
    L.append("tags: [A股, 可信度数据, 数据记忆]")
    L.append(f"code: {code}")
    L.append(f"fetch_time: {ft[:19] if ft else ''}")
    L.append(f"supplement_time: {st[:19] if st else ''}")
    L.append(f"coverage: {{{', '.join(f'{k}: {cov[k]}' for k in ORDER if cov[k])}}}")
    L.append("---\n")
    L.append(f"# {name}({code}) — 多源数据记忆\n")
    L.append(f"> 采集: {ft[:19] if ft else '—'} ｜ 补充: {st[:19] if st else '—'} ｜ [[_数据记忆索引|← 返回索引]]")
    L.append("> 本笔记为原始数据缓存，供可信度分析复用；下次仅需增量补充新数据。\n")

    # 数据源覆盖
    L.append("## 数据源覆盖\n")
    L.append("| 数据源 | 条数 | 数据源 | 条数 |")
    L.append("|------|----|------|----|")
    items = [(SRC_LABEL[k], cov[k]) for k in ORDER]
    for i in range(0, len(items), 2):
        a = items[i]; b = items[i+1] if i+1 < len(items) else ("", "")
        bn = b[1] if b[0] else ""
        L.append(f"| {a[0]} | {a[1] or '—'} | {b[0]} | {bn if bn!='' else ''} |")
    L.append("")

    # 情绪评分 (comment)
    cm = _g(d.get("comment"))
    if cm:
        L.append("## 市场情绪评分（东财）\n")
        L.append(f"- 综合得分 **{cm.get('综合得分','—')}** ｜ 机构参与度 {cm.get('机构参与度','—')} ｜ 关注指数 {cm.get('关注指数','—')} ｜ 目前排名 {cm.get('目前排名','—')} ｜ 主力成本 {cm.get('主力成本','—')}\n")

    # 最新研报
    reps = d.get("reports") or []
    if reps:
        L.append("## 最新研报（Top5）\n")
        L.append("| 日期 | 机构 | 评级 | 26EPS | 26PE | 报告 |")
        L.append("|------|------|------|-------|------|------|")
        for r in reps[:5]:
            L.append(f"| {r.get('date','')} | {r.get('org','')} | {r.get('rating','')} | {r.get('eps_2026','')} | {r.get('pe_2026','')} | {str(r.get('title',''))[:30]} |")
        L.append("")

    # 最新公告
    ann = d.get("cninfo") or []
    if ann:
        L.append("## 最新公告（Top6）\n")
        for a in ann[:6]:
            L.append(f"- `{a.get('date','')}` [{a.get('title','')}]({a.get('url','')})")
        L.append("")

    # 互动易
    ir = d.get("ir") or []
    if ir:
        L.append("## 互动易问答（Top3）\n")
        for q in ir[:3]:
            L.append(f"- **Q**（{q.get('date','')}）：{str(q.get('question',''))[:80]}")
            L.append(f"  **A**：{str(q.get('answer',''))[:120]}")
        L.append("")

    # 资金流
    sf = d.get("sina_fund") or []
    if sf:
        L.append("## 主力资金流（近5日）\n")
        L.append("| 日期 | 主力净额 | 主力占比 | 超大单 |")
        L.append("|------|--------|--------|------|")
        for f in sf[:5]:
            L.append(f"| {f.get('date','')} | {f.get('main_net','')} | {f.get('main_pct','')} | {f.get('super_net','')} |")
        L.append("")

    # 龙虎榜
    lhb = d.get("lhb") or []
    if lhb:
        L.append(f"## 龙虎榜（近3月，共{len(lhb)}次）\n")
        for x in lhb[:5]:
            date = x.get('上榜日') or x.get('交易日') or x.get('日期','')
            reason = x.get('解读') or x.get('上榜原因') or ''
            L.append(f"- `{date}` {str(reason)[:60]}")
        L.append("")

    # 最新新闻
    news = d.get("news") or []
    if news:
        L.append("## 最新新闻（Top5）\n")
        for nn in news[:5]:
            L.append(f"- `{str(nn.get('time',''))[:10]}`【{nn.get('source','')}】[{nn.get('title','')}]({nn.get('url','')})")
        L.append("")

    L.append("\n---\n*数据记忆自动生成，仅供可信度分析复用，非投资建议。*")
    return "\n".join(L) + "\n", cov, ft, st

def main():
    os.makedirs(OUTDIR, exist_ok=True)
    codes = sys.argv[1:]
    if codes:
        files = [os.path.join(DATA, f"{c}_raw.json") for c in codes]
    else:
        files = sorted(glob.glob(os.path.join(DATA, "*_raw.json")))
    index = []
    done = 0
    for path in files:
        if not os.path.exists(path):
            continue
        try:
            with open(path, encoding="utf-8") as f:
                d = json.load(f)
        except Exception as e:
            print(f"读取失败 {path}: {e}"); continue
        code = d.get("code",""); name = d.get("name","") or code
        note, cov, ft, st = build_note(d)
        # 文件名安全化
        safe = name.replace("/", "_").replace("*","").replace("\\","_")
        fn = os.path.join(OUTDIR, f"{safe}({code}).md")
        with open(fn, "w", encoding="utf-8") as f:
            f.write(note)
        index.append((code, name, cov, st or ft))
        done += 1
    # 索引
    write_index(index)
    print(f"导出完成: {done} 个数据记忆笔记 + 1 个索引 → {OUTDIR}")

def write_index(index):
    L = []
    L.append("---")
    L.append("title: 数据记忆索引")
    L.append("tags: [A股, 可信度数据, 索引]")
    L.append(f"updated: {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    L.append(f"count: {len(index)}")
    L.append("---\n")
    L.append("# A股多源数据记忆 — 总索引\n")
    L.append(f"> 共 **{len(index)}** 只 ｜ 更新: {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    L.append("> 覆盖标记: ✅有 / ➖空。下次运行 `supplement_sources.py` 仅补空缺，再 `export_obsidian_memory.py` 刷新本库。\n")
    key_src = ["kline","news","reports","financials","cninfo","ir","ths","sina_fund","lhb","comment"]
    hdr = "| 股票 | " + " | ".join(SRC_LABEL[k] for k in key_src) + " | 采集时间 |"
    sep = "|------|" + "|".join(["----"]*len(key_src)) + "|------|"
    L.append(hdr); L.append(sep)
    for code, name, cov, t in sorted(index, key=lambda x: x[0]):
        cells = []
        for k in key_src:
            cells.append(f"{cov.get(k,0)}" if cov.get(k,0) else "➖")
        L.append(f"| [[{name}({code})]] | " + " | ".join(cells) + f" | {str(t)[:10]} |")
    # 覆盖统计
    L.append("\n## 覆盖率统计\n")
    tot = len(index) or 1
    L.append("| 数据源 | 有数据 | 覆盖率 |")
    L.append("|------|------|------|")
    for k in key_src:
        c = sum(1 for _,_,cov,_ in index if cov.get(k,0))
        L.append(f"| {SRC_LABEL[k]} | {c} | {c/tot*100:.0f}% |")
    fn = os.path.join(OUTDIR, "_数据记忆索引.md")
    with open(fn, "w", encoding="utf-8") as f:
        f.write("\n".join(L) + "\n")

if __name__ == "__main__":
    main()
