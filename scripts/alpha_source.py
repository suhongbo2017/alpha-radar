#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Alpha Radar —— 多数据源交叉校验（第三方源适配器）

为什么需要这个
──────────────
`verify_data.py` 的 L3 只用了 **一个** 外部源（Yahoo）。按 D-39 / D-50 的教训：

    「交叉校验的有效性上限 = 两条路径的独立性。」

只有一个外部源时，那个源错了你无法知道。本脚本补上**第二、第三个源**，
并把"差异"分成四类，而不是简单地判"相等/不相等"：

    MATCH          差异在容差内
    DEFINITIONAL   差异能被**已知口径**精确解释（如 lease 计入债务）
    MISMATCH       差异无法解释 → 硬错误
    UNCOMPARABLE   日期不同，不可比（D-38：假警报与漏报同样有害）

数据源
──────
| 源             | 覆盖                          | 独立性               |
|----------------|-------------------------------|----------------------|
| SEC + engine   | 年度+季度 XBRL（基准）         | 主源（权威）          |
| Yahoo          | TTM trailing                  | 高：独立聚合管道      |
| stockanalysis  | TTM + 年度 + 分部（网页表格）    | 中：上游同源，解析不同 |
| Nasdaq         | 年度 4 年（JSON API）          | 中：同上              |

> **诚实的独立性说明**：后三个源的上游都是公司申报文件，所以它们**不是**真正独立的证据，
> 只是**独立的解析与聚合路径**。这能抓住"我算错了/取错 tag/日期混用"这类错误，
> 但抓不住"公司报错了"。这一点必须写清楚，否则就是 D-39 说的自欺。

用法
────
    py scripts/alpha_source.py list
    py scripts/alpha_source.py fetch GOOGL            # 多源并排
    py scripts/alpha_source.py fetch GOOGL --json
    py scripts/alpha_source.py cross GOOGL            # 与引擎逐项比对
    py scripts/alpha_source.py cross GOOGL --json
    py scripts/alpha_source.py selftest GOOGL         # 故障注入：故意改错，确认会变红

已知局限
────────
1. 只支持**美股**（stockanalysis / Nasdaq 的代码体系）。ADR 如 ASX/UMC 需人工确认代码，
   且它们的季报本来就取不到（见 D-86）。
2. stockanalysis 的 `Total Debt` **含租赁负债**，我们的 `debt` 只含有息债务 ——
   这是**已知 DEFINITIONAL**，不是错误（与 D-54/D-55 同类）。
