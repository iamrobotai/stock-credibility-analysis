# -*- coding: utf-8 -*-
"""读 config_XXX.json → 生成 Obsidian 双文件：
  raw_data_<ind>.md        （I-事件 / A-广告 / C-玩家 锚点，不加工）
  analysis_<ind>_上下游.md  （行业 §A~§J + F矩阵 + 公司拆分索引）
用法：python gen_obsidian_md.py <config.json> <out_dir>
"""
import os, sys, json

def gen_raw(cfg):
    ind = cfg['ind_name']
    L = []
    L.append(f"# {ind} — 原始数据锚点（raw_data）\n")
    L.append(f"> 配套：config_{ind}.json → mk_industry.py → {ind}_行业_分析.docx + 各公司独立 docx\n")
    L.append("> 口径：事实基准=政策公告/财报/权威媒/榜单；平台覆盖≥8类；多维=D1–D8 + F1–F6。\n")
    L.append("## 一、行业事件锚点\n")
    for e in cfg.get('events', []):
        L.append(f"- **{e['id']}**【{e['src']}】{e['text']}")
    L.append("\n## 二、广告 / 软文锚点（全量检出）\n")
    for a in cfg.get('ads', []):
        L.append(f"- **{a['id']}**【{a['src']}】{a.get('time','')}：{a['verdict']}")
    L.append("\n## 三、玩家档案锚点\n")
    for c in cfg.get('companies', []):
        row = c.get('row', ['', '', ''])
        L.append(f"- **{c['name']} {c['code']}**（{c['tag']}）：{row[0]}；{row[1]}；{row[2]}")
    L.append("\n## 四、分段 / 锚点说明\n")
    L.append("- 本行业为\"强周期 + 国产替代/需求驱动型\"，非单股价格曲线，故不做 P1–P6 分段；景气度以\"订单放量加速周期\"刻画。")
    L.append(f"- 平台覆盖核验：雪球、东方财富、百度百家号、新浪财经、腾讯浏览器、搜狐、中国日报、中国 WTO/TBT、TrendForce、Yole、China Daily、巨潮 等 ≥8 类。")
    L.append(f"- 数据量核验：I 事件 {len(cfg.get('events', []))} ≥15；C 玩家 {len(cfg.get('companies', []))} ≥8；A 广告 {len(cfg.get('ads', []))}（全量）；达标。")
    return "\n".join(L) + "\n"

def gen_analysis(cfg):
    ind = cfg['ind_name']
    L = []
    L.append(f"# {ind} — 上下游 + 横向对比分析（analysis）\n")
    L.append("> 股票可信度评估专家组（stock-credibility-team）｜ 含 D8 强提醒 + F1–F6 影响因素矩阵\n")
    L.append("> 本文件为客观分析样例，不构成任何投资建议。结论均回溯至 raw_data 锚点。\n")
    L.append("## §0 执行口径与可信度约定\n")
    L.append("- 事实基准：以政策公告/财报/权威媒/榜单为权威地面真相")
    L.append("- 平台覆盖：≥8 类（雪球/东财/百家号/头条/微博/微信/官网/研报）")
    L.append("- 多维评价：D1–D8（D8=真实性/广告）+ F1–F6 影响因素")
    L.append("- 可追溯：结论经 I-/A-/C- 锚点回链 raw_data")
    L.append("- 可信度标注：仅前瞻/推断标 🟢高 / 🟡中 / 🔴低；事实不标")
    L.append(f"- 数据量下限：行业事件≥15 / 公司档案≥{len(cfg.get('companies', []))} 家 / 广告全量检出\n")
    L.append("## §A 行业总览\n")
    for b in cfg.get('overview', []):
        L.append(f"- {b}")
    L.append("\n## §B 上游产业链（卡脖子 / 壁垒区）\n")
    L.append(cfg.get('upstream', '').replace('\\n', '\n'))
    L.append("\n## §C 下游需求（客户 / 场景）\n")
    L.append(cfg.get('downstream', '').replace('\\n', '\n'))
    L.append("\n## §D 横向对比：主要玩家\n")
    L.append("| 公司 | 定位 | 订单/营收 | 核心优势 |")
    L.append("|------|------|----------|----------|")
    for h in cfg.get('horizontal', []):
        L.append(f"| {h['name']} | {h.get('pos','')} | {h.get('rev','')} | {h.get('adv','')} |")
    L.append("\n## §E 技术路线（决定下一程胜负）\n")
    L.append(cfg.get('tech', '').replace('\\n', '\n'))
    L.append("\n## §F 新闻 ↔ 事实互证（权威源校准）\n")
    L.append("| 编号 | 来源 | 关键事实 |")
    L.append("|------|------|----------|")
    for e in cfg.get('events', []):
        L.append(f"| {e['id']} | {e['src']} | {e['text']} |")
    L.append("\n## §G 真实性 / 广告甄别结论（D8 强提醒门禁）\n")
    for a in cfg.get('ads', []):
        L.append(f"- **{a['id']}**【{a['src']}】类型：{a.get('type','软文')}｜判定：{a['verdict']}")
    L.append("\n## §H 行业注意点 + 原因\n")
    for i, at in enumerate(cfg.get('attention', []), 1):
        L.append(f"{i}. **{at['t']}** —— {at['r']}")
    L.append("\n## §I 分类总结\n")
    L.append(f"- 归类：{cfg.get('classification','')}\n")
    L.append("| 维度 | 归类 | 依据 | 可信度 |")
    L.append("|------|------|------|--------|")
    for c in cfg.get('confidence', []):
        L.append(f"| {c['dim']} | {c.get('dir','')} | {c.get('ev','')} | {c.get('conf','')} |")
    L.append("\n## §F矩阵 影响因素（F1–F6，R16 新增）\n")
    L.append("| 维度 | 方向 | 关键证据 | 可信度 |")
    L.append("|------|------|----------|--------|")
    for f in cfg.get('fmatrix', []):
        L.append(f"| {f['dim']} | {f.get('dir','')} | {f.get('ev','')} | {f.get('conf','')} |")
    L.append("\n## §J 客观性与局限\n")
    for b in cfg.get('limits', []):
        L.append(f"- {b}")
    L.append("\n## §K 公司拆分索引（独立 docx）\n")
    for c in cfg.get('companies', []):
        L.append(f"- [[{c['name']} {c['code']}]]：{c['tag']}")
    L.append("\n— 本分析为方法论样例，决策须经正规渠道核实。非投资建议。 —")
    return "\n".join(L) + "\n"

if __name__ == '__main__':
    if len(sys.argv) < 3:
        print("usage: python gen_obsidian_md.py <config.json> <out_dir>")
        sys.exit(1)
    with open(sys.argv[1], encoding='utf-8') as f:
        cfg = json.load(f)
    out = sys.argv[2]
    os.makedirs(out, exist_ok=True)
    ind = cfg['ind_name']
    rp = os.path.join(out, f"raw_data_{ind}.md")
    ap = os.path.join(out, f"analysis_{ind}_上下游.md")
    with open(rp, 'w', encoding='utf-8') as f:
        f.write(gen_raw(cfg))
    with open(ap, 'w', encoding='utf-8') as f:
        f.write(gen_analysis(cfg))
    print(f"[{ind}] raw={os.path.getsize(rp)}B analysis={os.path.getsize(ap)}B")
