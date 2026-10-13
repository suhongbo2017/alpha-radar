#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Alpha Radar 静态站点生成器

产出：site/index.html —— **单文件、零依赖、可离线打开、可直接上 GitHub Pages**

设计原则
────────
1. **只读**。站点不提供任何写操作 —— 写操作必须走 alpha_portfolio.py / alpha_ledger.py，
   因为那些命令带 append-only、自动 git 固化、单位/版本校验三层纪律。
   一个"方便"的界面能把这些纪律打穿。
2. **持仓分两级敏感度**（[D-73]）：
   `data/holdings.json` —— **只含标的**，可入库可公开，站点**默认读它**，
   用来判断"持有/未持有"与"持仓 vs 分析结论是否冲突"。
   `data/positions.json` —— 含数量/成本/盈亏，**仅本地**（gitignored），
   需 `--include-holdings` 才读，且页面会打红标。
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
# [D-73] 公开站点绝不出现的**数据字段**（数量类一律禁止）
#
# 注意：**不要把文件名 "positions.json" 放进来**。
# 文档正文里合法地会提到它（D-73 的说明写明了"positions.json 仅本地"），
# 那是说明文字，不是数据泄漏 —— 把它当禁用词会产生假警报（实测踩过）。
# 真正的保护是：① 下面这些**字段名**；② 默认代码路径根本不读那个文件。
FORBIDDEN = ["market_value", "cost_basis", "unrealized_pnl",
             "realized_pnl", "avg_cost", '"qty"', "shares"]

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


def _is_num(cell):
    """单元格是否数字（**先剥掉 markdown 记号**，否则 **$445.87B** 判不出来）"""
    t = re.sub(r"[*`\s]", "", cell)
    if not t or t in ("—", "-", "–", "n/a", "N/A", "?"):
        return False
    t = t.replace("%", "").replace("$", "").replace(",", "").replace("+", "")
    t = t.replace("−", "-").replace("≈", "").replace("~", "").replace("x", "")
    for u in ("B", "M", "K", "T", "bp", "pp", "倍"):
        t = t.replace(u, "")
    try:
        float(t)
        return True
    except ValueError:
        return False


def _num_cols(head, body):
    """判断哪些列是数字列：≥60% 的单元格是数字"""
    out = set()
    for j in range(len(head)):
        vals = []
        for r in body:
            cs = split_row(r)
            if len(cs) > j:
                vals.append(cs[j])
        if vals and sum(1 for v in vals if _is_num(v)) >= max(1, len(vals) * 0.6):
            out.add(j)
    return out


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
        # [D-80] 数字列必须同时拿到「右对齐」和「等宽数字（tabular-nums）」。
        # 只右对齐不够 —— 数字字形宽度不等（"1" 比 "0" 窄），小数点对不齐，
        # 看起来仍然是"没对齐"。class="num" 同时提供两者。
        has_marker = bool(aligns) and any(aligns)
        autocols = set() if has_marker else _num_cols(head, body)

        def _attr(j):
            if j < len(aligns) and aligns[j]:
                return ' class="num"' if aligns[j] == "right" else                        ' style="text-align:%s"' % aligns[j]
            if j in autocols:
                return ' class="num"'
            return ""

        h = ['<div class="tw"><table><thead><tr>']
        for j, c in enumerate(head):
            h.append("<th%s>%s</th>" % (_attr(j), inline(c)))
        h.append("</tr></thead><tbody>")
        for r in body:
            h.append("<tr>")
            for j, c in enumerate(split_row(r)):
                h.append("<td%s>%s</td>" % (_attr(j), inline(c)))
            h.append("</tr>")
        h.append("</tbody></table></div>")
        out.append("".join(h))
        tbl.clear()

    def flush_code():
        if code:
            out.append('<pre><code>%s</code></pre>' % esc("\n".join(code)))
            code.clear()

    # [D-80] 显式维护 in_code 状态。
    #
    # 旧实现用一个"上一行是否为 ```"的启发式判断是否在代码块内 —— 它**无法区分
    # 开 fence 与闭 fence**。实测后果：
    #     行56 '```'  闭合 → code 被清空
    #     行57 ''     因"上一行是 ```"被追加进 code
    #     行58+       之后所有行（**包括 5 张表格**）全被吞进 <pre>
    #   GOOGL 档案 7 张表只渲染出 2 张，另外 5 张**在页面上彻底消失**。
    #   这类"数据静默消失"是最难被发现的缺陷 —— 页面不报错，只是少了东西。
    in_code = False
    while i < len(lines):
        ln = lines[i]
        if ln.strip().startswith("```"):
            if in_code:
                out.append('<pre><code>%s</code></pre>' % esc(chr(10).join(code)))
                code.clear()
                in_code = False
            else:
                flush_tbl()
                in_code = True
            i += 1
            continue
        if in_code:
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
 --bg:#f4f7f5; --surface:#ffffff; --surface-soft:#edf3ef; --fg:#18302b; --mut:#667873;
 --line:#d8e4de; --line-strong:#c3d4cc; --acc:#16735f; --acc-strong:#0f5a4b; --acc-soft:#e2f0eb;
 --ok:#24754a; --ok-soft:#e6f3ea; --warn:#9a6812; --warn-soft:#fff4dc; --bad:#b7423c; --bad-soft:#fbe9e7;
 --shadow:0 12px 32px rgba(27,63,51,.07); --shadow-sm:0 3px 12px rgba(27,63,51,.06);
}
@media(prefers-color-scheme:dark){:root{
 --bg:#121a19; --surface:#192522; --surface-soft:#20302b; --fg:#e8f1ed; --mut:#9cb0a8;
 --line:#2b3d37; --line-strong:#3a5048; --acc:#65c4a6; --acc-strong:#8ad7bd; --acc-soft:#183c32;
 --ok:#79cf9b; --ok-soft:#193a2a; --warn:#e6b95f; --warn-soft:#443717; --bad:#f28c83; --bad-soft:#452523;
 --shadow:0 14px 34px rgba(0,0,0,.22); --shadow-sm:0 4px 14px rgba(0,0,0,.18);
}}
html{scroll-behavior:smooth}
body{margin:0;background:var(--bg);color:var(--fg);font:15px/1.7 -apple-system,BlinkMacSystemFont,"Segoe UI","Noto Sans SC","Microsoft YaHei",sans-serif;letter-spacing:0}
header{padding:18px clamp(18px,4vw,56px) 0;border-bottom:1px solid var(--line);position:sticky;top:0;
 background:color-mix(in srgb,var(--bg) 94%,transparent);backdrop-filter:blur(14px);z-index:9}
