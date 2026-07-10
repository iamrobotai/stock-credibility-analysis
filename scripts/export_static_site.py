# -*- coding: utf-8 -*-
"""
scripts/export_static_site.py — M5 静态快照导出器
==================================================
读取 output/quant/*_quant.json + summary.json，渲染为「自包含、零后端」
静态站点（dist_static/index.html），可直接托管 / CloudStudio 部署分享：

  - 顶部：量化 Top10 榜单 + 散户主导计数 + 生成时间
  - 中部：全量股票表（可搜索/排序），列 = 量化评分/散户评分/疑似类型/风险等级/最优策略
  - 点击某行 → 右侧详情：三维结论 + 策略绩效 + 风控 + 持仓结构 + 数据维度

所有数据以精简 JSON 内联进单个 HTML，无需任何请求。暗色 GitHub 风。

用法:
  python scripts/export_static_site.py                # 生成 dist_static/
  python scripts/export_static_site.py --out <dir>
"""
import argparse
import glob
import json
import os
from datetime import datetime

_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(_HERE)
QUANT_DIR = os.path.join(_ROOT, "output", "quant")
DEFAULT_OUT = os.path.join(_ROOT, "dist_static")


def _pct(v, nd=1):
    try:
        return round(float(v) * 100, nd)
    except Exception:
        return None


def _trim_stock(s: dict) -> dict:
    """精简单股数据，去掉体积大的 returns/positions 序列。"""
    td = s.get("three_dimensions", {}) or {}
    d1 = td.get("data_driven", {}) or {}
    d2 = td.get("company_outlook", {}) or {}
    d3 = td.get("who_profits", {}) or {}
    qf = s.get("quant_fund", {}) or {}
    rk = (s.get("risk") or {}).get("strategy") or {}
    pos = s.get("position", {}) or {}
    best = d1.get("best_strategy", {}) or {}

    strat = {}
    for nm, r in (s.get("strategies") or {}).items():
        if r.get("skipped"):
            strat[nm] = {"label": r.get("label", nm), "skipped": True,
                         "reason": r.get("reason", "")}
        else:
            m = r.get("metrics", {}) or {}
            strat[nm] = {
                "label": r.get("label", nm), "skipped": False,
                "sharpe": m.get("sharpe"),
                "total_return": _pct(m.get("total_return")),
                "max_drawdown": _pct(m.get("max_drawdown")),
                "win_rate": _pct(m.get("win_rate")),
            }

    dims = {}
    for k, v in (s.get("data_dimensions") or {}).items():
        if isinstance(v, dict) and v.get("available"):
            dims[k] = True

    return {
        "code": s.get("code"), "name": s.get("name"),
        "period": f'{s.get("date_start","")}~{s.get("date_end","")}',
        "n_days": s.get("n_days"),
        "quant_score": qf.get("quant_score"),
        "retail_score": qf.get("retail_score"),
        "is_retail": qf.get("is_retail_dominated"),
        "suspected": qf.get("suspected_type"),
        "risk_grade": rk.get("risk_grade"),
        "ann_vol": _pct(rk.get("ann_vol")),
        "var95": _pct(rk.get("var_95")),
        "best": {"label": best.get("label"), "sharpe": best.get("sharpe"),
                 "ret": _pct(best.get("total_return")),
                 "dd": _pct(best.get("max_drawdown"))},
        "dim2": {"growth": _pct(d2.get("net_profit_growth")),
                 "rating": d2.get("report_rating_avg"),
                 "news": d2.get("news_sentiment")},
        "dim3_subject": d3.get("subject"),
        "dim3_thesis": d3.get("thesis"),
        "holder_mix": pos.get("holder_mix"),
        "strategies": strat,
        "dims": list(dims.keys()),
        "error": s.get("error"),
    }


def collect():
    summary = {}
    sp = os.path.join(QUANT_DIR, "summary.json")
    if os.path.exists(sp):
        summary = json.load(open(sp, encoding="utf-8"))
    stocks = []
    for f in sorted(glob.glob(os.path.join(QUANT_DIR, "*_quant.json"))):
        try:
            s = json.load(open(f, encoding="utf-8"))
        except Exception:
            continue
        stocks.append(_trim_stock(s))
    # 按量化评分降序
    stocks.sort(key=lambda x: (x.get("quant_score") is None, -(x.get("quant_score") or 0)))
    return summary, stocks


def render_html(summary: dict, stocks: list) -> str:
    payload = json.dumps({"summary": summary, "stocks": stocks},
                         ensure_ascii=False)
    gen = summary.get("generated_at") or datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    total = summary.get("total", len(stocks))
    retail_n = summary.get("retail_dominated_count", 0)
    return _TEMPLATE.replace("__PAYLOAD__", payload) \
                    .replace("__GEN__", str(gen)) \
                    .replace("__TOTAL__", str(total)) \
                    .replace("__RETAIL__", str(retail_n))


