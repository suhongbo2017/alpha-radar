#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Alpha Radar 静态站点生成器

产出：site/index.html —— **单文件、零依赖、可离线打开、可直接上 GitHub Pages**

设计原则
────────
1. **只读**。站点不提供任何写操作 —— 写操作必须走 alpha_portfolio.py / alpha_ledger.py，
   因为那些命令带 append-only、自动 git 固化、单位/版本校验三层纪律。
   一个"方便"的界面能把这些纪律打穿。
2. **默认不含持仓**。`data/positions.json` 默认**不读**。
   用 `--include-holdings` 才包含，且会在页面上打红标 —— 因为仓库是公开的。
3. **不生成"分析"**。站点只呈现已经写好的档案，不调用 alpha_scenario.py 产生新的"报告"。
   规则级结果会明确标注等级，不与研究级混淆。
4. 零外部依赖（不引 CDN）—— 本机网络受限，且离线可用更重要。

用法:
    py scripts/build_site.py                    # 默认：不含持仓（可公开）
    py scripts/build_site.py --include-holdings # 含持仓（🔴 不要公开）
    py scripts/build_site.py --with-gates       # 同时嵌入最近一次门禁结果
    py scripts/build_site.py --out site/index.html
"""
import argparse
import datetime as dt
import glob
import html
import json
import os
import re
import subprocess
import sys

try:
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
except Exception:
    pass

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(ROOT, "data")
ANALYSIS = os.path.join(ROOT, "analysis")

# 公开站点绝不出现的字符串（构建后断言）
FORBIDDEN = ["positions.json", "market_value", "cost_basis", "unrealized_pnl"]

RULE_MARK = "Bull/Base/Bear 由 `alpha_scenario.py` 的规则生成，不是行业研究结论。"


# ══════════════════════════════════════════════════════════
#  数据读取
# ══════════════════════════════════════════════════════════
def load_jsonl(path):
    if not os.path.exists(path):
        return []
    out = []
    for line in open(path, encoding="utf-8"):
        line = line.strip()
        if line:
            try:
                out.append(json.loads(line))
            except Exception:
                pass
    return out


def latest_by(rows, key="ticker"):
    d = {}
    for r in sorted(rows, key=lambda x: (x.get(key, ""), x.get("analysis_date", ""))):
        d[r.get(key, "").upper()] = r
    return d


def grade_of(text):
    """档案等级：报告级 / 研究级 / 规则级"""
    first = text.splitlines()[0] if text else ""
    if "研究级" in first:
        return "研究级"
    if RULE_MARK in text:
        return "规则级"
    return "报告级"


def parse_dossier(path):
    text = open(path, encoding="utf-8").read()
    ticker = os.path.basename(path).replace("_AlphaRadar.md", "")
    title = (text.splitlines()[0] or "").lstrip("# ").strip()
    # 一句话结论：取 "## 0." 之后第一段引用块
    m = re.search(r"## 0\.[^\n]*\n+(.*?)(?=\n---|\n## )", text, re.S)
    concl = ""
    if m:
        concl = re.sub(r"^>\s?", "", m.group(1), flags=re.M).strip()
    return {"ticker": ticker, "title": title, "grade": grade_of(text),
            "conclusion": concl[:400], "body": text, "path": path,
            "size": len(text)}


# ══════════════════════════════════════════════════════════
#  极简 Markdown → HTML（不依赖任何库）
# ══════════════════════════════════════════════════════════
def esc(s):
    return html.escape(s, quote=False)


def inline(s):
    s = esc(s)
    s = re.sub(r"`([^`]+)`", lambda m: "<code>%s</code>" % m.group(1), s)
    s = re.sub(r"\*\*([^*]+)\*\*", r"<strong>\1</strong>", s)
    s = re.sub(r"(?<!\*)\*([^*\n]+)\*(?!\*)", r"<em>\1</em>", s)
    s = re.sub(r"\[([^\]]+)\]\(([^)]+)\)", r'<a href="\2">\1</a>', s)
    return s


def split_row(line):
    line = line.strip()
    if line.startswith("|"):
        line = line[1:]
    if line.endswith("|"):
        line = line[:-1]
    # 保留转义竖线
    line = line.replace("\\|", "\x00")
    return [c.strip().replace("\x00", "|") for c in line.split("|")]


def md_to_html(md):
    lines = md.split("\n")
    out, i = [], 0
    code, buf, tbl = [], [], []

    def flush_tbl():
        if not tbl:
            return
        head = split_row(tbl[0])
        aligns = []
        if len(tbl) > 1 and re.match(r"^\|?[\s:\-|]+\|?$", tbl[1]):
            for c in split_row(tbl[1]):
                aligns.append("right" if c.endswith(":") and c.startswith(":")
                              else "right" if c.endswith(":")
                              else "center" if c.startswith(":") else "")
            body = tbl[2:]
        else:
            body = tbl[1:]
        h = ['<div class="tw"><table><thead><tr>']
        for j, c in enumerate(head):
            al = (' style="text-align:%s"' % aligns[j]) if j < len(aligns) and aligns[j] else ""
            h.append("<th%s>%s</th>" % (al, inline(c)))
        h.append("</tr></thead><tbody>")
        for r in body:
            h.append("<tr>")
            for j, c in enumerate(split_row(r)):
                al = (' style="text-align:%s"' % aligns[j]) if j < len(aligns) and aligns[j] else ""
                h.append("<td%s>%s</td>" % (al, inline(c)))
            h.append("</tr>")
        h.append("</tbody></table></div>")
        out.append("".join(h))
        tbl.clear()

    def flush_code():
        if code:
            out.append('<pre><code>%s</code></pre>' % esc("\n".join(code)))
            code.clear()

    while i < len(lines):
        ln = lines[i]
        if ln.strip().startswith("```"):
            if code:
                flush_code()
            else:
                flush_tbl()
                code.append("")     # 占位，进入 code 模式
            i += 1
            if code and code[0] == "":
                code.clear()
            continue
        if code or (i > 0 and lines[i - 1].strip().startswith("```") and not ln.strip().startswith("```")):
            code.append(ln)
            i += 1
            continue
        if ln.strip().startswith("|") and ln.strip().endswith("|"):
            tbl.append(ln)
            i += 1
            continue
        flush_tbl()
        if re.match(r"^#{1,6}\s", ln):
            lv = len(ln) - len(ln.lstrip("#"))
            out.append("<h%d>%s</h%d>" % (lv, inline(ln.lstrip("#").strip()), lv))
            i += 1
            continue
        if re.match(r"^\s*([-*_])\1{2,}\s*$", ln):
            out.append("<hr>")
            i += 1
            continue
        if ln.startswith(">"):
            # [D-70] 引用块内部必须递归做**块级**渲染 —— 否则里面的
            # 代码块（```）和列表（-）会以字面文本出现。
            # 实测：APH 档案的"可复现命令" ```bash 块曾原样显示为 ```bash。
            q = []
            while i < len(lines) and (lines[i].startswith(">") or
                                      (not lines[i].strip() and q and
                                       i + 1 < len(lines) and lines[i + 1].startswith(">"))):
                q.append(lines[i][1:] if lines[i].startswith(">") else "")
                i += 1
            out.append("<blockquote>%s</blockquote>" % md_to_html(chr(10).join(q)))
            continue
        m = re.match(r"^(\s*)[-*]\s+(.*)$", ln)
        if m:
            items = []
            while i < len(lines):
                mm = re.match(r"^(\s*)[-*]\s+(.*)$", lines[i])
                if not mm:
                    break
                items.append(inline(mm.group(2)))
                i += 1
            out.append("<ul>%s</ul>" % "".join("<li>%s</li>" % x for x in items))
            continue
        m = re.match(r"^\s*\d+\.\s+(.*)$", ln)
        if m:
            items = []
            while i < len(lines):
                mm = re.match(r"^\s*\d+\.\s+(.*)$", lines[i])
                if not mm:
                    break
                items.append(inline(mm.group(1)))
                i += 1
            out.append("<ol>%s</ol>" % "".join("<li>%s</li>" % x for x in items))
            continue
        if not ln.strip():
            i += 1
            continue
        out.append("<p>%s</p>" % inline(ln))
        i += 1
    flush_tbl()
    flush_code()
    return "\n".join(out)


# ══════════════════════════════════════════════════════════
#  HTML 组装
# ══════════════════════════════════════════════════════════
CSS = """
*{box-sizing:border-box}
:root{
 --bg:#0f1115; --fg:#e6e8ee; --mut:#9aa3b2; --line:#252a34;
 --card:#171a21; --acc:#5b9dff; --ok:#3fb950; --warn:#d29922; --bad:#f85149;
}
@media(prefers-color-scheme:light){:root{
 --bg:#fbfbfd; --fg:#1b1f27; --mut:#5c6473; --line:#e3e6ec;
 --card:#fff; --acc:#0b62d6; --ok:#1a7f37; --warn:#9a6700; --bad:#cf222e;}}
body{margin:0;background:var(--bg);color:var(--fg);
 font:15px/1.7 -apple-system,BlinkMacSystemFont,"Segoe UI","Noto Sans SC","Microsoft YaHei",sans-serif}
header{padding:22px 26px 0;border-bottom:1px solid var(--line);position:sticky;top:0;
 background:var(--bg);z-index:9}
h1{font-size:20px;margin:0 0 4px}
.sub{color:var(--mut);font-size:12.5px;margin-bottom:14px}
nav{display:flex;gap:4px;flex-wrap:wrap}
nav button{background:none;border:none;color:var(--mut);padding:9px 13px;cursor:pointer;
 font:inherit;font-size:13.5px;border-bottom:2px solid transparent}
nav button:hover{color:var(--fg)}
nav button.on{color:var(--acc);border-bottom-color:var(--acc)}
main{padding:22px 26px 60px;max-width:1400px}
section{display:none}section.on{display:block}
.bar{display:flex;gap:10px;flex-wrap:wrap;align-items:center;margin-bottom:14px}
input,select{background:var(--card);border:1px solid var(--line);color:var(--fg);
 padding:7px 11px;border-radius:7px;font:inherit;font-size:13.5px}
input{min-width:230px}
table{border-collapse:collapse;width:100%;font-size:13.5px}
.tw{overflow-x:auto;margin:12px 0}
th,td{padding:8px 11px;border-bottom:1px solid var(--line);text-align:left;vertical-align:top}
th{color:var(--mut);font-weight:600;white-space:nowrap;position:sticky;top:0;background:var(--bg)}
td.num,th.num{text-align:right;font-variant-numeric:tabular-nums}
tr:hover td{background:#ffffff08}
.card{background:var(--card);border:1px solid var(--line);border-radius:11px;
 padding:15px 18px;margin-bottom:13px}
.grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(320px,1fr));gap:13px}
.g{display:inline-block;font-size:11px;padding:2px 7px;border-radius:5px;
 border:1px solid var(--line);color:var(--mut);margin-left:7px;vertical-align:middle}
.g.研究级{color:var(--acc);border-color:var(--acc)}
.g.规则级{color:var(--warn);border-color:var(--warn)}
.g.报告级{color:var(--ok);border-color:var(--ok)}
.pill{display:inline-block;font-size:11.5px;padding:2px 8px;border-radius:20px;
 border:1px solid var(--line);color:var(--mut)}
.pill.ok{color:var(--ok);border-color:var(--ok)}.pill.bad{color:var(--bad);border-color:var(--bad)}
.pill.warn{color:var(--warn);border-color:var(--warn)}
a{color:var(--acc);text-decoration:none}a:hover{text-decoration:underline}
blockquote{margin:12px 0;padding:10px 15px;border-left:3px solid var(--acc);
 background:#5b9dff12;color:var(--fg);border-radius:0 8px 8px 0}
blockquote p{margin:0}
pre{background:var(--card);border:1px solid var(--line);border-radius:9px;
 padding:12px 14px;overflow-x:auto;font-size:12.5px}
code{font-family:ui-monospace,Menlo,Consolas,monospace;font-size:.92em;
 background:#88888822;padding:1px 5px;border-radius:4px}
pre code{background:none;padding:0}
h2{font-size:17px;margin:26px 0 10px;padding-bottom:6px;border-bottom:1px solid var(--line)}
h3{font-size:15px;margin:20px 0 8px}h4{font-size:14px;margin:16px 0 6px;color:var(--mut)}
hr{border:none;border-top:1px solid var(--line);margin:22px 0}
.dossier{max-width:960px}
.meta{color:var(--mut);font-size:12.5px;margin-bottom:10px}
.warnband{border:1px solid var(--bad);background:#f8514912;border-radius:9px;
 padding:11px 15px;margin-bottom:16px;font-size:13.5px}
footer{color:var(--mut);font-size:12px;padding:18px 26px;border-top:1px solid var(--line)}
.kpi{display:grid;grid-template-columns:repeat(auto-fill,minmax(150px,1fr));gap:11px;margin-bottom:18px}
.kpi div{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:11px 14px}
.kpi b{display:block;font-size:20px;font-variant-numeric:tabular-nums}
.kpi span{color:var(--mut);font-size:12px}
"""

JS = """
function tab(id){
  document.querySelectorAll('nav button').forEach(b=>b.classList.toggle('on',b.dataset.t===id));
  document.querySelectorAll('section').forEach(s=>s.classList.toggle('on',s.id==='s-'+id));
  if(history.replaceState)history.replaceState(null,'','#'+id);
  window.scrollTo(0,0);
}
function filt(sec){
  var q=(document.getElementById('q-'+sec)?.value||'').toLowerCase();
  var g=document.getElementById('g-'+sec)?.value||'';
  var rows=document.querySelectorAll('#s-'+sec+' tbody tr, #s-'+sec+' .card');
  var n=0;
  rows.forEach(function(r){
    var t=r.dataset.txt||r.textContent.toLowerCase();
    var ok=(!q||t.indexOf(q)>=0)&&(!g||r.dataset.grade===g);
    r.style.display=ok?'':'none'; if(ok)n++;
  });
  var c=document.getElementById('c-'+sec); if(c)c.textContent=n+' 项';
}
function sortTbl(sec,idx,num){
  var tb=document.querySelector('#s-'+sec+' tbody'); if(!tb)return;
  var rows=Array.from(tb.rows);
  rows.sort(function(a,b){
    var x=a.cells[idx]?.dataset.v??a.cells[idx]?.textContent??'';
    var y=b.cells[idx]?.dataset.v??b.cells[idx]?.textContent??'';
    if(num){x=parseFloat(x)||-1e9;y=parseFloat(y)||-1e9;return y-x;}
    return String(x).localeCompare(String(y));
  });
  rows.forEach(r=>tb.appendChild(r));
}
window.addEventListener('DOMContentLoaded',function(){
  var h=(location.hash||'').replace('#','');
  tab(document.getElementById('s-'+h)?h:'board');
});
"""


def build_board(analyses, prices, holds):
    rows = []
    for t, an in sorted(analyses.items(), key=lambda kv: -(kv[1].get("odds") or -1)):
        h = holds.get(t) if holds else None
        rows.append({"t": t, "an": an, "h": h})
    head = ["Ticker", "基本面", "赔率", "现价", "分析动作", "档案"]
    if holds:
        head = ["Ticker", "基本面", "赔率", "现价", "仓位%", "盈亏%", "分析动作", "一致性", "档案"]
    h = ['<table><thead><tr>']
    for c in head:
        h.append("<th>%s</th>" % c)
    h.append("</tr></thead><tbody>")
    for r in rows:
        an, t = r["an"], r["t"]
        g = ("%.1f" % an["fundamental_score"]) if an.get("fundamental_score") is not None else "—"
        od = ("%.2f" % an["odds"]) if an.get("odds") is not None else "—"
        px = ("%.2f" % an["price"]) if an.get("price") is not None else "—"
        act = an.get("action") or "—"
        cls = "ok" if act in ("Buy", "StrongBuy", "Core", "Starter") else "warn" if act in ("Trim", "Exit") else ""
        h.append("<tr><td><b>%s</b></td>" % t)
        h.append('<td class="num">%s</td><td class="num">%s</td><td class="num">%s</td>' % (g, od, px))
        if holds:
            if r["h"]:
                wp = r["h"].get("weight_pct")
                pnl = r["h"].get("pnl_pct")
                h.append('<td class="num">%s</td><td class="num">%s</td>' % (
                    ("%.1f%%" % wp) if wp is not None else "—",
                    ("%+.1f%%" % pnl) if pnl is not None else "—"))
            else:
                h.append('<td class="num">—</td><td class="num">—</td>')
        h.append('<td><span class="pill %s">%s</span></td>' % (cls, act))
        if holds:
            conflict = r["h"] and an.get("odds") is not None and an["odds"] < 1 and act in ("Watch", "Trim", "Exit")
            h.append('<td>%s</td>' % ('<span class="pill bad">🔴 冲突</span>' if conflict else
                                      ('<span class="pill ok">✅</span>' if r["h"] else
                                       '<span class="pill">未持有</span>')))
        h.append('<td><a href="#%s" onclick="tab(\'doc\');showDoc(\'%s\')">查看</a></td></tr>' % (t, t))
    h.append("</tbody></table>")
    return "".join(h)


def build_preds(preds):
    h = ['<table><thead><tr><th onclick="sortTbl(\'pred\',0)">Ticker</th>'
         '<th onclick="sortTbl(\'pred\',1)">指标</th><th>期间</th><th>情景</th>'
         '<th onclick="sortTbl(\'pred\',4,1)" class="num">预测</th><th>单位</th>'
         '<th class="num">概率</th><th onclick="sortTbl(\'pred\',7)">分析日期</th>'
         '<th>依据</th></tr></thead><tbody>']
    def n(v, u):
        if v is None:
            return "—"
        a = abs(v)
        if u in ("%", "X"):
            return "%.2f" % v
        if a >= 1e12:
            return "%.2fT" % (v / 1e12)
        if a >= 1e9:
            return "%.2fB" % (v / 1e9)
        if a >= 1e6:
            return "%.1fM" % (v / 1e6)
        return "%.2f" % v
    for p in sorted(preds, key=lambda x: (x["ticker"], x["metric"], x["forecast_period"])):
        h.append('<tr><td><b>%s</b></td><td>%s</td><td>%s</td><td>%s</td>'
                 '<td class="num" data-v="%s">%s</td><td>%s</td><td class="num">%s</td>'
                 '<td>%s</td><td style="color:var(--mut);font-size:12px">%s</td></tr>' % (
                     p["ticker"], p["metric"], p["forecast_period"], p["scenario"],
                     p["forecast_value"], n(p["forecast_value"], p.get("unit", "")),
                     p.get("unit", ""),
                     ("%.0f%%" % (p["probability"] * 100)) if p.get("probability") else "—",
                     p.get("analysis_date", ""), esc((p.get("source_basis") or "")[:60])))
    h.append("</tbody></table>")
    return "".join(h)


def build_decisions(decs):
    h = ['<table><thead><tr><th>Ticker</th><th>日期</th><th>动作</th>'
         '<th class="num">决策价</th><th class="num">赔率</th><th>理由</th></tr></thead><tbody>']
    for d in sorted(decs, key=lambda x: (x["ticker"], x["decision_date"])):
        h.append('<tr><td><b>%s</b></td><td>%s</td><td><span class="pill">%s</span></td>'
                 '<td class="num">%.2f</td><td class="num">%s</td>'
                 '<td style="color:var(--mut);font-size:12.5px">%s</td></tr>' % (
                     d["ticker"], d["decision_date"], d["action"], d["price"],
                     ("%.2f" % d["odds"]) if d.get("odds") is not None else "—",
                     esc(d.get("reason") or "")))
    h.append("</tbody></table>")
    return "".join(h)


def main():
    ap = argparse.ArgumentParser(description="生成静态站点")
    ap.add_argument("--out", default=os.path.join(ROOT, "site", "index.html"))
    ap.add_argument("--include-holdings", action="store_true",
                    help="🔴 包含持仓（不要公开部署）")
    ap.add_argument("--with-gates", action="store_true", help="嵌入最近一次门禁结果")
    a = ap.parse_args()

    preds = load_jsonl(os.path.join(DATA, "predictions.jsonl"))
    decs = load_jsonl(os.path.join(DATA, "decisions.jsonl"))
    analyses = latest_by(load_jsonl(os.path.join(DATA, "analyses.jsonl")))

    # ── 持仓：默认不读
    holds = None
    if a.include_holdings:
        pf = os.path.join(DATA, "positions.json")
        if os.path.exists(pf):
            raw = json.load(open(pf, encoding="utf-8"))
            tot = sum(p["qty"] * (p.get("last") or 0) for p in raw["positions"] if p.get("qty"))
            holds = {}
            for p in raw["positions"]:
                if not p.get("qty"):
                    continue
                t = str(p["code"]).split(".")[-1]
                mv = p["qty"] * (p.get("last") or 0)
                holds[t] = {"weight_pct": (mv / tot * 100) if tot else None,
                            "pnl_pct": ((p["last"] / p["avg_cost"] - 1) * 100)
                                       if p.get("avg_cost") else None}

    # ── 档案
    docs = []
    for f in sorted(glob.glob(os.path.join(ANALYSIS, "*_AlphaRadar.md"))):
        docs.append(parse_dossier(f))
    docs.sort(key=lambda d: ({"报告级": 0, "研究级": 1, "规则级": 2}[d["grade"]], d["ticker"]))

    # ── 门禁
    gates = None
    if a.with_gates:
        try:
            r = subprocess.run([sys.executable, "scripts/gates.py", "--all"],
                               cwd=ROOT, capture_output=True, text=True,
                               encoding="utf-8", errors="replace", timeout=1800)
            gates = [l for l in (r.stdout or "").splitlines()
                     if l.startswith("__GATE_") or l.strip().startswith(("G1", "G2", "G3", "G4", "G5", "G6", "G7"))]
        except Exception as e:
            gates = ["门禁执行失败: %s" % e]

    defects = ""
    dp = os.path.join(ROOT, "DEFECTS.md")
    if os.path.exists(dp):
        defects = md_to_html(open(dp, encoding="utf-8").read())

    # ── 文档卡片 + 详情
    cards, details = [], []
    for d in docs:
        tl = d["ticker"].lower()
        cards.append(
            '<div class="card" data-grade="%s" data-txt="%s %s %s">'
            '<div><b>%s</b><span class="g %s">%s</span></div>'
            '<div class="meta">%s</div>'
            '<div style="font-size:13px;color:var(--mut);max-height:5.2em;overflow:hidden">%s</div>'
            '<div style="margin-top:9px"><a href="#%s" onclick="tab(\'doc\');showDoc(\'%s\')">打开档案 →</a></div>'
            "</div>" % (d["grade"], esc(d["ticker"]), esc(d["title"]), esc(d["conclusion"][:120]),
                        d["ticker"], d["grade"], d["grade"],
                        esc(d["title"].split("（", 1)[-1].rstrip("）"))[:60],
                        esc(d["conclusion"][:150]), d["ticker"], d["ticker"]))
        details.append(
            '<div id="doc-%s" class="dossier" style="display:none">%s</div>'
            % (d["ticker"], md_to_html(d["body"])))

    # ── 组合统计
    odds_ok = [t for t, x in analyses.items() if (x.get("odds") or 0) >= 1]
    n_doc = {"报告级": 0, "研究级": 0, "规则级": 0}
    for d in docs:
        n_doc[d["grade"]] += 1

    htmlout = """<!doctype html><html lang="zh-CN"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Alpha Radar</title><style>%s</style></head><body>
<header>
<h1>🛰️ Alpha Radar</h1>
<div class="sub">多维投资研究与决策系统　·　生成于 %s
%s</div>
<nav>
<button data-t="board" onclick="tab('board')">组合雷达</button>
<button data-t="doc" onclick="tab('doc')">公司档案 (%d)</button>
<button data-t="pred" onclick="tab('pred')">预测账本 (%d)</button>
<button data-t="dec" onclick="tab('dec')">决策记录 (%d)</button>
<button data-t="defect" onclick="tab('defect')">缺陷登记册</button>
<button data-t="method" onclick="tab('method')">方法论</button>
</nav></header>
<main>
<section id="s-board">
%s
<div class="kpi">
<div><b>%d</b><span>已建档公司</span></div>
<div><b>%d</b><span>报告级</span></div>
<div><b>%d</b><span>研究级</span></div>
<div><b>%d</b><span>规则级</span></div>
<div><b>%d</b><span>赔率 ≥1</span></div>
<div><b>%d</b><span>已登记预测</span></div>
</div>
<h2>分析结论</h2>
<div class="bar"><input id="q-board" placeholder="搜索 ticker…" oninput="filt('board')">
<span class="pill" id="c-board"></span></div>
%s
</section>
<section id="s-doc">
<div class="bar">
<input id="q-doc" placeholder="搜索公司名 / 结论关键词…" oninput="filt('doc')">
<select id="g-doc" onchange="filt('doc')">
<option value="">全部等级</option><option>报告级</option><option>研究级</option><option>规则级</option>
</select><span class="pill" id="c-doc"></span></div>
<div class="grid" id="docgrid">%s</div>
<div id="docview" style="display:none"><div class="bar">
<button class="pill" onclick="tab('doc')">← 返回列表</button></div>%s</div>
</section>
<section id="s-pred">
<div class="bar"><input id="q-pred" placeholder="搜索 ticker / 指标…" oninput="filt('pred')">
<span class="pill" id="c-pred"></span></div>
%s
</section>
<section id="s-dec"><h2>决策记录</h2><p style="color:var(--mut);font-size:13px">
> 赔率 &lt;1:1 时任何价位都不建仓。决策 append-only，改主意记新的一条。</p>%s</section>
<section id="s-defect"><h2>缺陷登记册</h2>
<p style="color:var(--mut);font-size:13px">与预测账本同一条铁律：<b>旧记录永不覆盖</b>。
修复后只更新状态并追加小节，不删除原始描述。</p>%s</section>
<section id="s-method"><h2>方法论</h2>
<div class="card"><h3>五模块闭环</h3>
<pre>基本面引擎 → 估值引擎 → 决策引擎 → 预测账本 → 复盘引擎</pre>
<h3>九条铁律</h3>
<ol>
<li>先基本面，后估值</li><li>先预测企业价值，再看股价</li>
<li>股价下跌 ≠ 加仓理由；股价上涨 ≠ 卖出理由</li>
<li>价格变化与基本面变化必须分开记账</li>
<li><b>旧预测永不覆盖</b>（append-only）</li>
<li>每个数字必须有来源与数据截点</li>
<li>预测错误必须归因</li><li>投资逻辑失效比股价下跌更值得行动</li>
<li>目标不是提高预测命中率，而是提高长期风险调整后收益</li>
</ol>
<h3>三类档案的等级（不得混淆）</h3>
<table><thead><tr><th>等级</th><th>情景来源</th><th>能否登记预测</th><th>典型动作</th></tr></thead><tbody>
<tr><td><span class="g 报告级">报告级</span></td><td>Bottom-Up 行业研究支撑</td><td>✅ 可以</td><td>Watch/Buy/Hold</td></tr>
<tr><td><span class="g 研究级">研究级</span></td><td>以一致预期为锚 + 显式折扣假设</td><td>✅ 可以</td><td>Hold/Buy/Trim</td></tr>
<tr><td><span class="g 规则级">规则级</span></td><td>机械规则（只看规模+增速+杠杆）</td><td>❌ <b>不可以</b></td><td>Watch（需研究后再决策）</td></tr>
</tbody></table>
<blockquote>规则只看「市值规模 + TTM 增速 + 杠杆 + 是否烧钱」，<b>完全不看行业地位、竞争格局、技术路线或管理层</b>。
实测它把 NVDA 与 GOOGL 按同一增速上限处理。用它产生的赔率，实测与完整分析可差 <b>4 倍</b>（ORCL：0.65 vs 2.71）。</blockquote>
<h3>七道门禁</h3>
<pre>G1 账本回归(63项)  G2 skill同步  G3 数据完整性  G4 语法
G5 文档-CLI漂移   G6 账本已固化进git  G7 一手数据多层校验</pre>
<h3>四层数据校验</h3>
<pre>L1 会计恒等式      Revenue − COGS = GrossProfit
L2 时间一致性      双路TTM / YTD最长时长 / 净债务独立重算 / 一次性项侦测
L3 交叉来源        SEC vs 第三方 同一日期逐项比对
L4 量纲合理性</pre>
<blockquote><b>交叉校验的有效性上限 = 两条路径的独立性。</b>
共享原语的"双路验证"是自欺 —— 实测注入目标 bug 后仍全绿。</blockquote>
</div>
%s
</section>
</main>
<footer>Alpha Radar · 本页由 <code>py scripts/build_site.py</code> 生成 · 只读快照，不含任何写操作
%s</footer>
<script>%s
function showDoc(t){
  ['docgrid','docview'].forEach(function(id,i){
    document.getElementById(id).style.display=i?'':'none';});
  document.querySelectorAll('.dossier').forEach(d=>d.style.display='none');
  var e=document.getElementById('doc-'+t); if(e)e.style.display='';
  var g=document.querySelector('#s-doc .bar'); 
  document.querySelectorAll('#docview').forEach(function(v){});
}
</script>
</body></html>""" % (
        CSS, dt.datetime.now().strftime("%Y-%m-%d %H:%M"),
        ('<span class="pill bad">🔴 含持仓数据 — 请勿公开部署</span>' if holds
         else '<span class="pill ok">不含持仓数据 · 可公开</span>'),
        len(docs), len(preds), len(decs),
        ('<div class="warnband">🔴 <b>本页含真实持仓数据</b>（仓位% / 盈亏%）。'
         '仓库是<b>公开</b>的 —— <b>不要部署到公网</b>。'
         '要生成可公开版本，去掉 <code>--include-holdings</code> 重新构建。</div>' if holds else ''),
        len(docs), n_doc["报告级"], n_doc["研究级"], n_doc["规则级"],
        len(odds_ok), len(preds),
        build_board(analyses, None, holds),
        "".join(cards), "".join(details),
        build_preds(preds), build_decisions(decs), defects,
        ("<h2>最近一次门禁</h2><pre>%s</pre>" % esc("\n".join(gates))) if gates else "",
        ("<br>⚠️ 含持仓" if holds else ""),
        JS)

    # ── 安全断言
    if not a.include_holdings:
        for bad in ("market_value", "cost_basis", "unrealized_pnl", "avg_cost"):
            if bad in htmlout:
                print("✗ 构建中止：输出中含持仓字段 '%s'" % bad)
                return 1

    os.makedirs(os.path.dirname(a.out), exist_ok=True)
    with open(a.out, "w", encoding="utf-8") as f:
        f.write(htmlout)
    kb = os.path.getsize(a.out) / 1024
    try:
        _rel = os.path.relpath(a.out, ROOT)
    except ValueError:           # 输出在另一个盘（如 /tmp → C:）
        _rel = a.out
    print("✓ %s（%.0f KB）" % (_rel, kb))
    print("  档案 %d（报告级 %d / 研究级 %d / 规则级 %d）｜预测 %d ｜决策 %d"
          % (len(docs), n_doc["报告级"], n_doc["研究级"], n_doc["规则级"], len(preds), len(decs)))
    print("  持仓数据：%s" % ("🔴 已包含（勿公开）" if holds else "✓ 未包含（可公开）"))
    return 0


if __name__ == "__main__":
    sys.exit(main())