.brandrow{display:flex;justify-content:space-between;gap:20px;align-items:flex-start;max-width:1480px;margin:0 auto}
h1{font-size:23px;line-height:1.2;letter-spacing:0;margin:0 0 4px;font-weight:760;color:var(--fg)}
.brandmark{display:flex;align-items:center;gap:10px}.brandmark .mark{display:grid;place-items:center;width:34px;height:34px;border-radius:10px;background:var(--acc);color:#fff;font-size:17px;box-shadow:var(--shadow-sm)}
.sub{color:var(--mut);font-size:12.5px;margin-bottom:14px}
.header-status{display:flex;gap:8px;align-items:center;flex-wrap:wrap;justify-content:flex-end;padding-top:2px}
nav{display:flex;gap:3px;flex-wrap:wrap;max-width:1480px;margin:0 auto}
nav button{appearance:none;background:none;border:0;border-bottom:2px solid transparent;color:var(--mut);padding:10px 14px;cursor:pointer;
 font:inherit;font-size:13px;font-weight:650;letter-spacing:0;transition:color .18s,border-color .18s,background .18s;border-radius:7px 7px 0 0}
nav button:hover{color:var(--fg);background:var(--surface-soft)}
nav button:focus-visible,.btn:focus-visible,input:focus-visible,select:focus-visible,a:focus-visible{outline:3px solid color-mix(in srgb,var(--acc) 32%,transparent);outline-offset:2px}
nav button.on{color:var(--acc-strong);border-bottom-color:var(--acc);background:var(--acc-soft)}
main{padding:30px clamp(18px,4vw,56px) 72px;max-width:1590px;margin:0 auto}
section{display:none}section.on{display:block}
.board-intro{display:flex;justify-content:space-between;align-items:flex-end;gap:28px;margin:0 0 24px;padding:4px 0 22px;border-bottom:1px solid var(--line)}
.eyebrow{color:var(--acc);font-size:11px;font-weight:800;letter-spacing:.12em;text-transform:uppercase;margin:0 0 7px}
.board-intro h2{border:0;padding:0;margin:0 0 4px;font-size:28px;line-height:1.2;letter-spacing:0}.board-intro p{margin:0;color:var(--mut);max-width:690px;font-size:14px}
.intro-note{max-width:300px;padding:12px 14px;border-left:3px solid var(--acc);background:var(--surface-soft);color:var(--mut);font-size:12.5px}
.bar{display:flex;gap:9px;flex-wrap:wrap;align-items:center;margin:0 0 16px}
input,select{appearance:none;background:var(--surface);border:1px solid var(--line-strong);color:var(--fg);padding:9px 12px;border-radius:8px;font:inherit;font-size:13px;box-shadow:var(--shadow-sm)}
input{min-width:250px}input::placeholder{color:var(--mut)}select{padding-right:32px;background-image:linear-gradient(45deg,transparent 50%,var(--mut) 50%),linear-gradient(135deg,var(--mut) 50%,transparent 50%);background-position:calc(100% - 16px) 54%,calc(100% - 11px) 54%;background-size:5px 5px,5px 5px;background-repeat:no-repeat}
.tw{overflow:auto;margin:14px 0;border:1px solid var(--line);border-radius:10px;background:var(--surface);box-shadow:var(--shadow-sm)}
table{border-collapse:collapse;width:100%;font-size:13px;min-width:640px}th,td{padding:11px 13px;border-bottom:1px solid var(--line);text-align:left;vertical-align:top}tbody tr:last-child td{border-bottom:0}
th{color:var(--mut);font-size:11px;font-weight:800;letter-spacing:.06em;text-transform:uppercase;white-space:nowrap;position:sticky;top:0;background:var(--surface);z-index:1}th[onclick]{cursor:pointer}th[onclick]:hover{color:var(--acc)}td.num,th.num{text-align:right;font-variant-numeric:tabular-nums}tbody tr:hover td{background:var(--surface-soft)}
.card{background:var(--surface);border:1px solid var(--line);border-radius:10px;padding:18px 19px;margin-bottom:13px;box-shadow:var(--shadow-sm)}
.grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(300px,1fr));gap:14px}.grid .card{height:100%;margin:0;display:flex;flex-direction:column}.grid .card>div:last-child{margin-top:auto!important;padding-top:14px}
.g{display:inline-block;font-size:10px;font-weight:750;padding:2px 7px;border-radius:5px;border:1px solid var(--line-strong);color:var(--mut);margin-left:7px;vertical-align:middle}.g.研究级{color:var(--acc);border-color:var(--acc)}.g.规则级{color:var(--warn);border-color:var(--warn)}.g.报告级{color:var(--ok);border-color:var(--ok)}
.pill{display:inline-flex;align-items:center;min-height:24px;font-size:11px;font-weight:650;padding:2px 9px;border-radius:999px;border:1px solid var(--line-strong);color:var(--mut);background:var(--surface)}
.pill.ok{color:var(--ok);border-color:color-mix(in srgb,var(--ok) 48%,var(--line));background:var(--ok-soft)}.pill.bad{color:var(--bad);border-color:color-mix(in srgb,var(--bad) 48%,var(--line));background:var(--bad-soft)}.pill.warn{color:var(--warn);border-color:color-mix(in srgb,var(--warn) 48%,var(--line));background:var(--warn-soft)}
.btn{appearance:none;border:1px solid var(--line-strong);background:var(--surface);color:var(--fg);cursor:pointer;padding:7px 12px;border-radius:7px;font:inherit;font-size:12.5px;font-weight:650;box-shadow:var(--shadow-sm)}.btn:hover{border-color:var(--acc);color:var(--acc-strong);background:var(--acc-soft)}
a{color:var(--acc-strong);text-decoration:none;font-weight:650}a:hover{text-decoration:underline}
blockquote{margin:16px 0;padding:12px 16px;border-left:3px solid var(--acc);background:var(--acc-soft);color:var(--fg);border-radius:0 8px 8px 0}blockquote p{margin:0}
pre{background:var(--surface-soft);border:1px solid var(--line);border-radius:8px;padding:13px 15px;overflow:auto;font-size:12px;line-height:1.6;color:var(--fg)}
code{font-family:ui-monospace,Menlo,Consolas,monospace;font-size:.92em;background:var(--surface-soft);padding:1px 5px;border-radius:4px}pre code{background:none;padding:0}
h2{font-size:19px;line-height:1.3;margin:34px 0 12px;padding-bottom:9px;border-bottom:1px solid var(--line);letter-spacing:0}h3{font-size:16px;line-height:1.35;margin:23px 0 9px}h4{font-size:14px;margin:18px 0 7px;color:var(--mut)}hr{border:0;border-top:1px solid var(--line);margin:24px 0}
.dossier{max-width:1000px}.dossier h1{font-size:28px}.dossier h2{margin-top:32px}.meta{color:var(--mut);font-size:12.5px;margin-bottom:10px}.warnband{border:1px solid color-mix(in srgb,var(--bad) 56%,var(--line));background:var(--bad-soft);color:var(--fg);border-radius:9px;padding:12px 15px;margin-bottom:19px;font-size:13px}
footer{color:var(--mut);font-size:12px;padding:20px clamp(18px,4vw,56px);border-top:1px solid var(--line);max-width:none}.kpi{display:grid;grid-template-columns:repeat(6,minmax(125px,1fr));gap:12px;margin-bottom:29px}.kpi div{background:var(--surface);border:1px solid var(--line);border-radius:10px;padding:14px 15px;box-shadow:var(--shadow-sm)}.kpi b{display:block;font-size:24px;line-height:1.15;font-variant-numeric:tabular-nums;color:var(--fg)}.kpi span{display:block;color:var(--mut);font-size:11px;margin-top:5px;font-weight:650}
.section-kicker{display:flex;justify-content:space-between;align-items:center;gap:12px}.section-kicker h2{flex:1}.muted{color:var(--mut)!important}.action-link{display:inline-flex;align-items:center;gap:5px}.empty{padding:28px;text-align:center;color:var(--mut);background:var(--surface);border:1px dashed var(--line-strong);border-radius:10px}
@media(max-width:900px){.kpi{grid-template-columns:repeat(3,minmax(120px,1fr))}.board-intro{align-items:flex-start;flex-direction:column}.intro-note{max-width:none;width:100%;box-sizing:border-box}.header-status{display:none}}
@media(max-width:600px){header{padding:15px 14px 0}.brandrow{display:block}.sub{margin-bottom:10px}nav{overflow-x:auto;flex-wrap:nowrap;margin:0 -4px;padding-bottom:1px}nav button{flex:0 0 auto;padding:9px 11px;font-size:12px}main{padding:23px 14px 52px}.board-intro h2{font-size:24px}.kpi{grid-template-columns:repeat(2,minmax(0,1fr));gap:9px}.kpi div{padding:12px}.kpi b{font-size:21px}.grid{grid-template-columns:1fr}input{min-width:0;width:100%}.bar input{flex:1 1 100%}.dossier h1{font-size:24px}}
"""

A11Y_CSS = r"""
/* ══════════════════════════════════════════════════════════════
   [D-76] 无障碍层 —— 面向视力不佳者
   ──────────────────────────────────────────────────────────────
   改造前实测的可读性问题：
     字号：11 个文字元素里 10 个 ≤13px（table 13 / th 11 / pill 11 / .g 10 / pre 12 …）
     对比度：浅色主题 --mut 在 --bg 上仅 4.33:1，**低于 WCAG AA 的 4.5**
     行宽：main 1590px ÷ 15px ≈ 106 字/行，远超中文建议的 ≤40 字/行
   本层不改原配色与布局，只做四件事：
     ① 用 --fs 统一放大并让用户可调（A−/A+/重置，存 localStorage）
     ② 修正不达标对比度
     ③ 收窄正文行宽（表格保持满宽可横向滚动）
     ④ 高对比度模式开关
   ══════════════════════════════════════════════════════════════ */