def export(out_dir: str = DEFAULT_OUT) -> str:
    os.makedirs(out_dir, exist_ok=True)
    summary, stocks = collect()
    html = render_html(summary, stocks)
    path = os.path.join(out_dir, "index.html")
    with open(path, "w", encoding="utf-8") as f:
        f.write(html)
    return path


_TEMPLATE = r"""<!DOCTYPE html>
<html lang="zh-CN"><head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>A股量化三维分析 · 静态快照</title>
<style>
:root{--bg:#0d1117;--card:#161b22;--bd:#30363d;--fg:#c9d1d9;--mut:#8b949e;--red:#f85149;--grn:#3fb950;--acc:#58a6ff;--yel:#d29922}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--fg);font:14px/1.6 -apple-system,"Microsoft YaHei",sans-serif}
.wrap{max-width:1280px;margin:0 auto;padding:20px}
h1{font-size:20px;margin:0 0 4px}.sub{color:var(--mut);font-size:12px;margin-bottom:16px}
.stats{display:flex;gap:12px;margin-bottom:16px;flex-wrap:wrap}
.stat{background:var(--card);border:1px solid var(--bd);border-radius:8px;padding:10px 16px}
.stat b{font-size:20px;color:var(--acc)}.stat span{color:var(--mut);font-size:12px;display:block}
.layout{display:grid;grid-template-columns:1fr 1fr;gap:16px}
@media(max-width:900px){.layout{grid-template-columns:1fr}}
.card{background:var(--card);border:1px solid var(--bd);border-radius:8px;padding:14px}
.card h2{font-size:15px;margin:0 0 10px}
input{width:100%;padding:8px 10px;background:#0d1117;border:1px solid var(--bd);border-radius:6px;color:var(--fg);margin-bottom:10px}
table{width:100%;border-collapse:collapse;font-size:12.5px}
th,td{padding:6px 8px;border-bottom:1px solid var(--bd);text-align:right}
th:first-child,td:first-child{text-align:left}
th{color:var(--mut);cursor:pointer;user-select:none;position:sticky;top:0;background:var(--card)}
tbody tr{cursor:pointer}tbody tr:hover{background:#1c2333}tbody tr.sel{background:#1f2937}
.tblwrap{max-height:70vh;overflow:auto}
.badge{display:inline-block;padding:1px 7px;border-radius:10px;font-size:11px}
.b-red{background:rgba(248,81,73,.15);color:var(--red)}.b-grn{background:rgba(63,185,80,.15);color:var(--grn)}
.b-yel{background:rgba(210,153,34,.15);color:var(--yel)}
.dim{border-left:3px solid var(--acc);padding:6px 10px;margin:8px 0;background:#0d1117;border-radius:0 6px 6px 0}
.dim .t{font-weight:bold;font-size:12px;color:var(--acc)}.dim .b{font-size:12.5px;margin-top:2px}
.kv{display:flex;flex-wrap:wrap;gap:6px 16px;margin:6px 0}.kv span{font-size:12.5px}.kv b{color:#fff}
.mut{color:var(--mut)}.up{color:var(--red)}.down{color:var(--grn)}
.foot{color:var(--mut);font-size:11px;margin-top:20px;text-align:center}
</style></head><body>
<div class="wrap">
  <h1>📊 A股量化三维分析 · 静态快照</h1>
  <div class="sub">生成时间：__GEN__　·　零后端自包含页面（数据已内联，可离线查看 / 分享）</div>
  <div class="stats">
    <div class="stat"><b>__TOTAL__</b><span>覆盖标的</span></div>
    <div class="stat"><b>__RETAIL__</b><span>疑似散户主导</span></div>
    <div class="stat"><b id="stShown">0</b><span>当前筛选</span></div>
  </div>
  <div class="layout">
    <div class="card">
      <h2>🏆 全量榜单（点击查看详情）</h2>
      <input id="q" placeholder="搜索代码 / 名称 / 疑似类型…">
      <div class="tblwrap"><table id="tbl">
        <thead><tr>
          <th data-k="name">名称</th><th data-k="quant_score">量化分</th>
          <th data-k="retail_score">散户分</th><th data-k="suspected">疑似类型</th>
          <th data-k="risk_grade">风险</th>
        </tr></thead><tbody id="tb"></tbody>
      </table></div>
    </div>
    <div class="card" id="detail">
      <h2>📄 详情</h2>
      <div class="mut">← 点击左侧任意标的查看三维结论、策略绩效、风控与持仓结构。</div>
    </div>
  </div>
  <div class="foot">本快照所有量化识别 / 「赚了谁的钱」 / 持有者结构均为疑似推断，非投资建议。</div>
</div>
<script>
const DATA=__PAYLOAD__;
const $=s=>document.querySelector(s);
let rows=DATA.stocks.slice(), sortK='quant_score', sortDir=-1;
function grade(g){if(!g)return '<span class="mut">—</span>';
  const m={'高':'b-red','中':'b-yel','低':'b-grn'};let c='b-yel';
  for(const k in m){if(String(g).includes(k))c=m[k];}
  return `<span class="badge ${c}">${g}</span>`;}
function fnum(v){return v==null?'—':(+v).toFixed(1);}
function fpct(v){if(v==null)return '<span class="mut">—</span>';const c=v>=0?'up':'down';return `<span class="${c}">${v>=0?'+':''}${v}%</span>`;}
function renderTable(){
  const q=($('#q').value||'').trim().toLowerCase();
  let r=rows.filter(s=>!q||`${s.code} ${s.name} ${s.suspected||''}`.toLowerCase().includes(q));
  r.sort((a,b)=>{let x=a[sortK],y=b[sortK];if(x==null)x=-1e9;if(y==null)y=-1e9;
    if(typeof x==='string')return sortDir*String(x).localeCompare(String(y));return sortDir*(x-y);});
  $('#stShown').textContent=r.length;
  $('#tb').innerHTML=r.map(s=>`<tr data-c="${s.code}">
    <td>${s.name||''} <span class="mut">${s.code}</span></td>
    <td>${fnum(s.quant_score)}</td><td>${fnum(s.retail_score)}</td>
    <td>${s.is_retail?'<span class="badge b-red">散户</span> ':''}${s.suspected||'—'}</td>
    <td>${grade(s.risk_grade)}</td></tr>`).join('');
  document.querySelectorAll('#tb tr').forEach(tr=>tr.onclick=()=>{
    document.querySelectorAll('#tb tr').forEach(t=>t.classList.remove('sel'));
    tr.classList.add('sel');showDetail(tr.dataset.c);});
}
function showDetail(code){
  const s=rows.find(x=>x.code===code);if(!s)return;
  const b=s.best||{},m=s.holder_mix||{},d2=s.dim2||{};
  let strat='';for(const k in (s.strategies||{})){const r=s.strategies[k];
    strat+=r.skipped?`<tr><td>${r.label}</td><td colspan="4" class="mut">跳过：${r.reason||''}</td></tr>`
      :`<tr><td>${r.label}</td><td>${fnum(r.sharpe)}</td><td>${fpct(r.total_return)}</td><td>${fpct(r.max_drawdown)}</td><td>${r.win_rate==null?'—':r.win_rate+'%'}</td></tr>`;}
  let mix='';if(m.institution_quant!=null)mix=`<div class="kv">
    <span>量化/机构 <b>${m.institution_quant}%</b></span>
    <span>散户/游资 <b>${m.retail_retail}%</b></span>
    <span>均衡 <b>${m.balanced}%</b></span></div>`;
  $('#detail').innerHTML=`<h2>${s.name} <span class="mut">${s.code}</span></h2>
    <div class="mut" style="font-size:12px">区间 ${s.period}　·　${s.n_days} 交易日</div>
    <div class="kv" style="margin-top:8px">
      <span>量化评分 <b>${fnum(s.quant_score)}</b></span>
      <span>散户评分 <b>${fnum(s.retail_score)}</b></span>
      <span>疑似类型 <b>${s.suspected||'—'}</b></span>
      <span>风险等级 ${grade(s.risk_grade)}</span></div>
    <div class="dim"><div class="t">① 数据导向</div><div class="b">最优策略 <b>${b.label||'—'}</b>（夏普 ${fnum(b.sharpe)}，收益 ${fpct(b.ret)}，回撤 ${fpct(b.dd)}）；年化波动 ${s.ann_vol==null?'—':s.ann_vol+'%'}，VaR95 ${s.var95==null?'—':s.var95+'%'}。</div></div>
    <div class="dim"><div class="t">② 公司前景</div><div class="b">净利同比 ${d2.growth==null?'—':d2.growth+'%'}　·　研报评级均值 ${d2.rating??'—'}　·　新闻情绪 ${d2.news??'—'}</div></div>
    <div class="dim"><div class="t">③ 赚了谁的钱</div><div class="b"><b>${s.dim3_subject||'—'}</b>：${s.dim3_thesis||''}</div></div>
    ${mix?'<h2 style="margin-top:12px">📦 持仓结构（疑似）</h2>'+mix:''}
    <h2 style="margin-top:12px">📈 策略绩效</h2>
    <table><thead><tr><th>策略</th><th>夏普</th><th>收益</th><th>回撤</th><th>胜率</th></tr></thead><tbody>${strat}</tbody></table>
    ${s.dims&&s.dims.length?'<div class="mut" style="margin-top:10px;font-size:12px">已采集数据维度：'+s.dims.join(' / ')+'</div>':''}`;
}
document.querySelectorAll('#tbl th').forEach(th=>th.onclick=()=>{
  const k=th.dataset.k;if(sortK===k)sortDir*=-1;else{sortK=k;sortDir=-1;}renderTable();});
$('#q').oninput=renderTable;
renderTable();
</script>
</body></html>"""


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=DEFAULT_OUT)
    args = ap.parse_args()
    path = export(args.out)
    size = os.path.getsize(path)
    print(f"[static] wrote {path} ({size/1024:.1f} KB)")


if __name__ == "__main__":
    main()
