#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""多层数据校验 —— 错误的数据导致错误的结果

起因（D-34 / D-35 / D-38）：
  D-34  年度表用下标索引平行数组 → 年份错位，FY2025 毛利报成 2.04B（实际 8.52B）
  D-35  YTD 取「最后一条」而非「最长时长」→ TTM 从 29.01B 变成 26.20B
  D-38  拿 2026-06-30 的债务去比 Yahoo 的 2025-12-31 → 产生**假警报**
  三个都不报错，前两个安静地给错数，第三个安静地骗你。

四层校验：
  L1 会计恒等式（内部）   Revenue − COGS = GrossProfit …
  L2 时间一致性（内部）   YTD 单调性；**双路 TTM 交叉验证**（直接抓 D-35）
  L3 交叉来源（外部）     SEC vs Yahoo fundamentals-timeseries，**同日比对**（抓 D-38）
  L4 量纲与合理性         正负号、区间、有限数

分级（关键：三种结论，不是两种）：
  ✅ MATCH        在紧容差内
  ⚠️ DEFINITIONAL 在松容差内 / 口径差异 / 日期不可比 → 提示，不算错
  ❌ MISMATCH     超出容差 → 真错误，退出码 1

> 为什么必须有 ⚠️ 这一级：只分对/错会产生大量假警报，
> 而假警报会训练人忽略校验器 —— 那比没有校验器更糟。

用法:
    py scripts/verify_data.py APH
    py scripts/verify_data.py ITRI --no-cross     # 跳过外部源（离线）
    py scripts/verify_data.py APH --json