:root{ --fs:19px; --lh:1.9; }

/* ① 字号：全部随 --fs 缩放 */
body{font-size:var(--fs);line-height:var(--lh)}
h1{font-size:calc(var(--fs)*1.32)}
.sub{font-size:calc(var(--fs)*0.80);line-height:1.6}
nav button{font-size:calc(var(--fs)*0.86);font-weight:700;padding:13px 17px;min-height:48px}
table{font-size:calc(var(--fs)*0.88)}
th{font-size:calc(var(--fs)*0.80);letter-spacing:.02em}
td,th{padding:14px 16px}
.pill{font-size:calc(var(--fs)*0.80);min-height:32px;padding:5px 13px}
.g{font-size:calc(var(--fs)*0.80);padding:3px 10px;font-weight:800}
pre{font-size:calc(var(--fs)*0.82);line-height:1.75;padding:16px 18px}
code{font-size:.94em;padding:2px 6px}
h2{font-size:calc(var(--fs)*1.20);margin:40px 0 15px;padding-bottom:11px}
h3{font-size:calc(var(--fs)*1.05);margin:26px 0 11px}
h4{font-size:calc(var(--fs)*0.95)}
.meta,.intro-note,.warnband{font-size:calc(var(--fs)*0.82);line-height:1.7}
footer{font-size:calc(var(--fs)*0.80);line-height:1.7}
.kpi b{font-size:calc(var(--fs)*1.72);line-height:1.2}
.kpi span{font-size:calc(var(--fs)*0.80);font-weight:700}
.kpi div{padding:17px 18px}
.eyebrow{font-size:calc(var(--fs)*0.80);letter-spacing:.08em}
.board-intro h2{font-size:calc(var(--fs)*1.50)}
.board-intro p{font-size:calc(var(--fs)*0.88);line-height:1.75;max-width:56ch}
input,select{font-size:calc(var(--fs)*0.88);padding:12px 15px;min-height:48px}
input{min-width:290px}
.btn{font-size:calc(var(--fs)*0.84);padding:10px 16px;min-height:44px}
p,li{line-height:var(--lh)}
.dossier h1{font-size:calc(var(--fs)*1.45)}
.dossier h2{font-size:calc(var(--fs)*1.20)}
ul,ol{padding-left:1.6em}
li{margin:.35em 0}

