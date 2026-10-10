#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Alpha Radar — Prediction Ledger / Review Engine  (v1.1)

v1.1 修复（把纪律变成代码约束）:
  [P1-4] 指标词表 —— 指标名必须命中白名单，写错立刻报错，不再静默失配
  [P0-3] 单位校验 —— 实际值 unit 与预测不一致时拒绝写入（可用 --force 覆盖并留痕）
  [P0-2] 版本隔离 —— 分组键含 forecast_version，主评分只用最新版本
  [P0-1] Base 计分 —— 预测能力只对 Base Case 计分；三情景改为"区间命中"独立统计
  [P1-7 部分] 指标分 fundamental / valuation 两类，估值输出不参与预测能力评分
  [P2-17] 重复录入检测

铁律:
  1. 旧预测永不覆盖 —— append-only JSONL
  2. 预测必须能被未来实际数据验证
"""
import argparse
import json
import os
import sys
import datetime as dt

try:
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
except Exception:
    pass

ROOT = os.environ.get(
    "ALPHA_RADAR_HOME",
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
)
DATA = os.path.join(ROOT, "data")
PRED = os.path.join(DATA, "predictions.jsonl")
ACT = os.path.join(DATA, "actuals.jsonl")
DEC = os.path.join(DATA, "decisions.jsonl")

# [D-05] 决策动作词表（与 SKILL.md §5.2 一致）
ACTIONS = ["Watch", "Starter", "Buy", "StrongBuy", "Core", "Hold", "Trim", "Exit"]

# [D-09] 误差归因 9 类；中文别名自动归一
ATTRIBUTIONS = {
    "demand": "Demand", "需求": "Demand", "需求判断": "Demand",
    "marketshare": "MarketShare", "份额": "MarketShare", "市占率": "MarketShare",
    "margin": "Margin", "利润率": "Margin",
    "capex": "CapEx", "资本开支": "CapEx", "资本支出": "CapEx",
    "management": "Management", "管理层": "Management",
    "ma": "M&A", "m&a": "M&A", "并购": "M&A",
    "macro": "Macro", "宏观": "Macro", "周期": "Macro",
    "fx": "FX", "汇率": "FX",
    "valuation": "Valuation", "估值": "Valuation",
}
DEFAULT_RESOLVE_LAG_DAYS = 75   # 期末之后多久应有财报可核对

# ------------------------------------------------------------------ 指标词表
# kind:  fundamental = 可被未来财报验证，计入预测能力评分
#        valuation   = 依赖自身估值假设，弱可验证，只做对照不计分
METRICS = {
    "Revenue":          ("fundamental", "营业收入"),
    "Organic_Growth":   ("fundamental", "有机增长率 %"),
    "Gross_Margin":     ("fundamental", "毛利率 %"),
    "Operating_Margin": ("fundamental", "营业利润率 %"),
    "Net_Margin":       ("fundamental", "净利率 %"),
    "EPS":              ("fundamental", "每股收益(摊薄)"),
    "FCF":              ("fundamental", "自由现金流"),
    "FCF_Margin":       ("fundamental", "自由现金流率 %"),
    "Cash_Conversion":  ("fundamental", "FCF/净利润 %"),
    "ROIC":             ("fundamental", "投入资本回报率 %"),
    "CapEx":            ("fundamental", "资本开支"),
    "Net_Debt_EBITDA":  ("fundamental", "净债务/EBITDA (x)"),
    "Shares":           ("fundamental", "摊薄股本"),
    "Backlog":          ("fundamental", "订单储备"),
    "Book_to_Bill":     ("fundamental", "订单出货比 (x)"),
    "FairValue":        ("valuation",   "情景合理价值"),
    "Target_Price":     ("valuation",   "目标价"),
    "Exit_Multiple":    ("valuation",   "退出倍数 (x)"),
}

ALIASES = {
    "revenue": "Revenue", "revenues": "Revenue", "sales": "Revenue",
    "营业收入": "Revenue", "收入": "Revenue", "营收": "Revenue",
    "organic": "Organic_Growth", "organicgrowth": "Organic_Growth", "有机增长": "Organic_Growth",
    "gm": "Gross_Margin", "grossmargin": "Gross_Margin", "毛利率": "Gross_Margin",
    "om": "Operating_Margin", "opmargin": "Operating_Margin", "operatingmargin": "Operating_Margin",
    "营业利润率": "Operating_Margin", "营业利益率": "Operating_Margin",
    "nm": "Net_Margin", "netmargin": "Net_Margin", "净利率": "Net_Margin",
    "eps": "EPS", "eps_diluted": "EPS", "epsdiluted": "EPS", "每股收益": "EPS",
    "fcf": "FCF", "freecashflow": "FCF", "自由现金流": "FCF",
    "fcfm": "FCF_Margin", "fcfmargin": "FCF_Margin", "自由现金流率": "FCF_Margin",
    "cashconversion": "Cash_Conversion", "cashconv": "Cash_Conversion", "现金转化率": "Cash_Conversion",
    "roic": "ROIC", "投入资本回报率": "ROIC",
    "capex": "CapEx", "capitalexpenditure": "CapEx", "资本开支": "CapEx", "资本支出": "CapEx",
    "netdebtebitda": "Net_Debt_EBITDA", "净债务ebitda": "Net_Debt_EBITDA",
    "fcfrevenue": "Cash_Conversion", "fcfnetincome": "Cash_Conversion", "净利现金转化": "Cash_Conversion",
    "shares": "Shares", "dilutedshares": "Shares", "股本": "Shares",
    "backlog": "Backlog", "订单储备": "Backlog",
    "booktobill": "Book_to_Bill", "btb": "Book_to_Bill", "订单出货比": "Book_to_Bill",
    "fairvalue": "FairValue", "fv": "FairValue", "合理价值": "FairValue",
    "targetprice": "Target_Price", "tp": "Target_Price", "目标价": "Target_Price",
    "exitmultiple": "Exit_Multiple", "退出倍数": "Exit_Multiple",
}

CURRENCIES = {"USD", "TWD", "HKD", "CNY", "RMB", "EUR", "JPY", "GBP", "KRW", "SGD"}
NON_CURRENCY_UNITS = {"%", "PCT", "X", "RATIO", "SHARES", "DAYS"}


def canonical_metric(raw):
    """返回 (canonical, kind) 或 (None, None)"""
    key = str(raw).strip().lower()
    for ch in (" ", "-", "/", "_", "(", ")", "（", "）"):
        key = key.replace(ch, "")
    if key in ALIASES:
        c = ALIASES[key]
        return c, METRICS[c][0]
    for c in METRICS:
        if c.lower().replace("_", "") == key:
            return c, METRICS[c][0]
    return None, None


def norm_unit_checked(u, where=""):
    """归一单位；未知单位只警告不拒绝（允许自定义，但要看得见）"""
    nu = norm_unit(u)
    if nu and nu not in CURRENCIES and nu not in NON_CURRENCY_UNITS:
        print("⚠ 非常见单位 '%s'%s —— 确认不是拼写错误（常见：USD/TWD/HKD/CNY/%%/X）"
              % (nu, (" (%s)" % where) if where else ""))
    return nu


def metric_menu():
    lines = ["  可验证 (fundamental):"]
    for m, (k, d) in METRICS.items():
        if k == "fundamental":
            lines.append("    %-18s %s" % (m, d))
    lines.append("  估值输出 (valuation, 不计入预测能力评分):")
    for m, (k, d) in METRICS.items():
        if k == "valuation":
            lines.append("    %-18s %s" % (m, d))
    return "\n".join(lines)


def die(msg):
    print("✗ " + msg, file=sys.stderr)
    sys.exit(2)


def norm_unit(u):
    u = str(u).strip()
    return u.upper() if u not in ("%",) else "%"


def ensure():
    os.makedirs(DATA, exist_ok=True)


def append(path, rec):
    ensure()
    with open(path, "a", encoding="utf-8") as f:
        f.write(json.dumps(rec, ensure_ascii=False) + "\n")


def load(path):
    if not os.path.exists(path):
        return []
    out = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                out.append(json.loads(line))
    return out


def norm_period(s):
    """FY2030 / 2030 / FY30 -> 2030；Q3FY2027 / 2027Q3 -> Q32027"""
    s = str(s).upper().replace("FY", "").replace(" ", "").strip()
    if len(s) == 2 and s.isdigit():
        s = "20" + s
    # 2027Q3 -> Q32027
    if len(s) == 6 and s[:4].isdigit() and s[4] == "Q":
        s = s[4:] + s[:4]
    return s


def period_end(p):
    """[D-06] 期间 -> 期末日期 (YYYY-MM-DD)；无法识别返回 None
    Q32027 -> 2027-09-30   ;   2030 -> 2030-12-31
    """
    p = norm_period(p)
    if len(p) == 6 and p[0] == "Q" and p[1].isdigit() and p[2:].isdigit():
        q, y = int(p[1]), int(p[2:])
        if 1 <= q <= 4:
            m, d = {1: (3, 31), 2: (6, 30), 3: (9, 30), 4: (12, 31)}[q]
            return "%04d-%02d-%02d" % (y, m, d)
    if len(p) == 4 and p.isdigit():
        return "%s-12-31" % p
    return None


def resolves_after(p, lag=DEFAULT_RESOLVE_LAG_DAYS):
    """[D-06] 该期预测最早何时应可核对 = 期末 + lag 天"""
    e = period_end(p)
    if not e:
        return None
    d = dt.date.fromisoformat(e) + dt.timedelta(days=lag)
    return d.isoformat()


def canonical_attribution(raw):
    key = str(raw).strip().lower().replace(" ", "").replace("-", "")
    return ATTRIBUTIONS.get(key)


def canonical_action(raw):
    key = str(raw).strip().lower().replace(" ", "").replace("_", "").replace("-", "")
    for a in ACTIONS:
        if a.lower() == key:
            return a
    return None


def fmt(v, unit=""):
    if v is None:
        return "—"
    u = norm_unit(unit) if unit else ""
    if u in NON_CURRENCY_UNITS:
        if u in ("X", "RATIO"):
            return "%.2fx" % v
        if u == "%":
            return "%.1f%%" % v
        return "%.4g" % v
    a = abs(v)
    if a >= 1e12:
        s = "%.2fT" % (v / 1e12)
    elif a >= 1e9:
        s = "%.2fB" % (v / 1e9)
    elif a >= 1e6:
        s = "%.2fM" % (v / 1e6)
    else:
        s = "%.4g" % v
    return (u + " " + s).strip()


def pct_err(actual, forecast):
    if forecast in (None, 0):
        return None
    return (actual - forecast) / abs(forecast)


def grade(e):
    if e is None:
        return "—"
    a = abs(e)
    return "A" if a < 0.05 else "B" if a < 0.10 else "C" if a < 0.20 else "D"


# ---------------------------------------------------------------- predict
def cmd_predict(a):
    metric, kind = canonical_metric(a.metric)
    if metric is None:
        if not a.allow_custom:
            die("未知指标 '%s'。\n\n%s\n\n  如确需自定义指标，加 --allow-custom" % (a.metric, metric_menu()))
        metric, kind = str(a.metric).strip(), "fundamental"
        print("⚠ 自定义指标 '%s'，按 fundamental 处理。" % metric)
    if kind == "valuation":
        print("⚠ '%s' 属于 valuation 类（弱可验证），不计入预测能力评分，只做对照。" % metric)

    if a.prob is not None and not (0 < a.prob <= 1):
        die("--prob 应为 0-1 之间的小数（如 0.45）")

    value = a.value

    rec = {
        "record_type": "prediction",
        "ticker": a.ticker.upper(),
        "analysis_date": a.date or dt.date.today().isoformat(),
        "forecast_version": a.version,
        "scenario": a.scenario,
        "metric": metric,
        "metric_kind": kind,
        "forecast_period": norm_period(a.period),
        "forecast_value": value,
        "unit": norm_unit_checked(a.unit, "predict"),
        "probability": a.prob,
        "confidence": a.confidence,
        "thesis": a.thesis or "",
        "source_basis": a.basis or "",
        "logged_at": dt.datetime.now().isoformat(timespec="seconds"),
    }

    # [P2-17] 重复 / 冲突检测
    existing = load(PRED)
    same_key = [r for r in existing
                if r["ticker"] == rec["ticker"] and r["metric"] == rec["metric"]
                and norm_period(r["forecast_period"]) == rec["forecast_period"]
                and r.get("forecast_version", "v1") == rec["forecast_version"]
                and r["scenario"] == rec["scenario"]]
    if same_key and not a.allow_duplicate:
        prev = same_key[-1]
        if prev["forecast_value"] == rec["forecast_value"]:
            die("重复记录：同一 (ticker=%s, metric=%s, period=%s, version=%s, scenario=%s) 已存在且数值相同。\n"
                "  如确认要重复，加 --allow-duplicate" % (rec["ticker"], metric, rec["forecast_period"],
                                                        rec["forecast_version"], rec["scenario"]))
        die("版本冲突：同一 (ticker=%s, metric=%s, period=%s, version=%s, scenario=%s) 已存在数值 %s。\n"
            "  修改预测必须升版本（--version v2），不得在同一版本内改数。"
            % (rec["ticker"], metric, rec["forecast_period"], rec["forecast_version"],
               rec["scenario"], fmt(prev["forecast_value"], prev["unit"])))

    append(PRED, rec)
    print("✓ prediction appended")
    print(json.dumps(rec, ensure_ascii=False, indent=1))


# ---------------------------------------------------------------- actual
def cmd_actual(a):
    metric, kind = canonical_metric(a.metric)
    if metric is None:
        if not a.allow_custom:
            die("未知指标 '%s'。\n\n%s\n\n  如确需自定义指标，加 --allow-custom" % (a.metric, metric_menu()))
        metric, kind = str(a.metric).strip(), "fundamental"
    unit = norm_unit_checked(a.unit, "actual")
    period = norm_period(a.period)

    # [P0-3] 单位一致性 —— 这是最容易被忽略、也最容易产生假误差的地方
    related = [r for r in load(PRED)
               if r["ticker"] == a.ticker.upper() and r["metric"] == metric
               and norm_period(r["forecast_period"]) == period]
    if related:
        want = related[-1]["unit"]
        if want != unit and not a.force:
            die("单位不一致：预测用的是 %s，本次实际值用的是 %s。\n"
                "  (ticker=%s, metric=%s, period=%s)\n"
                "  预测值示例: %s\n"
                "  → 请换算成 %s 后再录入；如确认按当前单位录入，加 --force（会在记录中留痕）"
                % (want, unit, a.ticker.upper(), metric, period,
                   fmt(related[-1]["forecast_value"], want), want))

    attribution = None
    if getattr(a, "attribution", None):
        attribution = canonical_attribution(a.attribution)
        if attribution is None:
            die("未知归因 '%s'。可选: %s" % (a.attribution, ", ".join(sorted(set(ATTRIBUTIONS.values())))))

    rec = {
        "record_type": "actual",
        "ticker": a.ticker.upper(),
        "metric": metric,
        "metric_kind": kind,
        "period": period,
        "actual_value": a.value,
        "unit": unit,
        "unit_forced": bool(a.force and related and related[-1]["unit"] != unit),
        "fx_assumption": a.fx or "",
        "attribution": attribution,
        "actual_date": a.date or dt.date.today().isoformat(),
        "source": a.source or "",
        "logged_at": dt.datetime.now().isoformat(timespec="seconds"),
    }
    append(ACT, rec)
    print("✓ actual appended")
    print(json.dumps(rec, ensure_ascii=False, indent=1))


# ---------------------------------------------------------------- list
def cmd_list(a):
    tk = a.ticker.upper() if a.ticker else None
    rows = [r for r in load(PRED) if not tk or r["ticker"] == tk]
    rows.sort(key=lambda r: (r["ticker"], r["metric"], norm_period(r["forecast_period"]),
                             str(r.get("forecast_version", "v1")), r["scenario"]))
    print("%-6s %-10s %-4s %-6s %-17s %-7s %-14s %-5s %s" %
          ("TICKER", "ANALYSIS", "VER", "SCEN", "METRIC", "PERIOD", "VALUE", "CONF", "PROB"))
    for r in rows:
        print("%-6s %-10s %-4s %-6s %-17s %-7s %-14s %-5s %s" % (
            r["ticker"], r["analysis_date"], r.get("forecast_version", "v1"),
            r["scenario"], r["metric"], norm_period(r["forecast_period"]),
            fmt(r["forecast_value"], r["unit"]), r.get("confidence", ""),
            ("%.0f%%" % (r["probability"] * 100)) if r.get("probability") else "—"))
    print("\n%d predictions" % len(rows))


# ---------------------------------------------------------------- report
def cmd_report(a):
    tk = a.ticker.upper() if a.ticker else None
    preds = [r for r in load(PRED) if not tk or r["ticker"] == tk]
    acts = [r for r in load(ACT) if not tk or r["ticker"] == tk]

    aidx = {}
    for r in acts:
        # [D-31] actuals.jsonl 里可能混有 attribution 追记（无 unit/actual_value），
        # 必须过滤，否则下面读 r["unit"] 会 KeyError 使整个 report 崩掉
        if "actual_value" not in r or "unit" not in r:
            continue
        aidx[(r["ticker"], r["metric"], norm_period(r["period"]))] = r

    # 单位不一致的组：不参与任何对比（否则会生成无意义的"落点"和误差）
    mismatch = {}
    for (t, m, p), act in aidx.items():
        rel = [r for r in preds if r["ticker"] == t and r["metric"] == m
               and norm_period(r["forecast_period"]) == p]
        if rel and any(r["unit"] != act["unit"] for r in rel):
            mismatch[(t, m, p)] = rel[-1]["unit"]

    # 分组键含版本 [P0-2]
    by_ver = {}
    for r in preds:
        k = (r["ticker"], r["metric"], norm_period(r["forecast_period"]),
             r.get("forecast_version", "v1"))
        by_ver.setdefault(k, []).append(r)

    # 每个 (ticker,metric,period) 的最新版本
    latest = {}
    for (t, m, p, v) in by_ver:
        k = (t, m, p)
        cur = latest.get(k)
        if cur is None:
            latest[k] = v
        else:
            a_, b_ = str(cur).lower().lstrip("v"), str(v).lower().lstrip("v")
            if b_.isdigit() and (not a_.isdigit() or int(b_) > int(a_)):
                latest[k] = v

    L = []
    L.append("# Alpha Radar — Prediction vs Actual")
    L.append("")
    L.append("生成时间: %s" % dt.datetime.now().isoformat(timespec="seconds"))
    if tk:
        L.append("范围: %s" % tk)
    L.append("")
    L.append("> 口径：预测能力评分 **只使用 Base Case + 最新版本 + fundamental 类指标**。")
    L.append("> 三情景只用于判断\"实际落在哪个区间\"，不用于事后择优。")
    L.append("")

    # ---- 1. 主评分
    L.append("## 1. 主评分：Base Case vs 实际")
    L.append("")
    L.append("| Ticker | Metric | Period | Ver | Base 预测 | 实际 | Base 误差 | 评级 | 情景落点 |")
    L.append("|---|---|---|---|---:|---:|---:|:--:|---|")
    scored = []
    pending = []
    excluded_valuation = 0
    mismatch_n = 0
    for k in sorted(latest):
        t, m, p = k
        v = latest[k]
        rows = by_ver[(t, m, p, v)]
        kind = rows[0].get("metric_kind") or METRICS.get(m, ("fundamental", ""))[0]
        if kind == "valuation":
            excluded_valuation += 1
            continue
        base = next((r for r in rows if r["scenario"] == "Base"), None)
        if (t, m, p) in mismatch:
            act = aidx[(t, m, p)]
            L.append("| %s | %s | %s | %s | %s | %s | ⚠️ 单位不一致 | — | ⚠️ 跳过 |" % (
                t, m, p, v, fmt(base["forecast_value"], base["unit"]) if base else "—",
                fmt(act["actual_value"], act["unit"])))
            pending.append(k)
            mismatch_n += 1
            continue
        act = aidx.get(k)
        loc = "—"
        if act:
            loc = "⚠️ 单位不一致，跳过" if (t, m, p) in mismatch else scenario_location(rows, act["actual_value"])
        if base is None:
            L.append("| %s | %s | %s | %s | _无 Base_ | %s | — | — | %s |" %
                     (t, m, p, v, fmt(act["actual_value"], act["unit"]) if act else "_待公布_", loc))
            continue
        if not act:
            L.append("| %s | %s | %s | %s | %s | _待公布_ | — | — | — |" %
                     (t, m, p, v, fmt(base["forecast_value"], base["unit"])))
            pending.append(k)
            continue
        e = pct_err(act["actual_value"], base["forecast_value"])
        L.append("| %s | %s | %s | %s | %s | %s | %s | **%s** | %s |" % (
            t, m, p, v, fmt(base["forecast_value"], base["unit"]),
            fmt(act["actual_value"], act["unit"]),
            "%+.1f%%" % (e * 100) if e is not None else "—", grade(e), loc))
        if kind == "fundamental" and not act.get("unit_forced"):
            scored.append((t, m, e, act["unit"]))

    if not latest:
        L.append("| _无记录_ | | | | | | | | |")
    L.append("")

    # ---- 2. 概率加权预测 [D-08]
    L.append("## 2. 概率加权预测 vs 实际")
    L.append("")
    L.append("> 概率加权预测 = Σ(情景概率 × 情景预测值)。它比 Base 更能代表\"当时的整体预期\"；")
    L.append("> 只在三情景概率齐全时才计算。")
    L.append("")
    pw_rows = []
    for k in sorted(latest):
        t, m, p = k
        v = latest[k]
        rows = by_ver[(t, m, p, v)]
        kind = rows[0].get("metric_kind") or METRICS.get(m, ("fundamental", ""))[0]
        if kind == "valuation" or (t, m, p) in mismatch:
            continue
        probs = [(r.get("probability"), r["forecast_value"]) for r in rows]
        if any(pr is None for pr, _ in probs) or len(probs) < 2:
            continue
        tot = sum(pr for pr, _ in probs)
        if not tot:
            continue
        w = sum(pr * val for pr, val in probs) / tot
        act = aidx.get(k)
        e = pct_err(act["actual_value"], w) if act else None
        pw_rows.append((t, m, p, w, rows[0]["unit"], tot, act, e))
    if pw_rows:
        L.append("| Ticker | Metric | Period | 概率加权预测 | 概率合计 | 实际 | 加权误差 | 评级 |")
        L.append("|---|---|---|---:|---:|---:|---:|:--:|")
        for (t, m, p, w, u, tot, act, e) in pw_rows:
            L.append("| %s | %s | %s | %s | %.0f%% | %s | %s | **%s** |" % (
                t, m, p, fmt(w, u), tot * 100,
                fmt(act["actual_value"], act["unit"]) if act else "_待公布_",
                "%+.1f%%" % (e * 100) if e is not None else "—", grade(e)))
        L.append("")
        L.append("> 对比第 1 节：若**加权误差远小于 Base 误差**，说明三情景+概率的刻画比单点预测更准，")
        L.append("> 应更多地用加权值做决策参考。反之则说明概率本身拍错了。")
    else:
        L.append("_无三情景概率齐全的预测 —— 用 `predict --prob <0-1>` 补齐三情景后才可计算。_")
    L.append("")

    # ---- 3. 情景区间命中
    L.append("## 3. 情景区间命中（独立统计，不参与评分）")
    L.append("")
    L.append("| Ticker | Metric | Period | Bear | Base | Bull | 实际 | 落点 | 是否超出区间 |")
    L.append("|---|---|---|---:|---:|---:|---:|---|---|")
    hit_in, hit_total, sec2_rows = 0, 0, 0
    for k in sorted(latest):
        t, m, p = k
        v = latest[k]
        rows = by_ver[(t, m, p, v)]
        sec2_rows += 1
        if (t, m, p) in mismatch:
            d = {r["scenario"]: r["forecast_value"] for r in rows}
            u = rows[0]["unit"]
            act0 = aidx[(t, m, p)]
            L.append("| %s | %s | %s | %s | %s | %s | %s | ⚠️ 单位不一致，跳过 | ⚠️ |" % (
                t, m, p, fmt(d.get("Bear"), u), fmt(d.get("Base"), u), fmt(d.get("Bull"), u),
                fmt(act0["actual_value"], act0["unit"])))
            continue
        act = aidx.get(k)
        if not act:
            continue
        d = {r["scenario"]: r["forecast_value"] for r in rows}
        loc = scenario_location(rows, act["actual_value"])
        vals = sorted(d.values())
        inside = vals and (vals[0] <= act["actual_value"] <= vals[-1]) if vals else False
        hit_total += 1
        if inside:
            hit_in += 1
        L.append("| %s | %s | %s | %s | %s | %s | %s | %s | %s |" % (
            t, m, p,
            fmt(d.get("Bear"), rows[0]["unit"]), fmt(d.get("Base"), rows[0]["unit"]),
            fmt(d.get("Bull"), rows[0]["unit"]),
            fmt(act["actual_value"], act["unit"]), loc,
            "否（区间内）" if inside else "⚠️ **是**"))
    if sec2_rows == 0:
        L.append("| _尚无已兑现情景_ | | | | | | | | |")
    L.append("")
    if hit_total:
        L.append("**区间命中率：%d/%d = %.0f%%** —— 低于 70%% 说明三情景设置过窄（Bear 不够悲观 / Bull 不够乐观）。"
                 % (hit_in, hit_total, 100.0 * hit_in / hit_total))
    L.append("")

    # ---- 4. 历史版本对照
    L.append("## 4. 历史版本对照（不参与评分）")
    L.append("")
    hist = [k for k in by_ver if latest.get((k[0], k[1], k[2])) != k[3]]
    if hist:
        L.append("| Ticker | Metric | Period | Ver | Base 预测 | 实际 | 误差 |")
        L.append("|---|---|---|---|---:|---:|---:|")
        for k in sorted(hist):
            t, m, p, v = k
            rows = by_ver[k]
            base = next((r for r in rows if r["scenario"] == "Base"), None)
            act = aidx.get((t, m, p))
            e = pct_err(act["actual_value"], base["forecast_value"]) if (act and base) else None
            L.append("| %s | %s | %s | %s | %s | %s | %s |" % (
                t, m, p, v,
                fmt(base["forecast_value"], base["unit"]) if base else "—",
                fmt(act["actual_value"], act["unit"]) if act else "_待公布_",
                "%+.1f%%" % (e * 100) if e is not None else "—"))
    else:
        L.append("_无历史版本 —— 说明尚未发生过预测修订。_")
    L.append("")

    # ---- 5. 估值输出对照
    L.append("## 5. 估值输出对照（弱可验证，不计分）")
    L.append("")
    valrows = [(k, r) for k, v in latest.items() for r in by_ver[(k[0], k[1], k[2], v)]
               if (r.get("metric_kind") or METRICS.get(r["metric"], ("", ""))[0]) == "valuation"]
    if valrows:
        L.append("| Ticker | Metric | Period | Ver | 情景 | 预测 | 实际/现价 | 备注 |")
        L.append("|---|---|---|---|---|---:|---:|---|")
        for k, r in sorted(valrows, key=lambda x: x[0]):
            act = aidx.get(k)
            L.append("| %s | %s | %s | %s | %s | %s | %s | 需人工判断是否兑现 |" % (
                k[0], k[1], k[2], r.get("forecast_version", "v1"), r["scenario"],
                fmt(r["forecast_value"], r["unit"]),
                fmt(act["actual_value"], act["unit"]) if act else "_待公布_"))
    else:
        L.append("_无估值类记录。_")
    L.append("")

    # ---- 6. 预测能力
    L.append("## 6. 预测能力 Forecast Accuracy（Base Case，按 Ticker+Metric+币种分组）")
    L.append("")
    agg = {}
    for (t, m, e, u) in scored:
        if e is None:
            continue
        agg.setdefault((t, m, u), []).append(abs(e))
    if agg:
        L.append("| Ticker | Metric | 单位 | 样本 | 平均绝对误差 | 评级 |")
        L.append("|---|---|---|---:|---:|---:|")
        for (t, m, u) in sorted(agg):
            errs = agg[(t, m, u)]
            avg = sum(errs) / len(errs)
            L.append("| %s | %s | %s | %d | %.1f%% | %s |" % (t, m, u, len(errs), avg * 100, grade(avg)))
    else:
        L.append("_尚无已兑现的 fundamental 预测。_")
    L.append("")
    L.append("已结算 %d 条 / 待公布 %d 条 / 单位不一致 %d 条 / 不计分（估值类）%d 条" %
             (len(scored), len(pending) - mismatch_n, mismatch_n, excluded_valuation))

    # ---- 7. 误差归因分布 [D-09]
    L.append("")
    L.append("## 7. 误差归因分布")
    L.append("")
    latest_att = {}
    for r in acts:
        if r.get("attribution"):
            latest_att[(r["ticker"], r["metric"], norm_period(r.get("period", "")))] = r["attribution"]
    if latest_att:
        agg2 = {}
        for k, att in latest_att.items():
            agg2.setdefault(att, []).append(k)
        L.append("| 归因 | 次数 | 占比 | 涉及 |")
        L.append("|---|---:|---:|---|")
        for att in sorted(agg2, key=lambda x: -len(agg2[x])):
            ks = agg2[att]
            L.append("| %s | %d | %.0f%% | %s |" % (
                att, len(ks), 100.0 * len(ks) / len(latest_att),
                ", ".join(sorted({"%s/%s" % (a, b) for a, b, _ in ks}))))
        L.append("")
        L.append("> **这张表才是复盘引擎最高价值的输出**：它告诉你该修的是需求判断、利润率判断、")
        L.append("> 还是估值判断。哪个归因占比最高，下一轮就把资源投到那里。")
        for att in sorted(agg2, key=lambda x: -len(agg2[x]))[:1]:
            L.append(">")
            L.append("> 当前最大错误来源：**%s**（%d 次）" % (att, len(agg2[att])))
    else:
        L.append("_尚无归因记录。录入实际值时加 `--attribution <类别>`，或事后用 ")
        L.append("`alpha_ledger.py attribute` 补记。可选：Demand / MarketShare / Margin / CapEx / ")
        L.append("Management / M&A / Macro / FX / Valuation。_")
    L.append("")

    # ---- 8. 决策 vs 结果 [D-05]
    L.append("## 8. 决策 vs 结果")
    L.append("")
    decs = [r for r in load(DEC) if not tk or r["ticker"] == tk]
    prices = {}
    for spec in a.price:
        if "=" in spec:
            k, v = spec.split("=", 1)
            try:
                prices[k.strip().upper()] = float(v)
            except ValueError:
                pass
    if decs:
        L.append("| Ticker | 日期 | 动作 | 决策价 | 仓位 | 赔率 | 当前价 | 回报 | 年化 | 纪律 |")
        L.append("|---|---|---|---:|---:|---:|---:|---:|---:|---|")
        for r in sorted(decs, key=lambda x: (x["ticker"], x["decision_date"])):
            now = prices.get(r["ticker"])
            ret = ann = "—"
            flag = "—"
            if now and r["price"]:
                rr = (now - r["price"]) / r["price"]
                ret = "%+.1f%%" % (rr * 100)
                d0 = dt.date.fromisoformat(r["decision_date"])
                days = (dt.date.today() - d0).days
                # [D-30] 周期过短时不得年化：1 天回报年化会炸成天文数字
                if days >= 90 and (1 + rr) > 0:
                    ann = "%+.1f%%" % (((1 + rr) ** (365.0 / days) - 1) * 100)
                elif days < 90:
                    ann = "n/a(%dd)" % max(days, 0)
            if r["action"] in ("Buy", "StrongBuy", "Core", "Starter") and (r.get("odds") is not None) and r["odds"] < 1:
                flag = "⚠️ 违反赔率纪律"
            L.append("| %s | %s | **%s** | %.2f | %s | %s | %s | %s | %s | %s |" % (
                r["ticker"], r["decision_date"], r["action"], r["price"],
                ("%g%%" % r["target_weight"]) if r.get("target_weight") is not None else "—",
                ("%.2f:1" % r["odds"]) if r.get("odds") is not None else "—",
                "%.2f" % now if now else "—", ret, ann, flag))
        L.append("")
        L.append("> 赔率 <1:1 时任何价位都不应建仓。出现⚠️说明当时违反了自己定的纪律。")
        L.append("> 传入当前价才能算回报：`report --price %s=<现价>`" % (decs[0]["ticker"]))
    else:
        L.append("_尚无决策记录。用 `alpha_ledger.py decision` 记录，例如：_")
        L.append("```bash")
        L.append("py scripts/alpha_ledger.py decision --ticker APH --action Watch \\")
        L.append("    --price 88.62 --odds 0.5 --reason \"赔率 0.5:1，价格已把高增长定价进去\"")
        L.append("```")
    L.append("")

    # ---- 9. 单位告警
    forced = [r for r in acts if r.get("unit_forced")]
    if forced:
        L.append("")
        L.append("## 9. ⚠️ 单位强制覆盖留痕")
        L.append("")
        for r in forced:
            L.append("- %s %s %s：录入单位 %s（与预测不一致，已排除出评分）" %
                     (r["ticker"], r["metric"], norm_period(r["period"]), r["unit"]))

    md = "\n".join(L)
    print(md)
    if a.save:
        ensure()
        out = os.path.join(DATA, a.out or "review_report.md")
        with open(out, "w", encoding="utf-8") as f:
            f.write(md + "\n")
        print("\n✓ saved -> %s" % out)


def scenario_location(rows, actual):
    """判断实际落在哪个情景区间"""
    vals = sorted(((r["forecast_value"], r["scenario"]) for r in rows), key=lambda x: x[0])
    if not vals:
        return "—"
    if actual < vals[0][0]:
        return "低于 %s" % vals[0][1]
    if actual > vals[-1][0]:
        return "高于 %s" % vals[-1][1]
    for i in range(len(vals) - 1):
        lo, hi = vals[i], vals[i + 1]
        if lo[0] <= actual <= hi[0]:
            if actual == lo[0]:
                return lo[1]
            if actual == hi[0]:
                return hi[1]
            return "%s~%s" % (lo[1], hi[1])
    return vals[-1][1]


# ---------------------------------------------------------------- decision
# [D-05] Decision Database —— 回答"我当时在什么价格决定了什么动作，纪律遵守了吗"
def cmd_decision(a):
    action = canonical_action(a.action)
    if action is None:
        die("未知动作 '%s'。可选: %s" % (a.action, ", ".join(ACTIONS)))
    if a.price is None:
        die("必须提供 --price（决策当时的股价）；没价格的决策无法复盘")
    if a.weight is not None and not (0 <= a.weight <= 100):
        die("--weight 应为 0-100（目标仓位百分比）")

    rec = {
        "record_type": "decision",
        "ticker": a.ticker.upper(),
        "decision_date": a.date or dt.date.today().isoformat(),
        "action": action,
        "price": a.price,
        "currency": norm_unit_checked(a.currency, "decision"),
        "target_weight": a.weight,
        "prev_weight": a.prev_weight,
        "odds": a.odds,
        "fair_value": a.fair_value,
        "thesis": a.thesis or "",
        "reason": a.reason or "",
        "logged_at": dt.datetime.now().isoformat(timespec="seconds"),
    }
    append(DEC, rec)
    print("✓ decision appended（append-only，不可修改；改主意请记新的一条）")
    print(json.dumps(rec, ensure_ascii=False, indent=1))


def cmd_decisions(a):
    tk = a.ticker.upper() if a.ticker else None
    rows = [r for r in load(DEC) if not tk or r["ticker"] == tk]
    rows.sort(key=lambda r: (r["ticker"], r["decision_date"]))
    if not rows:
        print("（无决策记录）")
        return
    print("%-6s %-10s %-9s %-10s %-8s %-7s %s" %
          ("TICKER", "DATE", "ACTION", "PRICE", "WEIGHT", "ODDS", "理由"))
    for r in rows:
        print("%-6s %-10s %-9s %-10s %-8s %-7s %s" % (
            r["ticker"], r["decision_date"], r["action"],
            "%s %.2f" % (r.get("currency", ""), r["price"]),
            ("%g%%" % r["target_weight"]) if r.get("target_weight") is not None else "—",
            ("%.2f:1" % r["odds"]) if r.get("odds") is not None else "—",
            (r.get("reason") or r.get("thesis") or "")[:40]))
    print("\n%d decisions" % len(rows))


# ---------------------------------------------------------------- due
# [D-06] 哪些预测到期该复盘了
def cmd_due(a):
    asof = a.asof or dt.date.today().isoformat()
    tk = a.ticker.upper() if a.ticker else None
    preds = [r for r in load(PRED) if not tk or r["ticker"] == tk]
    acts = {(r["ticker"], r["metric"], norm_period(r["period"])) for r in load(ACT)}

    seen, due = set(), []
    for r in preds:
        k = (r["ticker"], r["metric"], norm_period(r["forecast_period"]))
        if k in seen:
            continue
        seen.add(k)
        ra = r.get("resolves_after") or resolves_after(r["forecast_period"], a.lag)
        if not ra or ra > asof:
            continue
        if k in acts:
            continue
        due.append((k, ra, r))

    if not due:
        print("（截至 %s 没有到期未复盘的预测）" % asof)
        return 0
    print("截至 %s，以下 %d 条预测已到期但尚未录入实际值：\n" % (asof, len(due)))
    print("%-6s %-17s %-7s %-12s %-14s %s" %
          ("TICKER", "METRIC", "PERIOD", "应可核对", "Base 预测", "情景"))
    for k, ra, r in sorted(due, key=lambda x: x[1]):
        same = [p for p in preds if (p["ticker"], p["metric"], norm_period(p["forecast_period"])) == k]
        base = next((p for p in same if p["scenario"] == "Base"), None)
        print("%-6s %-17s %-7s %-12s %-14s %s" % (
            k[0], k[1], k[2], ra,
            fmt(base["forecast_value"], base["unit"]) if base else "—",
            "/".join(sorted({p["scenario"] for p in same}))))
    print("\n提示：录入实际值用\n  py scripts/alpha_ledger.py actual --ticker <T> --metric <M> \\")
    print("      --period <P> --value <V> --unit <U> --source \"<申报来源>\"")
    return 0


# ---------------------------------------------------------------- attribute
# [D-09] 事后补归因（atter-only，不覆盖 actual）
def cmd_attribute(a):
    metric, _ = canonical_metric(a.metric)
    if metric is None:
        die("未知指标 '%s'" % a.metric)
    att = canonical_attribution(a.attribution)
    if att is None:
        die("未知归因 '%s'。可选: %s" % (a.attribution, ", ".join(sorted(set(ATTRIBUTIONS.values())))))
    rec = {
        "record_type": "attribution",
        "ticker": a.ticker.upper(),
        "metric": metric,
        "period": norm_period(a.period),
        "attribution": att,
        "note": a.note or "",
        "logged_at": dt.datetime.now().isoformat(timespec="seconds"),
    }
    append(ACT, rec)
    print("✓ attribution appended")
    print(json.dumps(rec, ensure_ascii=False, indent=1))


# ---------------------------------------------------------------- export
def cmd_export(a):
    ensure()
    preds = load(PRED)
    out = os.path.join(DATA, "prediction_ledger.csv")
    keys = ["ticker", "analysis_date", "forecast_version", "scenario", "metric", "metric_kind",
            "forecast_period", "forecast_value", "unit", "probability", "confidence", "thesis"]
    with open(out, "w", encoding="utf-8-sig") as f:
        f.write(",".join(keys) + "\n")
        for r in preds:
            vals = []
            for k in keys:
                v = r.get(k, "")
                v = "" if v is None else str(v)
                vals.append('"%s"' % v.replace('"', "'").replace(",", ";").replace("\n", " "))
            f.write(",".join(vals) + "\n")
    print("✓ %s (%d rows)" % (out, len(preds)))


# ---------------------------------------------------------------- main
def main():
    p = argparse.ArgumentParser(description="Alpha Radar Prediction Ledger v1.1")
    sub = p.add_subparsers(dest="cmd", required=True)

    q = sub.add_parser("predict", help="追加一条预测 (永不覆盖，改数必须升版本)")
    q.add_argument("--ticker", required=True)
    q.add_argument("--metric", required=True, help="见 `metrics` 子命令")
    q.add_argument("--period", required=True, help="FY2030 / 2030 / Q3FY2027")
    q.add_argument("--value", type=float, required=True)
    q.add_argument("--unit", default="USD", help="USD/TWD/HKD/CNY/%%/X ...")
    q.add_argument("--scenario", default="Base", choices=["Bear", "Base", "Bull"])
    q.add_argument("--prob", type=float, default=None, help="该情景概率 0-1，如 0.45")
    q.add_argument("--confidence", default="Medium", choices=["Low", "Medium", "High"])
    q.add_argument("--version", default="v1")
    q.add_argument("--date", default=None, help="分析日期 (默认今天)")
    q.add_argument("--thesis", default="")
    q.add_argument("--basis", default="", help="预测依据 / 数据来源")
    q.add_argument("--allow-custom", action="store_true", help="绕过指标词表")
    q.add_argument("--allow-duplicate", action="store_true")
    q.add_argument("--force", action="store_true")
    q.set_defaults(func=cmd_predict)

    q = sub.add_parser("actual", help="追加一条实际值 (校验单位一致性)")
    q.add_argument("--ticker", required=True)
    q.add_argument("--metric", required=True)
    q.add_argument("--period", required=True)
    q.add_argument("--value", type=float, required=True)
    q.add_argument("--unit", default="USD")
    q.add_argument("--date", default=None)
    q.add_argument("--source", default="")
    q.add_argument("--fx", default="", help="汇率假设，如 TWD/USD=32.0")
    q.add_argument("--attribution", default=None,
                   help="误差归因: Demand/MarketShare/Margin/CapEx/Management/M&A/Macro/FX/Valuation")
    q.add_argument("--allow-custom", action="store_true")
    q.add_argument("--force", action="store_true", help="单位不一致时强制录入（会留痕并被排除评分）")
    q.set_defaults(func=cmd_actual)

    q = sub.add_parser("decision", help="[D-05] 追加一条投资决策（不可修改）")
    q.add_argument("--ticker", required=True)
    q.add_argument("--action", required=True,
                   help="Watch/Starter/Buy/StrongBuy/Core/Hold/Trim/Exit")
    q.add_argument("--price", type=float, required=True, help="决策当时的股价")
    q.add_argument("--currency", default="USD")
    q.add_argument("--weight", type=float, default=None, help="目标仓位百分比 0-100")
    q.add_argument("--prev-weight", type=float, default=None)
    q.add_argument("--odds", type=float, default=None, help="赔率（上行/下行），如 0.5")
    q.add_argument("--fair-value", type=float, default=None)
    q.add_argument("--thesis", default="")
    q.add_argument("--reason", default="")
    q.add_argument("--date", default=None)
    q.set_defaults(func=cmd_decision)

    q = sub.add_parser("decisions", help="[D-05] 列出决策历史")
    q.add_argument("--ticker", default=None)
    q.set_defaults(func=cmd_decisions)

    q = sub.add_parser("due", help="[D-06] 列出已到期但尚未复盘的预测")
    q.add_argument("--ticker", default=None)
    q.add_argument("--asof", default=None, help="基准日期 (默认今天)")
    q.add_argument("--lag", type=int, default=DEFAULT_RESOLVE_LAG_DAYS,
                   help="期末之后多少天应有财报可核对 (默认 %d)" % DEFAULT_RESOLVE_LAG_DAYS)
    q.set_defaults(func=cmd_due)

    q = sub.add_parser("attribute", help="[D-09] 事后补记误差归因（不覆盖 actual）")
    q.add_argument("--ticker", required=True)
    q.add_argument("--metric", required=True)
    q.add_argument("--period", required=True)
    q.add_argument("--attribution", required=True)
    q.add_argument("--note", default="")
    q.set_defaults(func=cmd_attribute)

    q = sub.add_parser("list", help="列出预测版本")
    q.add_argument("--ticker", default=None)
    q.set_defaults(func=cmd_list)

    q = sub.add_parser("report", help="预测 vs 实际 对照报告（Base 计分 + 区间命中 + 版本隔离）")
    q.add_argument("--ticker", default=None)
    q.add_argument("--price", action="append", default=[],
                   help="[D-05] 当前价用于计算决策回报，可重复: --price APH=92.5")
    q.add_argument("--save", action="store_true")
    q.add_argument("--out", default=None)
    q.set_defaults(func=cmd_report)

    q = sub.add_parser("export", help="导出 CSV")
    q.set_defaults(func=cmd_export)

    q = sub.add_parser("metrics", help="列出指标词表")
    q.set_defaults(func=lambda a: print(metric_menu()))

    a = p.parse_args()
    if not hasattr(a, "allow_custom"):
        a.allow_custom = False
    a.func(a)


if __name__ == "__main__":
    main()