"""
import argparse
import datetime as dt
import json
import os
import subprocess
import sys

try:
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
except Exception:
    pass

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SEC_DIR = os.path.join(ROOT, "analysis", "sec")
PROXY = os.environ.get("ALPHA_PROXY", "http://127.0.0.1:7897")
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36")

# 与 alpha_metrics.py 保持一致的 tag 优先级
T = {
    "revenue": ["RevenueFromContractWithCustomerExcludingAssessedTax", "Revenues"],
    "cogs": ["CostOfRevenue", "CostOfGoodsAndServicesSold"],
    "gp": ["GrossProfit"],
    "op": ["OperatingIncomeLoss"],
    "ni": ["NetIncomeLoss"],
    "ocf": ["NetCashProvidedByUsedInOperatingActivities"],
    "capex": ["PaymentsToAcquirePropertyPlantAndEquipment"],
    "sga": ["SellingGeneralAndAdministrativeExpense"],
    "rd": ["ResearchAndDevelopmentExpense"],
}
# [D-46] CapEx 可能需加上资本化软件；债务与 Yahoo 的差异通常是经营租赁负债
CAPEX_ADD = ["PaymentsToDevelopSoftware", "PaymentsForSoftware", "PaymentsToAcquireSoftware"]
LEASE_TAGS = ["OperatingLeaseLiability", "OperatingLeaseLiabilityNoncurrent"]
# Yahoo 的"operatingIncome"是调整后口径（剔重组等）；SEC 是 GAAP。
# 实测 CRM：8.331 + 重组 0.586 = 8.917 = Yahoo 分毫不差。
OP_ADD = ["RestructuringCharges", "RestructuringSettlementAndImpairmentProvisions",
          "AssetImpairmentCharges"]

# [D-46] 现金组必须与引擎一致（含短期投资），否则校验器测的是另一条路径
from importlib.util import spec_from_file_location, module_from_spec as _mfs  # noqa: E402
_s = spec_from_file_location("_amconst", os.path.join(ROOT, "scripts", "alpha_metrics.py"))
_amc = _mfs(_s); _s.loader.exec_module(_amc)
CASH_LIKE_EXTRA = _amc.CASH_LIKE_EXTRA
# Yahoo 字段名
Y = {
    "revenue": "annualTotalRevenue", "gp": "annualGrossProfit", "op": "annualOperatingIncome",
    "ni": "annualNetIncome", "ocf": "annualOperatingCashFlow",
    "capex": "annualCapitalExpenditure", "fcf": "annualFreeCashFlow",
    "debt": "annualTotalDebt", "cash": "annualCashAndCashEquivalents",
    "equity": "annualStockholdersEquity",
}
# TTM 外部交叉 —— 【决定性检查】
# 为什么必需：内部的「双路 TTM」并不真正独立 —— 两条路径都调用 F.series(...,"ytd")，
# 共享同一个 bug，所以必然一致（实测：注入 D-35 后双路仍报 Δ0.000%）。
# Yahoo trailing 是完全独立的编制管道，它才是能真正拓测 YTD 选择错误的检查。
TTM_Y = {"revenue": "trailingTotalRevenue", "ni": "trailingNetIncome",
         "ocf": "trailingOperatingCashFlow",
         # [D-53] capex/FCF 也必须交叉 —— MSFT 的 CapEx TTM 曾因财年边界错误
         # 报成 167.35B（真值 115.95B），当时它不在交叉范围内，所以静默通过了。
         "capex": "trailingCapitalExpenditure",
         "fcf": "trailingFreeCashFlow"}
# 资产负债表项为【时点值】，必须用 instant 取数，不能用年度区间的 key 去查
BAL = {
    "cash": ["CashAndCashEquivalentsAtCarryingValue"] + CASH_LIKE_EXTRA,
    "equity": ["StockholdersEquity"],
    "debt": ["LongTermDebtAndCapitalLeaseObligationsIncludingCurrentMaturities",
             "DebtLongtermAndShorttermCombinedAmount",
             "LongTermDebt", "LongTermDebtNoncurrent",
             "DebtInstrumentCarryingAmount"],
}

R = []          # results
HARD = 0        # MISMATCH 计数


def rec(level, verdict, name, detail):
    global HARD
    R.append({"layer": level, "verdict": verdict, "name": name, "detail": detail})
    if verdict == "MISMATCH":
        HARD += 1
    icon = {"MATCH": "✅", "DEF": "⚠️ ", "MISMATCH": "❌"}[verdict]
    print("  %s %-42s %s" % (icon, name, detail))


def close(a, b, tol):
    if a is None or b is None:
        return None
    d = abs(a - b)
    base = max(abs(a), abs(b), 1e-9)
    return d / base <= tol


def pctdiff(a, b):
    if a is None or b is None:
        return None
    return (b - a) / abs(a) * 100 if a else None


# ══════════════════════════════════════════════════════════════════
sys.path.insert(0, os.path.join(ROOT, "scripts"))
import importlib.util
_spec = importlib.util.spec_from_file_location("am", os.path.join(ROOT, "scripts", "alpha_metrics.py"))
am = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(am)


def ytd_map(F, tags):
    _, v, d = F.series(tags, "ytd")
    return dict(zip(d, v))


def annual_map(F, tags):
    _, v, d = F.series(tags, "annual")
    return dict(zip(d, v))


def instant_map(F, tags):
    """时点值（资产负债表项）—— **合并所有 tag**，同日期时前面的 tag 优先

    [D-55] 旧实现只返回"第一个有数据的 tag"的序列 → 若该 tag 早已停用，
    最新日期就永远取不到，交叉比对会静默退化成"日期不可比"（假阴性）。
    实测：MSFT 的 debt 比对因此被跳过。
    """
    out = {}
    for tag in tags:
        for it in F._items(tag):
            if "start" in it:
                continue
            if it["end"] not in out:      # 前面的 tag 优先
                out[it["end"]] = it["val"]
    return out


def fy_ends(F, tags=None):
    """财年结束日列表（升序）。[D-44] 非自然年财年（如 INTU 7月结束）必需。"""
    _, _, ad = F.series(tags or T["revenue"], "annual")
    return sorted(ad)


def fy_of(date, fyes):
    """date 属于哪个财年：结束日 ≥ date 且相距 ≤ 400 天的最小财年
    [D-44/D-47] 不能只用 `date <= e`：若财年列表有缺口（如早期用不同 revenue tag），
    远古日期会被映射到很晚的财年 → 同一桶里混了不同年份 → 34 处假"异常下降"。
    """
    d = dt.date.fromisoformat(date)
    for e in fyes:
        ed = dt.date.fromisoformat(e)
        if d <= ed and (ed - d).days <= 400:
            return e
    return None


def ytd_records(F, tags):
    """每个结束日的【最长时长】记录 → {end: (dur, start, val)}"""
    for tag in tags:
        rows = {}
        for it in F._items(tag):
            if "start" not in it:
                continue
            n = (dt.date.fromisoformat(it["end"]) - dt.date.fromisoformat(it["start"])).days
            if not (60 <= n <= 400):
                continue
            if it["end"] not in rows or n > rows[it["end"]][0]:
                rows[it["end"]] = (n, it["start"], it["val"])
        if rows:
            return rows
    return {}


def _minus1y(d):
    """返回 d 的上一年同日（2/29 → 2/28）"""
    try:
        return d.replace(year=d.year - 1)
    except ValueError:
        return d.replace(year=d.year - 1, day=28)


def fy_candidates(F, tags=None):
    """候选财年末 —— 已结束的 + 向后续推的。
    [D-48] 必须包含【尚未结束】的本财年，否则当年 YTD 记录归属不到任何财年，
    会被静默丢掉（表现为 ttm_path2 算不出 4 个季度）。
    """
    ends = fy_ends(F, tags)
    if not ends:
        return ends
    cands = set(ends)
    base = dt.date.fromisoformat(ends[-1])
    for i in range(1, 6):
        try:
            cands.add(base.replace(year=base.year + i).isoformat())
        except ValueError:
            cands.add(base.replace(year=base.year + i, day=28).isoformat())
    return sorted(cands)


def ytd_sequences(F, tags):
    """按【财年】分组的 YTD 序列  {fy_end: [(date, ytd), ...]}

    [D-44/D-47/D-48] 三个精确性要求，缺一不可：
      1. 按财年而非自然年分组（INTU 7 月结账）
      2. **记录的起点必须就是本财年的起点**（±15 天）——
         否则会把跨年度的 trailing 值当成本财年累计
      3. 候选财年末必须向后续推，覆盖**尚未结束**的本财年
    """
    recs = ytd_records(F, tags)
    fyes = fy_candidates(F, tags)
    out = {}
    for d_ in sorted(recs):
        n, st, v = recs[d_]
        dd = dt.date.fromisoformat(d_)
        stt = dt.date.fromisoformat(st)
        for e in fyes:
            ed = dt.date.fromisoformat(e)
            if dd <= ed and (ed - dd).days <= 400:
                fy_start = _minus1y(ed) + dt.timedelta(days=1)
                if abs((stt - fy_start).days) <= 15:
                    out.setdefault(e, []).append((d_, v))
                break
    for e in out:
        out[e].sort()
    return out


def ttm_path2(F, tags):
    """第二条路径：最近 4 个离散季度之和（Q4 = FY − 9M）—— 按【财年】计算"""
    amap = annual_map(F, tags)
    ym = ytd_map(F, tags)
    if not ym or not amap:
        return None, None
    q_end = sorted(ym)[-1]
    seqs = ytd_sequences(F, tags)
    fy = fy_of(q_end, fy_candidates(F, tags))
    if not fy:
        return None, None
    cur = seqs.get(fy, [])
    # 当前财年内已披露的离散季度
    qs, prev = [], 0.0
    for d_, v_ in cur:
        if d_ > q_end:
            break
        qs.append((d_, v_ - prev))
        prev = v_
    if not qs or qs[-1][0] != q_end:
        return None, None
    need = 4 - len(qs)
    prior = []
    if need > 0:
        fyes = fy_candidates(F, tags)
        i = fyes.index(fy)
        if i == 0:
            return None, None
        pf = fyes[i - 1]
        pseq = seqs.get(pf, [])
        if not pseq:
            return None, None
        for j, (d_, v_) in enumerate(pseq):
            pv = pseq[j - 1][1] if j else 0.0
            prior.append((d_, v_ - pv))
        # 补 Q4（= 财年 − 9M）
        if amap.get(pf) is not None and (not prior or prior[-1][0] != pf):
            ytd9 = pseq[-1][1]
            prior.append((pf, amap[pf] - ytd9))
        prior = prior[-need:]
    if len(qs) + len(prior) < 4:
        return None, None
    total = sum(v for _, v in qs) + sum(v for _, v in prior)
    return total, q_end


def close_enough(a, b, tol_pct):
    """[D-47] 不能写 `pctdiff(...) or 99` —— pctdiff 返回 0.0 时是 falsy，
    `0.0 or 99` 会得到 99，从而静默地关闭检查（完全相等的两个值反而判为失败）。
    """
    d = pctdiff(a, b)
    return d is not None and abs(d) < tol_pct


def _sum_annual(F, tags, y0):
    """y0 年度的各 tag 之和（只计有该年度数据的 tag）"""
    tot, used = 0.0, []
    for t in tags:
        a = annual_map(F, [t])
        if y0 in a:
            tot += a[y0]
            used.append(t)
    return tot, used


# [D-46/D-53] 已知的口径差异 —— 每一项都经实测精确对账到小数点后三位。
# 遇到差异时先试这些；能对上就归入 DEFINITIONAL 而不是 MISMATCH。
RECON = [
    ("capex", "资本化软件", [CAPEX_ADD], "annual"),
    ("op", "重组/减值等调整项", [OP_ADD], "annual"),
    # [D-54/D-55] 第三方（Yahoo）的债务口径与我们不同，且不止一种：
    #   Yahoo 反而计【经营租赁非流动】、不计【融资租赁】。
    #   既然口径不统一，校验目标就不是"相等"，而是"**能解释差异**"。
    ("debt", "经营租赁非流动", [["OperatingLeaseLiabilityNoncurrent"]], "instant"),
    ("debt", "经营租赁合计", [["OperatingLeaseLiability"]], "instant"),
    ("debt", "融资租赁", [["FinanceLeaseLiability"]], "instant"),
    ("debt", "经营租赁非流动+融资租赁",
     [["OperatingLeaseLiabilityNoncurrent", "FinanceLeaseLiability"]], "instant"),
]


def try_reconcile(F, k, y0, va, vb):
    """返回 (差异百分数, 说明) 或 (None, 部分说明)

    逐个尝试候选调整项；只要有一组能把差异解释到 0.5% 以内，
    就归入 DEFINITIONAL 而不是 MISMATCH。
    """
    partial = ""
    for key, label, tag_sets, kind in RECON:
        if key != k:
            continue
        for tags in tag_sets:
            if kind == "instant":
                m = instant_map(F, tags)
                add = m.get(y0)
            else:
                add, _used = _sum_annual(F, tags, y0)
            if not add:
                continue
            if close_enough(va + add, vb, 0.5):
                return pctdiff(va + add, vb), \
                    "%.4fB + %s %.4fB = %.4fB = 第三方 %.4fB ✓（口径差异，非错误）" % (
                        va / 1e9, label, add / 1e9, (va + add) / 1e9, vb / 1e9)
            partial = "（已试 %s = %.4fB，不足以完全解释）" % (label, add / 1e9)
    return None, partial


def fetch_yahoo(ticker, types):
    url = ("https://query1.finance.yahoo.com/ws/fundamentals-timeseries/v1/finance/timeseries/%s"
           "?symbol=%s&type=%s&period1=1451606400&period2=2000000000" % (ticker, ticker, ",".join(types)))
    for proxy in (None, PROXY):
        cmd = ["curl", "-s", "--max-time", "30", "-A", UA]
        if proxy:
            cmd += ["-x", proxy]
        cmd.append(url)
        try:
            p = subprocess.run(cmd, capture_output=True, text=True,
                               encoding="utf-8", errors="replace")
            if p.returncode != 0 or not (p.stdout or "").strip():
                continue
            d = json.loads(p.stdout)
            res = (d.get("timeseries") or {}).get("result") or []
            if not res:
                continue
            out = {}
            for r in res:
                t = r["meta"]["type"][0]
                out[t] = {v["asOfDate"]: v["reportedValue"]["raw"]
                          for v in (r.get(t) or []) if v}
            return out, ("yahoo直连" if proxy is None else "yahoo代理")
        except Exception:
            continue
    return None, None


def main():
    global R, HARD
    ap = argparse.ArgumentParser(description="多层数据校验")
    ap.add_argument("ticker", nargs="?", help="股票代码；或用 --all 校验全部已下载公司")
    ap.add_argument("--all", action="store_true", help="校验 analysis/sec/*_facts.json 里的全部公司")
    ap.add_argument("--no-cross", action="store_true", help="跳过 L3 外部交叉校验")
    ap.add_argument("--require-cross", action="store_true",
                    help="外部源不可用时视为失败（CI 用；否则仅告警并退出 0）")
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args()

    if a.all:
        import glob
        files = sorted(glob.glob(os.path.join(SEC_DIR, "*_facts.json")))
        tks = [os.path.basename(f).replace("_facts.json", "").upper() for f in files]
        if not tks:
            print("✗ analysis/sec/ 下没有 *_facts.json，先跑 alpha_fetch.py")
            return 1
        bad = 0
        for i, tk in enumerate(tks):
            if i:
                print("\n" + "#" * 78 + "\n")
            ns = argparse.Namespace(ticker=tk, all=False, no_cross=a.no_cross,
                                    require_cross=a.require_cross, json=False)
            bad += _run_one(ns)
        print("\n" + "=" * 78)
        print("  全量校验: %d 家公司，%d 家存在硬错误" % (len(tks), bad))
        print("__VERIFY_%s__ ALL" % ("PASS" if bad == 0 else "FAIL"))
        return 0 if bad == 0 else 1

    if not a.ticker:
        ap.error("需要 ticker 或 --all")
    return _run_one(a)


def _run_one(a):
    global R, HARD
    tk = a.ticker.upper()
    R = []
    HARD = 0
    path = os.path.join(SEC_DIR, "%s_facts.json" % tk.lower())
    if not os.path.exists(path):
        print("✗ 找不到 %s，先跑: py scripts/alpha_fetch.py %s" % (path, tk))
        return 1

    F = am.Facts(path)
    print("多层数据校验 —— %s" % tk)
    print("实体: %s" % F.entity)
    print("=" * 78)

    # ─────────────────────────── L1 会计恒等式
    print("\n[L1] 会计恒等式（内部一致性）")
    rev = annual_map(F, T["revenue"])
    cogs = annual_map(F, T["cogs"])
    gp = annual_map(F, T["gp"])
    op = annual_map(F, T["op"])
    sga = annual_map(F, T["sga"])
    rd = annual_map(F, T["rd"])
    # [D-45] 不能静默什么都不做：若关键 tag 缺失，必须明确报出"无法校验"
    missing = [k for k, v in (("Revenue", rev), ("OpInc", op)) if not v]
    if not gp:
        missing.append("GrossProfit（该公司不单列毛利）")
    if missing:
        rec("L1", "DEF", "会计恒等式可执行性",
            "缺少 %s → 相关恒等式**无法校验**（不等于通过）" % ", ".join(missing))
    years = sorted(set(rev) & set(gp))[-3:] if gp else []
    if not years and rev and op:
        years = sorted(set(rev) & set(op))[-3:]
    for y in years:
        if y in cogs and y in gp:
            calc = rev[y] - cogs[y]
            ok = close(calc, gp[y], 0.005)
            rec("L1", "MATCH" if ok else "MISMATCH", "Revenue − COGS = GrossProfit (%s)" % y,
                "%.4fB − %.4fB = %.4fB vs 报表 %.4fB (Δ%.2f%%)"
                % (rev[y] / 1e9, cogs[y] / 1e9, calc / 1e9, gp[y] / 1e9,
                   abs(pctdiff(calc, gp[y]) or 0)))
        if y in gp and y in op:
            rec("L1", "MATCH", "GrossProfit > OpInc (%s)" % y,
                "%.4fB > %.4fB" % (gp[y] / 1e9, op[y] / 1e9) if gp[y] > op[y]
                else "❌ %.4fB vs %.4fB" % (gp[y] / 1e9, op[y] / 1e9))
        if y in gp and y in op and y in sga:
            sub = gp[y] - sga[y] - rd.get(y, 0)
            d = abs(pctdiff(op[y], sub) or 0)
            rec("L1", "MATCH" if d < 3 else "DEF",
                "GrossProfit − SG&A − R&D ≈ OpInc (%s)" % y,
                "%.4fB vs %.4fB (Δ%.1f%%) %s" % (sub / 1e9, op[y] / 1e9, d,
                                                 "" if d < 10 else "← 口径差异，需人工确认"))

    # ─────────────────────────── L2 时间一致性
    print("\n[L2] 时间一致性（内部一致性）")

    # YTD 单调性 —— [D-44/D-47] 按财年；[D-49] 只对【收入】成立
    # 累计经营现金流/NI 完全可能 Q1 为负、年末转正，**本来就不单调** ——
    # 把一个收入特有的性质套到所有流量上会产生大量假警报。
    bad = []
    for tag_key in ("revenue",):
        for fy, seq in ytd_sequences(F, T[tag_key]).items():
            for i in range(1, len(seq)):
                if seq[i][1] < seq[i - 1][1] * 0.9:
                    bad.append("%s %s" % (fy, seq[i][0]))
    rec("L2", "MATCH" if not bad else "MISMATCH", "YTD 累计序列单调性（收入）",
        "无异常下降" if not bad else "%d 处异常下降: %s" % (len(bad), ", ".join(bad[:3])))
    # NI / OCF 只做"累计值不应超出财年总额的合理倍数"的宽松检查
    loose = []
    for tag_key in ("ni", "ocf"):
        amap_ = annual_map(F, T[tag_key])
        for fy, seq in ytd_sequences(F, T[tag_key]).items():
            if fy not in amap_ or not seq:
                continue
            tot = amap_[fy]
            for d_, v_ in seq:
                if abs(tot) > 1e7 and abs(v_) > abs(tot) * 3:
                    loose.append("%s@%s" % (tag_key, d_))
    rec("L2", "MATCH" if not loose else "DEF", "NI/OCF 累计量级宽松检查",
        "无越界" if not loose else "%d 处偏离（可能跨境/一次性项）: %s" % (len(loose), ", ".join(loose[:3])))

    # 双路 TTM 交叉 —— 注意：这不是独立检查（两路共享 ytd 原语）
    for tag_key, label in (("revenue", "Revenue"), ("ni", "NetIncome"), ("ocf", "OCF")):
        p1 = F.ttm(T[tag_key])
        p2, qe = ttm_path2(F, T[tag_key])
        if p1 is None or p2 is None:
            rec("L2", "DEF", "双路 TTM 交叉 %s" % label, "无法计算第二条路径，跳过")
            continue
        d = abs(pctdiff(p1, p2) or 0)
        rec("L2", "MATCH" if d < 0.5 else "MISMATCH",
            "双路 TTM 交叉 %s (截至 %s)" % (label, qe),
            "路径1 %.4fB = 路径2 %.4fB (Δ%.3f%%) [两路共享 ytd 原语，独立性有限]" % (p1 / 1e9, p2 / 1e9, d))

    # [D-35 结构性断言] ytd map 中每个结束日必须是该日**最长时长**的记录
    # 此断言直接从原始 items 重算，不复用 alpha_metrics 的 series()，所以是独立的
    miss = []
    for tag in T["revenue"]:
        if tag not in F.tax:
            continue
        best = {}
        for it in F._items(tag):
            if "start" not in it:
                continue
            n = (dt.date.fromisoformat(it["end"]) - dt.date.fromisoformat(it["start"])).days
            if not (60 <= n <= 400):
                continue
            if it["end"] not in best or n > best[it["end"]][0]:
                best[it["end"]] = (n, it["val"])
        got = ytd_map(F, [tag])
        for d_, (n_, v_) in best.items():
            if abs(got.get(d_, 0) - v_) > 1:
                miss.append("%s 取了 %s 而非最长时长记录" % (d_, d_))
        break
    rec("L2", "MATCH" if not miss else "MISMATCH", "YTD 取最长时长断言",
        "每个结束日均取到最长时长记录" if not miss else "; ".join(miss[:3]))

    # [D-42/D-46/D-50] 净债务校验 —— 同一条路径 + 独立重算数值
    # 三次踩同一个坑（测了引擎没走的路径），根源都是两边解析路径不同。
    # 现在：引擎与校验器共用 F.balance_sheet()，只把【数值】独立重算。
    asof, bsv, bstag = F.balance_sheet()
    if not asof:
        rec("L2", "DEF", "资产负债表解析", "无法确定共同日期")
    else:
        # 独立重算：该日期上所有现金类 tag 之和（逐条重算，不用引擎的求和结果）
        exp_cash, seen = 0.0, []
        for t in am.CASH_TAGS + am.CASH_LIKE_EXTRA:
            rows = {it["end"]: it["val"] for it in F._items(t) if "start" not in it}
            if asof in rows:
                v = rows[asof]
                if any(abs(v - x) < 1 for x in seen):
                    continue
                exp_cash += v; seen.append(v)
        exp_debt = None
        for t in am.DEBT_TAGS:
            rows = {it["end"]: it["val"] for it in F._items(t) if "start" not in it}
            if asof in rows:
                exp_debt = rows[asof]; break
        # [D-54] 融资租赁必须计入总债务；独立重算要跟上引擎的定义
        fl_eng, _ = F.finlease_at(asof)
        if exp_debt is not None:
            exp_debt += (fl_eng or 0.0)
        eng_cash, eng_debt = bsv.get("cash"), bsv.get("debt")
        if not close_enough(eng_cash, exp_cash, 0.5) or not close_enough(eng_debt, exp_debt, 0.5):
            rec("L2", "MISMATCH", "净债务独立重算（同日 %s）" % asof,
                "引擎 现金%.4fB/债务%.4fB vs 独立 现金%.4fB/债务%.4fB"
                % ((eng_cash or 0) / 1e9, (eng_debt or 0) / 1e9, exp_cash / 1e9, (exp_debt or 0) / 1e9))
        else:
            rec("L2", "MATCH", "净债务独立重算（同日 %s）" % asof,
                "现金 %.4fB（%d 个 tag 之和）/ 债务 %.4fB（含融资租赁 %.4fB）→ 净债务 %.4fB"
                % (eng_cash / 1e9, len(seen), eng_debt / 1e9, (fl_eng or 0) / 1e9,
                   (eng_debt - eng_cash) / 1e9))

    # TTM 应落在两个财年的合理包络内
    # [D-40] 不能写死"公司一定在增长"：初版假设 TTM ≥ 上一财年，
    #        结果 ITRI（收入下滑）被判为硬错误 —— 假警报。
    #        改为对称包络：允许下滑，也允许增长。
    rt = F.ttm(T["revenue"])
    if rt and len(rev) >= 2:
        # [D-41] 又犯了 D-34 的错：把「最新年份的标签」和「最大值」混在一起用。
        #        标签与数值必须来自同一个 key，不能各自取。
        years_sorted = sorted(rev)
        last_y, prev_y = years_sorted[-1], years_sorted[-2]
        last_v, prev_v = rev[last_y], rev[prev_y]
        lo, hi = 0.5 * min(last_v, prev_v), 1.6 * max(last_v, prev_v)
        inrange = lo <= rt <= hi
        rec("L2", "MATCH" if inrange else "MISMATCH", "TTM 量级合理性",
            "TTM %.4fB 落在包络 [%.4fB, %.4fB]" % (rt / 1e9, lo / 1e9, hi / 1e9)
            if inrange else "TTM %.4fB 超出包络 [%.4fB, %.4fB]" % (rt / 1e9, lo / 1e9, hi / 1e9))
        # 把收入趋势作为【信息】报出，而不是用合理性检查去隐式表达
        trend = (rt / last_v - 1) * 100
        rec("L2", "MATCH", "收入趋势（信息项，非错误）",
            "TTM %.4fB vs FY%s %.4fB → %+.1f%%%s"
            % (rt / 1e9, last_y[:4], last_v / 1e9, trend,
               "（**下滑**，与 APH 反向）" if trend < -1 else ""))

    # ─────────────────────────── L3 交叉来源
    if not a.no_cross:
        print("\n[L3] 交叉来源（SEC vs Yahoo，必须同日比对）")
        ydata, ysrc = fetch_yahoo(tk, list(Y.values()) + list(TTM_Y.values()))
        if not ydata:
            if a.require_cross:
                rec("L3", "MISMATCH", "外部源可用性",
                    "Yahoo 不可达，但指定了 --require-cross → 视为失败")
            else:
                rec("L3", "DEF", "外部源可用性",
                    "⚠️ Yahoo 不可达，**本次仅有内部校验**（内部双路不独立，无法捕获 YTD 类错误）")
        else:
            print("      源: %s" % ysrc)
            # ── TTM 外部交叉（决定性）
            print("      ── TTM 外部交叉（独立于 YTD 选择逻辑）──")
            # 我的 TTM 截止日
            _, _, _yd = F.series(T["revenue"], "ytd")
            my_q = _yd[-1] if _yd else None
            for k, ykey in TTM_Y.items():
                if ykey not in ydata:
                    continue
                yv = ydata[ykey]
                mine = F.ttm(T[k]) if k in T else None
                if k == "capex":
                    mine = F.ttm(am.CAPEX_TAGS, add_tags=am.CAPEX_ADD_TAGS)
                elif k == "fcf":
                    _o = F.ttm(T["ocf"])
                    _c = F.ttm(am.CAPEX_TAGS, add_tags=am.CAPEX_ADD_TAGS)
                    mine = (_o - _c) if (_o is not None and _c is not None) else None
                hit = yv.get(my_q) if my_q else None
                if hit is None:
                    rec("L3", "DEF", "TTM 交叉 %s" % k,
                        "Yahoo 无 %s 日期的 trailing 值（有: %s）" % (my_q, sorted(yv)[-3:]))
                    continue
                if k == "capex":
                    hit = abs(hit)
                    mine = abs(mine) if mine is not None else None
                    # 第三方 capex 可能还包含购入的无形资产（实测 NOW：0.850+0.044=0.894 ✓）
                    alt = F.ttm(am.CAPEX_TAGS,
                                add_tags=am.CAPEX_ADD_TAGS + ["PaymentsToAcquireIntangibleAssets"],
                                q_end=(q_end_for := my_q))
                    if alt is not None and close_enough(abs(alt), hit, 0.5):
                        rec("L3", "DEF", "TTM capex @%s【口径】" % my_q,
                            "%.4fB(P\u0026E+软件) + 无形资产 → %.4fB = 第三方 %.4fB ✓"
                            % (abs(mine or 0) / 1e9, abs(alt) / 1e9, hit / 1e9))
                        continue
                d = abs(pctdiff(mine, hit) or 0) if mine is not None else 99
                rec("L3", "MATCH" if d < 0.5 else "DEF" if d < 2 else "MISMATCH",
                    "TTM %s @%s（我 vs Yahoo trailing）" % (k, my_q),
                    "%.4fB vs %.4fB (Δ%.2f%%)%s" % ((mine or 0) / 1e9, hit / 1e9, d,
                                                    "" if d < 2 else "  ← **TTM 算错了**"))

            # [D-56] 去年同期 TTM 也必须交叉 —— TTM YoY 靠它，错一位数就变 0.0%
            prior_q = None
            if my_q:
                _d = dt.date.fromisoformat(my_q)
                prior_q = _d.replace(year=_d.year - 1).isoformat()
            for k, ykey in TTM_Y.items():
                if ykey not in ydata or not prior_q:
                    continue
                h2 = ydata[ykey].get(prior_q)
                if h2 is None:
                    continue
                if k == "fcf":
                    _o = F.ttm(T["ocf"], q_end=prior_q)
                    _c = F.ttm(am.CAPEX_TAGS, add_tags=am.CAPEX_ADD_TAGS, q_end=prior_q)
                    m2 = (_o - _c) if (_o is not None and _c is not None) else None
                elif k == "capex":
                    m2 = F.ttm(am.CAPEX_TAGS, add_tags=am.CAPEX_ADD_TAGS, q_end=prior_q)
                    h2, m2 = abs(h2), abs(m2) if m2 is not None else None
                    alt2 = F.ttm(am.CAPEX_TAGS,
                                 add_tags=am.CAPEX_ADD_TAGS + ["PaymentsToAcquireIntangibleAssets"],
                                 q_end=prior_q)
                    if alt2 is not None and close_enough(abs(alt2), h2, 0.5):
                        rec("L3", "DEF", "去年同期 TTM capex @%s【口径】" % prior_q,
                            "+ 购入无形资产 → %.4fB = 第三方 %.4fB ✓" % (abs(alt2) / 1e9, h2 / 1e9))
                        continue
                else:
                    m2 = F.ttm(T[k], q_end=prior_q)
                d2 = abs(pctdiff(m2, h2) or 0) if m2 is not None else 99
                if d2 >= 2:
                    rec("L3", "DEF" if d2 < 10 else "MISMATCH", "去年同期 TTM %s @%s" % (k, prior_q),
                        "%.4fB vs %.4fB (Δ%.2f%%)%s"
                        % ((m2 or 0) / 1e9, h2 / 1e9, d2,
                           "（口径差异，幅度 <10%%）" if d2 < 10 else " ← **去年同期算错**"))
                else:
                    rec("L3", "MATCH", "去年同期 TTM %s @%s" % (k, prior_q),
                        "%.4fB vs %.4fB (Δ%.2f%%)" % ((m2 or 0) / 1e9, h2 / 1e9, d2))

            for k, ykey in Y.items():
                if ykey not in ydata:
                    continue
                yv = ydata[ykey]
                sv = (instant_map(F, BAL[k]) if k in BAL
                      else annual_map(F, T[k]) if k in T else {})
                common = sorted(set(yv) & set(sv))
                if not common:
                    ylast = sorted(yv)[-1] if yv else "?"
                    slast = sorted(sv)[-1] if sv else "?"
                    if ylast != slast:
                        rec("L3", "DEF", "同一日期比对 %s" % k,
                            "Yahoo 最新 %s vs SEC 最新 %s → **日期不同不可比**（勿误判为错误，见 D-38）"
                            % (ylast, slast))
                    else:
                        rec("L3", "DEF", "同一日期比对 %s" % k, "无共同日期")
                    continue
                y0 = common[-1]
                va, vb = sv[y0], abs(yv[y0]) if k == "capex" else yv[y0]
                va = abs(va) if k == "capex" else va
                d = abs(pctdiff(va, vb) or 0)
                extra = ""
                # [D-46/D-53] 先试已知口径对账
                rd_, rdesc = try_reconcile(F, k, y0, va, vb)
                if rd_ is not None:
                    rec("L3", "DEF", "SEC ≈ Yahoo: %s (%s)【口径】" % (k, y0), rdesc)
                    continue
                extra = rdesc
                if d < 0.5:
                    rec("L3", "MATCH", "SEC = Yahoo: %s (%s)" % (k, y0),
                        "%.4fB = %.4fB" % (va / 1e9, vb / 1e9))
                elif d < 5:
                    rec("L3", "DEF", "SEC ≈ Yahoo: %s (%s)" % (k, y0),
                        "%.4fB vs %.4fB (Δ%.2f%%) ← 聚合口径差异%s" % (va / 1e9, vb / 1e9, d, extra))
                else:
                    rec("L3", "MISMATCH", "SEC vs Yahoo: %s (%s)" % (k, y0),
                        "%.4fB vs %.4fB (Δ%.1f%%) ← **需查明**%s" % (va / 1e9, vb / 1e9, d, extra))

            # FCF 在 SEC 里是派生量（OCF − CapEx），单独处理
            if "annualFreeCashFlow" in ydata:
                yo = ydata.get("annualOperatingCashFlow", {})
                yc = ydata.get("annualCapitalExpenditure", {})
                so = annual_map(F, T["ocf"])
                sc = annual_map(F, T["capex"])
                common = sorted(set(ydata["annualFreeCashFlow"]) & set(so) & set(sc))
                if common:
                    y0 = common[-1]
                    sec_fcf = so[y0] - sc[y0]
                    yh_fcf = ydata["annualFreeCashFlow"][y0]
                    d = abs(pctdiff(sec_fcf, yh_fcf) or 0)
                    rec("L3", "MATCH" if d < 1 else "DEF",
                        "SEC(OCF−CapEx) = Yahoo FCF (%s)" % y0,
                        "%.4fB vs %.4fB (Δ%.2f%%)" % (sec_fcf / 1e9, yh_fcf / 1e9, d))
                else:
                    rec("L3", "DEF", "FCF 派生量交叉", "无共同日期，跳过")

    # ─────────────────────────── L4 合理性
    print("\n[L4] 量纲与合理性")
    issues = []
    for y in years:
        if rev.get(y) is not None and rev[y] <= 0:
            issues.append("Revenue %s ≤ 0" % y)
        if rev.get(y) and gp.get(y) is not None:
            gm = gp[y] / rev[y]
            if not (-0.5 < gm < 1.0):
                issues.append("GrossMargin %s = %.1f%% 越界" % (y, gm * 100))
    rec("L4", "MATCH" if not issues else "MISMATCH", "数值区间检查",
        "全部在合理区间" if not issues else "; ".join(issues))

    cap = annual_map(F, T["capex"])
    if cap:
        neg = [y for y in cap if cap[y] < 0]
        rec("L4", "DEF" if neg else "MATCH", "CapEx 符号约定",
            "SEC 为正直（付款）%s" % ("✓" if not neg else "，异常: %s" % neg))

    # ─────────────────────────── 结论
    n_ok = sum(1 for r in R if r["verdict"] == "MATCH")
    n_def = sum(1 for r in R if r["verdict"] == "DEF")
    n_bad = HARD
    print("\n" + "=" * 78)
    print("  校验结果: ✅ %d 通过 / ⚠️ %d 提示 / ❌ %d 错误" % (n_ok, n_def, n_bad))
    if n_bad:
        print("  ❌ 存在硬错误 —— 在查明之前，**不要**用这些数据写档案")
    else:
        print("  ✅ 无硬错误。⚠️ 项为口径差异或日期不可比，已列明，需人工判断是否影响结论。")
    print("=" * 78)
    print("__VERIFY_%s__ %s" % ("PASS" if n_bad == 0 else "FAIL", tk))

    if a.json:
        print(json.dumps({"ticker": tk, "results": R,
                          "ok": n_ok, "def": n_def, "bad": n_bad}, ensure_ascii=False, indent=1))
    return 0 if n_bad == 0 else 1


if __name__ == "__main__":
    sys.exit(main())