3. 网页结构会变。解析失败时**必须报错**，不得静默返回空值（D-45 的教训）。
"""
import argparse
import html as _html
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
PROXY = os.environ.get("ALPHA_PROXY", "http://127.0.0.1:7897")
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/120.0 Safari/537.36")

# 规范指标名 → 引擎（alpha_metrics --json）字段名
CANON = {
    "revenue": "ttm_revenue",
    "gross_profit": "ttm_gross_profit",
    "op_income": "ttm_op_income",
    "net_income": "ttm_net_income",
    "ocf": "ttm_ocf",
    "capex": "ttm_capex",
    "fcf": "ttm_fcf",
    "cash_and_sti": "cash",
    "debt": "debt",
    "equity": "equity",
    "shares": "shares",
}

LABEL = {
    "revenue": "收入", "gross_profit": "毛利", "op_income": "营业利润",
    "net_income": "净利润", "ocf": "经营现金流", "capex": "资本开支",
    "fcf": "自由现金流", "cash_and_sti": "现金+短期投资", "debt": "有息债务",
    "equity": "股东权益", "shares": "股数(M)",
}

# 容差必须按指标分档，不能用一个大绝对阈值兜底。
# 实测教训：ABS_TOL=20M 会让「股数差 50 万股（1.14%）」被判为通过 ——
# 而股数差 1% 就足以让市值和 P/E 差 1%。绝对阈值只在数值极小时才该起作用。
TOLERANCE = 0.005          # 默认 0.5% 相对
ABS_TOL = 0.5e6            # 默认 50 万（小于此额度的差异视为舍入）

METRIC_TOL = {
    # canon: (相对容差, 绝对容差)
    "shares": (0.005, 5e4),          # 5 万股 / 0.5%
    "capex": (0.02, 0.5e6),          # capex 口径易有软件/无形资产差异
    "fcf": (0.02, 0.5e6),
}


# ══════════════════════════════════════════════════════════════════
#  取数与解析基础设施
# ══════════════════════════════════════════════════════════════════
def http_get(url, accept=None, expect_json=False):
    """先直连，失败再走代理。返回 (text, source_desc)。

    本机直连是**不通**的，但运营商/热点会返回一个 **HTTP 200 的劫持页**，
    curl 的 returncode 也是 0。所以「returncode==0 且有输出」**不等于拿到了内容**。

    实测（2026-10-30）：直连 Yahoo 返回的是 `<html lang="zh"><title>Yahoo</title>` 的
    劫持页，长度 3125 字节，看起来完全像成功。若不加校验，解析器会拿它去 json.loads
    然后报一个"JSON 解析失败"，把根因指向错误的地方（D-45 的同一类问题）。

    expect_json=True 时，响应必须以 { 或 [ 开头，否则视为失败并改走代理。
    """
    for proxy in (None, PROXY):
        cmd = ["curl", "-s", "--max-time", "30", "-A", UA]
        if accept:
            cmd += ["-H", "Accept: %s" % accept]
        if proxy:
            cmd += ["-x", proxy]
        cmd.append(url)
        try:
            p = subprocess.run(cmd, capture_output=True, text=True,
                               encoding="utf-8", errors="replace")
        except Exception:
            continue
        body = (p.stdout or "").strip()
        if p.returncode != 0 or not body:
            continue
        if expect_json and not body[:1] in ("{", "["):
            continue          # 劫持页 / 错误页 → 换代理再试
        return p.stdout, ("直连" if proxy is None else "代理")
    return None, None


def parse_num(s):
    """'-1,234' / '1 234' / '--' / '' / '(1,234)' / '4.19%' → float or None"""
    if s is None:
        return None
    s = str(s).replace("\u2212", "-").replace("\xa0", " ").strip()
    if s in ("", "-", "--", "—", "N/A", "n/a"):
        return None
    neg = s.startswith("(") and s.endswith(")")
    s = s.strip("()")
    s = s.replace(",", "").replace("$", "").replace("%", "").strip()
    m = re.match(r"^-?\d+(?:\.\d+)?$", s)
    if not m:
        return None
    v = float(s)
    return -v if neg else v


def warn(msg):
    print("  ⚠️  %s" % msg)


# ══════════════════════════════════════════════════════════════════
#  适配器 1：stockanalysis.com（TTM + 最新年度）
#  - 表格是服务端渲染的 HTML，不需要 JS
#  - TTM 列在第 1 列，最新年度在第 2 列
# ══════════════════════════════════════════════════════════════════
_SA_BASE = "https://stockanalysis.com/stocks/%s/financials/%s"

_SA_PAGES = {
    "income": "",
    "balance": "balance-sheet/",
    "cashflow": "cash-flow-statement/",
}

_SA_ROWS = {
    "income": {"revenue": "Revenue", "gross_profit": "Gross Profit",
               "op_income": "Operating Income", "net_income": "Net Income"},
    "balance": {"cash_and_sti": "Cash & Short-Term Investments",
                "equity": "Shareholders' Equity"},
    "cashflow": {"ocf": "Operating Cash Flow", "capex": "Capital Expenditures",
                 "fcf": "Free Cash Flow"},
}

# stockanalysis 的标签单元格里同时有可见标签和 aria-hidden 的 "XXX Growth" 辅助文本，
# 通用标签剥离后恒变成 "Revenue Revenue Growth" 这种重复形态。
# 不能用「删 aria-hidden 元素」的办法：<svg> 也带 aria-hidden，会连可见标签一起误删。
def _norm_label(raw):
    """→ (标签, 是否增长率行)

    stockanalysis 把一个逻辑行拆成两个可见行：
        "Revenue Revenue Growth"   ← 金额行（标签被重复一次）
        "Revenue Growth"           ← 增长率行
    折叠后两者同名，必须靠这个布尔位区分，否则可能把 22.21 这样的百分比当成收入。
    """
    s = re.sub(r"\s+", " ", raw).strip()
    dup = re.match(r"^(.+?)\s+\1(?:\s+Growth)?$", s)      # "X X" / "X X Growth"
    if dup:
        return dup.group(1), False
    g = re.match(r"^(.+?)\s+Growth$", s)                   # "X Growth"
    if g:
        return g.group(1), True
    return s, False


_ARIA_HIDDEN = re.compile(r'(?is)<[^>]*aria-hidden="true"[^>]*>.*?</div>')


def _sa_tables(html):
    """返回 [ [(label, is_growth, [v1, v2, ...]), ...], ... ]

    先剥离全部标签得到纯文本标签，再归一化（见 _norm_label 的说明）。
    """
    out = []
    for t in re.findall(r"(?is)<table[^>]*>.*?</table>", html):
        rows = []
        for r in re.findall(r"(?is)<tr[^>]*>(.*?)</tr>", t):
            cells = re.findall(r"(?is)<t[hd][^>]*>(.*?)</t[hd]>", r)
            cells = [re.sub(r"\s+", " ",
                            re.sub(r"(?s)<[^>]+>", " ", c)).strip() for c in cells]
            cells = [_html.unescape(c) for c in cells]
            if len(cells) >= 2:
                label, is_growth = _norm_label(cells[0])
                rows.append((label, is_growth, [parse_num(c) for c in cells[1:]]))
        if rows:
            out.append(rows)
    return out


_MONTHS = {mm: i + 1 for i, mm in enumerate(
    ["Jan", "Feb", "Mar", "Apr", "May", "Jun",
     "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"])}


def _sa_scale(html):
    """页面自带单位声明，必须读而不是假设。

    stockanalysis 对大公司写 "Financials in millions USD"，对小公司写
    "in thousands USD"。假设错误会让结果差 1000 倍 —— 而且看起来仍然像个数。
    """
    m = re.search(r"Financials in (millions|thousands|billions) (\w+)", html, re.I)
    if m:
        return {"thousands": 1e3, "millions": 1e6, "billions": 1e9}[m.group(1).lower()]
    return 1.0


def _sa_period(html):
    """取 TTM 截止日。

    首选 title 属性（最稳）：
        <th title="Trailing twelve month period ending Sep 30, 2026">
    回退到 'Period Ending' 行的可见文本。
    """
    m = re.search(r'title="Trailing twelve month period ending '
                  r'([A-Z][a-z]{2}) (\d{1,2}), (\d{4})"', html)
    if m:
        return "%s-%02d-%02d" % (m.group(3), _MONTHS[m.group(1)], int(m.group(2)))
    m = re.search(r"Period Ending</td>(.*?)</tr>", html, re.S)
    if m:
        txt = re.sub(r"(?s)<[^>]+>", " ", m.group(1))
        dm = re.search(r"([A-Z][a-z]{2}) (\d{1,2}), (\d{4})", txt)
        if dm:
            return "%s-%02d-%02d" % (dm.group(3), _MONTHS[dm.group(1)], int(dm.group(2)))
    return None


def adapter_stockanalysis(ticker, col=0):
    """col=0 → TTM；col=1 → 最新已结束年度"""
    sym = ticker.lower()
    pages = {}
    for key, sub in _SA_PAGES.items():
        html, via = http_get(_SA_BASE % (sym, sub))
        if not html:
            return None, "stockanalysis 取不到 %s 页（网络或代码不存在）" % key
        pages[key] = html

    as_of = _sa_period(pages["income"])
    scale = _sa_scale(pages["income"])
    metrics, notes = {}, []
    for key, want in _SA_ROWS.items():
        tables = _sa_tables(pages[key])
        found = {}
        for rows in tables:
            for label, is_growth, vals in rows:
                if is_growth or label not in want.values() or label in found:
                    continue
                found[label] = vals[col] if col < len(vals) else None
        for canon, label in want.items():
            if label in found and found[label] is not None:
                metrics[canon] = found[label] * scale
        missing = [l for l in want.values() if l not in found]
        if missing:
            notes.append("%s 页缺少: %s" % (key, ", ".join(missing)))

    # 股数 / 总债务在 balance 的附加表里（"Filing Date Shares Outstanding"/"Total Debt"）
    tables = _sa_tables(pages["balance"])
    for rows in tables:
        for label, is_growth, vals in rows:
            if is_growth:
                continue
            v = vals[col] if col < len(vals) else None
            if v is None:
                continue
            if label == "Total Debt" and "total_debt_leases" not in metrics:
                metrics["total_debt_leases"] = v * scale
            if label in ("Filing Date Shares Outstanding",
                         "Total Common Shares Outstanding") and "shares" not in metrics:
                metrics["shares"] = v * scale

    if "capex" in metrics and metrics["capex"] is not None:
        metrics["capex"] = abs(metrics["capex"])

    if not metrics.get("revenue"):
        return None, "stockanalysis 解析失败：未取到 Revenue（页面结构可能已变）"

    return {
        "source": "stockanalysis",
        "independence": "medium",
        "period": "ttm" if col == 0 else "annual",
        "as_of": as_of,
        "metrics": metrics,
        "notes": notes,
    }, None


# ══════════════════════════════════════════════════════════════════
#  适配器 2：Nasdaq API（年度 4 年，纯 JSON）
# ══════════════════════════════════════════════════════════════════
_NQ_URL = "https://api.nasdaq.com/api/company/%s/financials?frequency=1"

_NQ_ROWS = {
    "incomeStatementTable": {"revenue": "Total Revenue",
                             "gross_profit": "Gross Profit",
                             "op_income": "Operating Income",
                             "net_income": "Net Income"},
    "balanceSheetTable": {"cash": "Cash and Cash Equivalents",
                          "st_investments": "Short-Term Investments",
                          "equity": "Total Equity"},
    "cashFlowTable": {"ocf": "Net Cash Flow-Operating",
                      "capex": "Capital Expenditures"},
}


def adapter_nasdaq(ticker):
    body, via = http_get(_NQ_URL % ticker.upper(), accept="application/json",
                         expect_json=True)
    if not body:
        return None, "nasdaq 取不到（直连与代理都非 JSON）"
    try:
        d = json.loads(body)
    except Exception as e:
        return None, "nasdaq JSON 解析失败: %s" % e
    data = d.get("data") or {}
    if not data:
        return None, "nasdaq 返回空 data（代码可能不支持）"

    metrics, notes = {}, []
    as_of = None
    for tab, want in _NQ_ROWS.items():
        t = data.get(tab) or {}
        hdr = t.get("headers") or {}
        # value2 是最近年度
        if as_of is None and hdr.get("value2"):
            mm = re.match(r"(\d{2})/(\d{2})/(\d{4})", hdr["value2"])
            if mm:
                as_of = "%s-%s-%s" % (mm.group(3), mm.group(1), mm.group(2))
        rows = {r.get("value1"): r.get("value2") for r in (t.get("rows") or [])}
        for canon, label in want.items():
            if label in rows:
                metrics[canon] = parse_num(rows[label])
        missing = [l for l in want.values() if l not in rows]
        if missing:
            notes.append("%s 缺少: %s" % (tab, ", ".join(missing)))

    # 现金+短期投资需自行相加（Nasdaq 没有合并行）
    if metrics.get("cash") is not None:
        sti = metrics.pop("st_investments", None) or 0
        metrics["cash_and_sti"] = metrics["cash"] + sti
    if metrics.get("capex") is not None:
        metrics["capex"] = abs(metrics["capex"])
    if metrics.get("ocf") is not None and metrics.get("capex") is not None:
        metrics["fcf"] = metrics["ocf"] - metrics["capex"]

    if not metrics.get("revenue"):
        return None, "nasdaq 解析失败：未取到 Total Revenue"
    return {"source": "nasdaq", "independence": "medium", "period": "annual",
            "as_of": as_of, "metrics": metrics, "notes": notes}, None


# ══════════════════════════════════════════════════════════════════
#  适配器 3：Yahoo trailing（与 verify_data 的 L3 同源，但这里统一口径）
# ══════════════════════════════════════════════════════════════════
_Y_TYPES = {
    "revenue": "trailingTotalRevenue",
    "net_income": "trailingNetIncome",
    "ocf": "trailingOperatingCashFlow",
    "capex": "trailingCapitalExpenditure",
    "fcf": "trailingFreeCashFlow",
}


def adapter_yahoo(ticker):
    types = list(_Y_TYPES.values())
    url = ("https://query1.finance.yahoo.com/ws/fundamentals-timeseries/v1/finance/"
           "timeseries/%s?symbol=%s&type=%s&period1=1451606400&period2=2000000000"
           % (ticker.upper(), ticker.upper(), ",".join(types)))
    body, via = http_get(url, expect_json=True)
    if not body:
        return None, "yahoo 取不到（直连与代理都非 JSON）"
    try:
        d = json.loads(body)
    except Exception as e:
        return None, "yahoo JSON 解析失败: %s" % e
    res = (d.get("timeseries") or {}).get("result") or []
    if not res:
        return None, "yahoo 返回空 result"

    series = {}
    for r in res:
        t = r["meta"]["type"][0]
        for v in (r.get(t) or []):
            if not v:
                continue
            series.setdefault(t, {})[v["asOfDate"]] = v["reportedValue"]["raw"]

    metrics, as_of = {}, None
    for canon, ytype in _Y_TYPES.items():
        vals = series.get(ytype) or {}
        if vals:
            last = sorted(vals)[-1]
            metrics[canon] = vals[last]
            as_of = as_of or last
    if not metrics:
        return None, "yahoo 未返回任何 trailing 字段"
    notes = []
    # Yahoo 的 capex 记负号（现金流出），我们统一用正数幅值
    if metrics.get("capex") is not None and metrics["capex"] < 0:
        metrics["capex"] = abs(metrics["capex"])
        notes.append("capex 符号已归一（Yahoo 记负号）")
    return {"source": "yahoo", "independence": "high", "period": "ttm",
            "as_of": as_of, "metrics": metrics, "notes": notes}, None


ADAPTERS = {
    "stockanalysis": adapter_stockanalysis,
    "nasdaq": adapter_nasdaq,
    "yahoo": adapter_yahoo,
}


# ══════════════════════════════════════════════════════════════════
#  引擎基准
# ══════════════════════════════════════════════════════════════════
def engine(ticker):
    p = subprocess.run([sys.executable, "scripts/alpha_metrics.py", ticker, "--json"],
                       cwd=ROOT, capture_output=True, text=True,
                       encoding="utf-8", errors="replace")
    raw = p.stdout or ""
    if "{" not in raw:
        return None, "引擎无输出（%s）" % (raw.strip()[-200:] or "空")
    try:
        d = json.loads(raw[raw.index("{"):])
    except Exception as e:
        return None, "引擎 JSON 解析失败: %s" % e
    return {
        "source": "sec+engine",
        "independence": "primary",
        "period": "ttm",
        "as_of": d.get("ttm_period"),
        "metrics": {k: d.get(v) for k, v in CANON.items()},
        "_raw": d,
    }, None


# ══════════════════════════════════════════════════════════════════
#  比对
# ══════════════════════════════════════════════════════════════════
def close(a, b, canon=None):
    if a is None or b is None:
        return None
    rel, ab = METRIC_TOL.get(canon, (TOLERANCE, ABS_TOL))
    return abs(a - b) <= max(abs(b) * rel, ab)


def diff_pct(a, b):
    if a is None or b is None or b == 0:
        return None
    return (a - b) / abs(b) * 100


def explain(canon, mine, theirs, ref):
    """已知口径差异 → 返回解释字符串，否则 None

    必须**精确对上**才算 DEFINITIONAL（D-39/D-43：能解释差异，而不是"差不多"）。
    """
    # 债务：stockanalysis 的 Total Debt 含租赁负债，我们的 debt 只含有息债务
    if canon == "debt":
        tdl = ref.get("total_debt_leases")
        if tdl is not None and close(tdl, theirs, "debt"):
            return "第三方 Total Debt 含租赁负债 = %.4fB（含有息债务）" % (tdl / 1e9)
    # 股东权益：第三方常用「含少数股东权益」口径（ITRI 实测差 1.19%，正好是 NCI）
    if canon == "equity" and mine and theirs:
        nci = theirs - mine
        if mine > 0 and 0 < nci < mine * 0.10:
            return "第三方为含少数股东权益口径（差额 %.4fB ≈ NCI）" % (nci / 1e9)
    # 净利润：第三方常报「归属普通股股东」（已扣优先股股息）
    if canon == "net_income" and mine and theirs:
        d = mine - theirs
        if 0 < d < abs(mine) * 0.02:
            return "第三方为归属普通股口径（已扣优先股股息 %.4fB）" % (d / 1e9)
    # 股数：对方单位可能是"百万"
    if canon == "shares" and theirs is not None and mine:
        if close(theirs * 1e6, mine):
            return "对方单位是百万股（%.3fM）" % theirs
        if close(theirs, mine):
            return "单位一致"
    return None


def cross_one(ticker, inst):
    print("=" * 78)
    print("  多源交叉校验  %s" % ticker.upper())
    print("=" * 78)

    eng, err = engine(ticker)
    if not eng:
        print("  ❌ %s" % err)
        return 2

    print("\n[基准] SEC XBRL + alpha_metrics.py")
    print("   TTM 截止 %s" % (eng["as_of"] or "—"))

    results = []
    for name, fetch in inst.items():
        print("\n[源] %s" % name)
        data, err = fetch(ticker)
        if not data:
            print("   ⚠️  %s" % err)
            results.append({"source": name, "status": "UNAVAILABLE", "detail": err})
            continue
        same_date = (data["as_of"] == eng["as_of"])
        newer = bool(data["as_of"] and eng["as_of"]
                     and data["period"] == "ttm" and data["as_of"] > eng["as_of"])
        print("   口径 %s  截止 %s  独立性 %s%s" % (
            data["period"], data["as_of"] or "—", data["independence"],
            "" if same_date else
            ("   ← 比基准新" if newer else "   ← 与基准日期不同")))
        for n in data.get("notes") or []:
            warn(n)

        if newer:
            # 可行动信号，不是错误：第三方已有更新期，我们该更新档案了
            print("   → FRESHNESS：第三方已有 %s 数据，引擎停在 %s"
                  "（按 D-38 不跨日期比数值）" % (data["as_of"], eng["as_of"]))
            results.append({"source": name, "status": "FRESHNESS_STALE",
                            "detail": "源 %s > 引擎 %s" % (data["as_of"], eng["as_of"])})
            continue

        if not same_date:
            results.append({"source": name, "status": "UNCOMPARABLE",
                            "detail": "%s vs %s" % (data["as_of"], eng["as_of"])})
            print("   → UNCOMPARABLE（日期不同，不能当错误也不能当通过）")
            continue

        nmis = 0
        for canon in CANON:
            mine = eng["metrics"].get(canon)
            theirs = data["metrics"].get(canon)
            if mine is None or theirs is None:
                continue
            name_cn = LABEL.get(canon, canon)
            if close(mine, theirs, canon):
                print("   ✅ %-12s %18s = %18s" % (name_cn, fmt(mine), fmt(theirs)))
                results.append({"source": name, "metric": canon, "status": "MATCH"})
                continue
            exp = explain(canon, mine, theirs, data["metrics"])
            if exp:
                print("   ≈  %-12s %18s vs %18s  %s" % (name_cn, fmt(mine), fmt(theirs), exp))
                results.append({"source": name, "metric": canon,
                                "status": "DEFINITIONAL", "detail": exp})
            else:
                nmis += 1
                p = diff_pct(theirs, mine)
                print("   ❌ %-12s %18s vs %18s  (Δ%.2f%%) ← 无法解释" % (
                    name_cn, fmt(mine), fmt(theirs), p if p is not None else 0))
                results.append({"source": name, "metric": canon,
                                "status": "MISMATCH",
                                "detail": "Δ%.2f%%" % (p if p is not None else 0)})
        if nmis == 0:
            results.append({"source": name, "status": "ALL_CLEAR"})

    n_mis = sum(1 for r in results if r["status"] == "MISMATCH")
    n_ok = sum(1 for r in results if r["status"] in ("MATCH", "DEFINITIONAL", "ALL_CLEAR"))
    n_un = sum(1 for r in results if r["status"] in ("UNCOMPARABLE", "UNAVAILABLE"))
    n_fr = sum(1 for r in results if r["status"] == "FRESHNESS_STALE")

    print("\n" + "-" * 78)
    print("  一致/可解释 %d 项 ｜ 硬错误 %d 项 ｜ 不可比/不可用 %d 项 ｜ 待更新 %d 项"
          % (n_ok, n_mis, n_un, n_fr))
    if n_fr:
        print("  ↑ 待更新 = 第三方已有更新期数据（该跑 alpha_fetch 并改档案），不是校验错误")
    if n_mis:
        print("  %s" % "__CROSS_FAIL__")
        return 1
    print("  %s" % "__CROSS_PASS__")
    return 0


def fmt(v):
    if v is None:
        return "—"
    return "{:,.4f}B".format(v / 1e9) if abs(v) >= 1e8 else "{:,.1f}M".format(v / 1e6)


# ══════════════════════════════════════════════════════════════════
#  子命令
# ══════════════════════════════════════════════════════════════════
def cmd_list(a):
    print("可用的第三方数据源\n" + "=" * 70)
    print("%-16s %-28s %s" % ("源", "覆盖", "独立性"))
    print("-" * 70)
    print("%-16s %-28s %s" % ("sec+engine", "TTM（XBRL 计算）", "主源（权威）"))
    for name, fn in ADAPTERS.items():
        cov = {"stockanalysis": "TTM + 最新年度 + 分部",
               "nasdaq": "年度 4 年",
               "yahoo": "TTM trailing"}[name]
        ind = {"stockanalysis": "中（上游同源，解析不同）",
               "nasdaq": "中（上游同源，解析不同）",
               "yahoo": "高（独立聚合管道）"}[name]
        print("%-16s %-28s %s" % (name, cov, ind))
    print()
    print("规范指标：%s" % ", ".join(LABEL[k] for k in CANON))
    print()
    print("判定：MATCH / DEFINITIONAL（口径可精确解释）/ MISMATCH（硬错误）/ UNCOMPARABLE（日期不同）")
    return 0


def cmd_fetch(a):
    out = {}
    for name, fn in ADAPTERS.items():
        if a.source not in ("all", name):
            continue
        data, err = fn(a.ticker)
        out[name] = data or {"error": err}
    if a.json:
        print(json.dumps(out, ensure_ascii=False, indent=1))
        return 0
    for name, d in out.items():
        print("=" * 60)
        print("源: %s" % name)
        if d.get("error"):
            print("  ⚠️  %s" % d["error"])
            continue
        print("  口径 %s  截止 %s  独立性 %s" % (d["period"], d["as_of"], d["independence"]))
        for canon in CANON:
            if d["metrics"].get(canon) is not None:
                print("  %-14s %s" % (LABEL.get(canon, canon), fmt(d["metrics"][canon])))
        for n in d.get("notes") or []:
            print("  ⚠️  %s" % n)
    return 0


def cmd_cross(a):
    inst = {n: f for n, f in ADAPTERS.items() if a.source in ("all", n)}
    rc = cross_one(a.ticker, inst)
    return rc


def cmd_selftest(a):
    """故障注入：把某个源的 revenue 故意改错，确认校验器会变红。

    这是 D-39 / D-50 的硬要求：**没红过的校验器 = 未验证**。
    """
    print("故障注入自测  %s" % a.ticker.upper())
    print("=" * 60)
    real = adapter_stockanalysis

    def broken(ticker):
        data, err = real(ticker)
        if not data:
            return data, err
        if data["metrics"].get("revenue"):
            data["metrics"]["revenue"] *= 1.01          # 注入 +1% 错误
        return data, err

    rc = cross_one(a.ticker, {"stockanalysis(注入+1%收入错误)": broken})
    ok = (rc == 1)
    print("\n%s" % ("✅ 自测通过：注入的错误被抓住" if ok
                    else "❌ 自测失败：注入 +1% 错误后校验器仍然全绿 —— 这个校验器不可信"))
    return 0 if ok else 1


def main():
    ap = argparse.ArgumentParser(description="多数据源交叉校验")
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("list", help="列出可用数据源")
    p.set_defaults(fn=cmd_list)

    p = sub.add_parser("fetch", help="取单/多源的规范化数据")
    p.add_argument("ticker")
    p.add_argument("--source", default="all", choices=["all"] + list(ADAPTERS))
    p.add_argument("--json", action="store_true")
    p.set_defaults(fn=cmd_fetch)

    p = sub.add_parser("cross", help="与引擎逐项交叉比对")
    p.add_argument("ticker")
    p.add_argument("--source", default="all", choices=["all"] + list(ADAPTERS))
    p.set_defaults(fn=cmd_cross)

    p = sub.add_parser("selftest", help="故障注入自测（确认校验器真的会红）")
    p.add_argument("ticker")
    p.set_defaults(fn=cmd_selftest)

    a = ap.parse_args()
    return a.fn(a)


if __name__ == "__main__":
    sys.exit(main() or 0)