/* ② 对比度：浅色次要文字 4.33:1 → 达标 */
:root{--mut:#4a5a55}
@media(prefers-color-scheme:dark){:root{--mut:#b4c6be}}

/* ③ 行宽与排版（[D-77] 修）
   ─────────────────────────────────────────────────────────────
   上一版把行宽限制（max-width:52ch ≈ 540px）加到了 **.dossier 容器**上。
   但容器里还有**表格**（min-width:640px）→ 表格被压到必须横向滚动，
   整页内容挤成窄窄一条。这是把"限制正文"错加到"容器"的典型错误。

   正确做法：
     · 把宽度与居中放在**包裹层 #docview** 上（它只包档案，不包其它内容）
     · 容器要够宽放表格；正文靠容器宽度自然形成合理行宽
     · 表格不再强制 min-width，避免中等屏幕上被压出横向滚动条
   ───────────────────────────────────────────────────────────── */
#docview{max-width:1160px;margin:0 auto}
.dossier{max-width:none}
.dossier .tw{max-width:100%;overflow-x:auto}
table{min-width:520px}
main{max-width:1680px}


/* 表格可读性：斑马纹 + 数字不换行 */
tbody tr:nth-child(even) td{background:color-mix(in srgb,var(--surface-soft) 60%,var(--surface))}
tbody tr:nth-child(even):hover td,tbody tr:hover td{background:var(--surface-soft)}
td.num,th.num{white-space:nowrap}
th{position:sticky;top:0}

/* ④ 高对比度模式 */
html.hc{--bg:#ffffff;--surface:#ffffff;--surface-soft:#eef2f0;--fg:#000000;--mut:#1f2b27;
  --line:#000000;--line-strong:#000000;--acc:#00453a;--acc-strong:#003329;--acc-soft:#dff0ea;
  --ok:#0a4d24;--bad:#8a1d17;--warn:#6b4700;--shadow:none;--shadow-sm:none}
html.hc a{text-decoration:underline}
html.hc .tw,html.hc .card{border-width:2px}
@media(prefers-color-scheme:dark){
  html.hc{--bg:#000000;--surface:#000000;--surface-soft:#141414;--fg:#ffffff;--mut:#d8d8d8;
    --line:#ffffff;--line-strong:#ffffff;--acc:#7ff0cf;--acc-strong:#a6f7de;--acc-soft:#0d2b24}
}

/* 字号控件 */
.a11y{display:flex;gap:5px;align-items:center}
.a11y button{appearance:none;background:var(--surface);border:1px solid var(--line-strong);
  color:var(--fg);cursor:pointer;min-width:44px;min-height:44px;padding:0 11px;border-radius:8px;
  font:inherit;font-size:calc(var(--fs)*0.84);font-weight:800;box-shadow:var(--shadow-sm)}
.a11y button:hover{border-color:var(--acc);color:var(--acc-strong);background:var(--acc-soft)}
 .a11y .lbl{color:var(--mut);font-size:calc(var(--fs)*0.72);font-weight:700;margin-right:3px}

/* 原先用内联 font-size 的两处 → 改为类，**随 --fs 缩放**
   （实测：内联固定 12px/13px 会绕开无障碍层，比周围文字小一大截） */
.cell-note{color:var(--mut);font-size:calc(var(--fs)*0.82);line-height:1.6}
.card-conclusion{color:var(--mut);font-size:calc(var(--fs)*0.86);line-height:1.65;
  display:-webkit-box;-webkit-line-clamp:4;-webkit-box-orient:vertical;overflow:hidden}

/* ④ 卡片与 KPI 的栅格在放大字号后要跟着变宽，否则内容被挤 */
.grid{grid-template-columns:repeat(auto-fill,minmax(400px,1fr))}
.kpi{grid-template-columns:repeat(6,minmax(155px,1fr))}
@media(max-width:1100px){.kpi{grid-template-columns:repeat(3,minmax(140px,1fr))}}
@media(max-width:700px){.grid{grid-template-columns:1fr}.kpi{grid-template-columns:repeat(2,minmax(0,1fr))}}

/* 兜底：可读性下限 —— 对视力不佳者，任何文字都不应低于约 15px。
   用 --fs 调大时下限同步抬高（0.79 × 19px ≈ 15px）。 */
table,th,td,.pill,.g,.kpi span,.sub,.meta,pre,footer,.eyebrow,nav button,input,select,.btn{
  font-size:max(calc(var(--fs)*var(--lo,0.79)), 15px)}

@media(prefers-reduced-motion:reduce){html{scroll-behavior:auto}
  *{transition:none!important;animation:none!important}}
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
  ['board','doc','pred'].forEach(filt);
});
"""


def build_board(analyses, prices, holds):
    rows = []
    for t, an in sorted(analyses.items(), key=lambda kv: -(kv[1].get("odds") or -1)):
        h = holds.get(t) if holds else None
        rows.append({"t": t, "an": an, "h": h})
    head = ["Ticker", "基本面", "赔率", "现价", "分析动作", "档案"]
    granular = bool(holds) and any(v.get("weight_pct") is not None for v in holds.values())
    if holds:
        head = (["Ticker", "基本面", "赔率", "现价", "仓位%", "盈亏%", "分析动作", "一致性", "档案"]
                if granular else
                ["Ticker", "基本面", "赔率", "现价", "是否持有", "分析动作", "一致性", "档案"])
    numeric_headers = {"基本面", "赔率", "现价", "仓位%", "盈亏%"}
    h = ['<table><thead><tr>']
    for c in head:
        cls = ' class="num"' if c in numeric_headers else ''
        h.append("<th%s>%s</th>" % (cls, c))
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
            if granular:
                if r["h"]:
                    wp = r["h"].get("weight_pct")
                    pnl = r["h"].get("pnl_pct")
                    h.append('<td class="num">%s</td><td class="num">%s</td>' % (
                        ("%.1f%%" % wp) if wp is not None else "—",
                        ("%+.1f%%" % pnl) if pnl is not None else "—"))
                else:
                    h.append('<td class="num">—</td><td class="num">—</td>')
            else:
                h.append('<td>%s</td>' % ('<span class="pill">持有</span>' if r["h"] else "—"))
        h.append('<td><span class="pill %s">%s</span></td>' % (cls, act))
        if holds:
            conflict = r["h"] and an.get("odds") is not None and an["odds"] < 1 and act in ("Watch", "Trim", "Exit")
            h.append('<td>%s</td>' % ('<span class="pill bad">🔴 冲突</span>' if conflict else
                                      ('<span class="pill ok">✅</span>' if r["h"] else
                                       '<span class="pill">未持有</span>')))
        h.append('<td><a href="#%s" class="action-link" onclick="tab(\'doc\');showDoc(\'%s\');return false">查看 →</a></td></tr>' % (t, t))
    h.append("</tbody></table>")
    return '<div class="tw">%s</div>' % "".join(h)


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
                 '<td>%s</td><td class="cell-note">%s</td></tr>' % (
                     p["ticker"], p["metric"], p["forecast_period"], p["scenario"],
                     p["forecast_value"], n(p["forecast_value"], p.get("unit", "")),
                     p.get("unit", ""),
                     ("%.0f%%" % (p["probability"] * 100)) if p.get("probability") else "—",
                     p.get("analysis_date", ""), esc((p.get("source_basis") or "")[:60])))
    h.append("</tbody></table>")
    return '<div class="tw">%s</div>' % "".join(h)


def build_decisions(decs):
    h = ['<table><thead><tr><th>Ticker</th><th>日期</th><th>动作</th>'
         '<th class="num">决策价</th><th class="num">赔率</th><th>理由</th></tr></thead><tbody>']
    for d in sorted(decs, key=lambda x: (x["ticker"], x["decision_date"])):
        h.append('<tr><td><b>%s</b></td><td>%s</td><td><span class="pill">%s</span></td>'
                 '<td class="num">%.2f</td><td class="num">%s</td>'
                 '<td class="cell-note">%s</td></tr>' % (
                     d["ticker"], d["decision_date"], d["action"], d["price"],
                     ("%.2f" % d["odds"]) if d.get("odds") is not None else "—",
                     esc(d.get("reason") or "")))
    h.append("</tbody></table>")
    return '<div class="tw">%s</div>' % "".join(h)


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
    # [D-73] 默认读【只含标的】的清单（可公开）；--include-holdings 才读含数量的本地快照
    holds = {}
    hj = os.path.join(DATA, "holdings.json")
    if os.path.exists(hj):
        try:
            _h = json.load(open(hj, encoding="utf-8"))
            holds = {str(t).upper(): {"weight_pct": None, "pnl_pct": None}
                     for t in _h.get("tickers", [])}
        except Exception:
            holds = {}
    if a.include_holdings:
        pf = os.path.join(DATA, "positions.json")
        if os.path.exists(pf):
            raw = json.load(open(pf, encoding="utf-8"))
            tot = sum(p["qty"] * (p.get("last") or 0) for p in raw["positions"] if p.get("qty"))
            holds = dict(holds)      # 保留只含标的的成员集
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
            '<div class="card-conclusion">%s</div>'
            '<div style="margin-top:9px"><a href="#%s" class="action-link" onclick="tab(\'doc\');showDoc(\'%s\');return false">打开档案 →</a></div>'
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
<title>Alpha Radar</title><style>%s</style><style>%s</style></head><body>
<header>
<div class="brandrow"><div><div class="brandmark"><span class="mark">α</span><h1>Alpha Radar</h1></div>
<div class="sub">多维投资研究与决策系统　·　生成于 %s</div></div>
<div class="header-status"><div class="a11y" role="group" aria-label="显示设置">
<span class="lbl">字号</span>
<button onclick="fs(-1)" title="缩小字号" aria-label="缩小字号">A−</button>
<button onclick="fs(0)" title="重置字号" aria-label="重置字号">A</button>
<button onclick="fs(1)" title="放大字号" aria-label="放大字号">A+</button>
<button onclick="hc()" title="切换高对比度" aria-label="切换高对比度" id="hcbtn">◐</button>
</div>%s</div></div>
<nav aria-label="主要导航">
<button data-t="board" onclick="tab('board')">总览</button>
<button data-t="doc" onclick="tab('doc')">公司档案 <span class="nav-count">%d</span></button>
<button data-t="pred" onclick="tab('pred')">预测账本 <span class="nav-count">%d</span></button>
<button data-t="dec" onclick="tab('dec')">决策记录 <span class="nav-count">%d</span></button>
<button data-t="defect" onclick="tab('defect')">缺陷登记册</button>
<button data-t="method" onclick="tab('method')">方法论</button>
</nav></header>
<main>
<section id="s-board">
<div class="board-intro"><div><div class="eyebrow">Research overview</div><h2>研究总览</h2><p>追踪公司评估、赔率与预测记录。这里展示已登记结论，不构成买卖建议。</p></div>
<div class="intro-note">报告级、研究级与规则级结论采用不同证据标准。查看档案时请先确认等级和数据截点。</div></div>
%s
<div class="kpi">
<div><b>%d</b><span>已建档公司</span></div>
<div><b>%d</b><span>报告级</span></div>
<div><b>%d</b><span>研究级</span></div>
<div><b>%d</b><span>规则级</span></div>
<div><b>%d</b><span>赔率 ≥1</span></div>
<div><b>%d</b><span>已登记预测</span></div>
</div>
<div class="section-kicker"><h2>分析结论</h2><span class="pill">按赔率排序</span></div>
<div class="bar"><input id="q-board" aria-label="搜索股票代码" placeholder="搜索 ticker…" oninput="filt('board')">
<span class="pill" id="c-board"></span></div>
%s
</section>
<section id="s-doc">
<div class="board-intro"><div><div class="eyebrow">Company research</div><h2>公司档案</h2><p>按档案等级筛选，并搜索公司代码、标题和结论摘要。</p></div></div>
<div class="bar">
<input id="q-doc" aria-label="搜索公司档案" placeholder="搜索公司名 / 结论关键词…" oninput="filt('doc')">
<select id="g-doc" aria-label="按档案等级筛选" onchange="filt('doc')">
<option value="">全部等级</option><option>报告级</option><option>研究级</option><option>规则级</option>
</select><span class="pill" id="c-doc"></span></div>
<div class="grid" id="docgrid">%s</div>
<div id="docview" style="display:none"><div class="bar">
<button class="btn" onclick="showDocList()">← 返回档案列表</button></div>%s</div>
</section>
<section id="s-pred"><div class="board-intro"><div><div class="eyebrow">Forecast ledger</div><h2>预测账本</h2><p>追加记录的预测快照。预测能力以 Base 情景和最新版本为主口径。</p></div></div>
<div class="bar"><input id="q-pred" aria-label="搜索预测记录" placeholder="搜索 ticker / 指标…" oninput="filt('pred')">
<span class="pill" id="c-pred"></span></div>
%s
</section>
<section id="s-dec"><div class="board-intro"><div><div class="eyebrow">Decision history</div><h2>决策记录</h2><p>投资动作以时间顺序留痕，后续观点变化应追加记录。</p></div></div>
<p class="muted">赔率 &lt;1:1 时不应建仓。决策记录为 append-only。</p>%s</section>
<section id="s-defect"><div class="board-intro"><div><div class="eyebrow">Known issues</div><h2>缺陷登记册</h2><p>保留问题、修复状态和历史背景，避免丢失重要口径教训。</p></div></div>
<p class="muted">修复后更新状态并追加说明，不删除原始记录。</p>%s</section>
<section id="s-method"><div class="board-intro"><div><div class="eyebrow">Methodology</div><h2>方法论</h2><p>系统的证据等级、估值边界和数据校验口径。</p></div></div>
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
/* [D-76] 显示设置：字号 + 高对比度，存 localStorage */
(function(){
  var FS_DEFAULT=19, FS_MIN=15, FS_MAX=32;
  function apply(px){
    px=Math.max(FS_MIN,Math.min(FS_MAX,px));
    document.documentElement.style.setProperty('--fs',px+'px');
    try{localStorage.setItem('ar_fs',px);}catch(e){}
  }
  window.fs=function(d){
    if(d===0){apply(FS_DEFAULT);return;}
    var cur=parseFloat(getComputedStyle(document.documentElement).getPropertyValue('--fs'))||FS_DEFAULT;
    apply(cur+d*2);
  };
  window.hc=function(){
    var on=document.documentElement.classList.toggle('hc');
    var b=document.getElementById('hcbtn'); if(b)b.setAttribute('aria-pressed',on);
    try{localStorage.setItem('ar_hc',on?'1':'0');}catch(e){}
  };
  try{
    var v=localStorage.getItem('ar_fs'); if(v)apply(parseFloat(v));
    if(localStorage.getItem('ar_hc')==='1'){document.documentElement.classList.add('hc');}
  }catch(e){}
})();
function showDoc(t){
  tab('doc');
  document.getElementById('docgrid').style.display='none';
  document.getElementById('docview').style.display='';
  document.querySelectorAll('.dossier').forEach(function(d){d.style.display='none';});
  var e=document.getElementById('doc-'+t); if(e)e.style.display='';
  if(history.replaceState)history.replaceState(null,'','#'+t);
  window.scrollTo(0,0);
}
function showDocList(){
  document.getElementById('docgrid').style.display='';
  document.getElementById('docview').style.display='none';
  document.querySelectorAll('.dossier').forEach(function(d){d.style.display='none';});
  if(history.replaceState)history.replaceState(null,'','#doc');
  window.scrollTo(0,0);
}
</script>
</body></html>""" % (
        CSS, A11Y_CSS, dt.datetime.now().strftime("%Y-%m-%d %H:%M"),
        ('<span class="pill bad">🔴 含持仓数量 — 请勿公开部署</span>'
         if (holds and any(v.get("weight_pct") is not None for v in holds.values()))
         else ('<span class="pill ok">仅含持仓标的 · 不含数量 · 可公开</span>' if holds
               else '<span class="pill ok">不含持仓数据 · 可公开</span>')),
        len(docs), len(preds), len(decs),
        ('<div class="warnband">🔴 <b>本页含持仓数量</b>（仓位% / 盈亏%）。'
         '仓库是<b>公开</b>的 —— <b>不要部署到公网</b>。'
         '要生成可公开版本，去掉 <code>--include-holdings</code> 重新构建。</div>'
         if (holds and any(v.get("weight_pct") is not None for v in holds.values())) else ''),
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
        for bad in ("market_value", "cost_basis", "unrealized_pnl", "avg_cost", "shares"):
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
    _gran = bool(holds) and any(v.get("weight_pct") is not None for v in holds.values())
    if _gran:
        print("  持仓数据：🔴 含数量（勿公开）")
    elif holds:
        print("  持仓数据：✓ 仅含标的 %d 个（不含数量，可公开）" % len(holds))
    else:
        print("  持仓数据：✓ 未包含（可公开）")
    return 0


if __name__ == "__main__":
    sys.exit(main())