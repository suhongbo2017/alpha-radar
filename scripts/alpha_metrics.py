#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""一手财务指标计算 —— 从 SEC companyfacts 直接算 TTM / Margin / FCF / ROIC / 净债务

为什么需要它：
    报告里的每个数字都必须可追溯到一手申报，且**可复现**。
    手算 TTM 容易出错（季度是累计口径、Q4 不在 10-Q 里），所以要一个固定算法。

算法（TTM）：
    TTM = 最近年度 + 本年迄今 - 去年同期
    例：TTM(2026-06-30) = FY2025 + H1'26 - H1'25
    这样避开了「Q4 无独立季报」的问题。

用法:
    py scripts/alpha_metrics.py APH
    py scripts/alpha_metrics.py APH --json
    py scripts/alpha_metrics.py APH --years 8

数据源: analysis/sec/<ticker>_facts.json（先跑 alpha_fetch.py 取回）
"""
import argparse
import datetime as dt
import json
import os
import sys

try:
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
except Exception:
    pass

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SEC_DIR = os.path.join(ROOT, "analysis", "sec")

REV_TAGS = ["RevenueFromContractWithCustomerExcludingAssessedTax", "Revenues"]
GP_TAGS = ["GrossProfit"]
OP_TAGS = ["OperatingIncomeLoss"]
NI_TAGS = ["NetIncomeLoss"]
OCF_TAGS = ["NetCashProvidedByUsedInOperatingActivities"]
CAPEX_TAGS = ["PaymentsToAcquirePropertyPlantAndEquipment"]
# [D-46] 资本化软件也属于 CapEx（对内自建软件的投资），不计入会低估 CapEx / 高估 FCF。
# 实测：INTU PP&E 0.175B + 资本化软件 0.046B = 0.221B = Yahoo 完全一致
CAPEX_ADD_TAGS = ["PaymentsToDevelopSoftware", "PaymentsForSoftware",
                  "PaymentsToAcquireSoftware"]
DA_TAGS = ["DepreciationDepletionAndAmortization", "DepreciationAmortizationAndAccretionNet",
           # INTU 等用现金流量表里的摊销调整行
           "AdjustmentForAmortization"]
TAX_TAGS = ["IncomeTaxExpenseBenefit"]
PRETAX_TAGS = ["IncomeLossFromContinuingOperationsBeforeIncomeTaxesExtraordinaryItemsNoncontrollingInterest",
               "IncomeLossFromContinuingOperationsBeforeIncomeTaxesMinorityInterestAndIncomeLossFromEquityMethodInvestments"]
# [D-46] 现金及现金等价物 —— 净债务必须扣除【短期投资】，否则会系统性高估净债务。
# 实测：APH 短期投资 0.6897B → 净债务 14.08B(错) vs 13.39B(对)
#       INTU 短期投资 2.495B → 净债务 2.96B(错) vs 0.47B(对)
CASH_TAGS = ["CashAndCashEquivalentsAtCarryingValue"]
CASH_LIKE_EXTRA = ["ShortTermInvestments", "MarketableSecuritiesCurrent",
                   "AvailableForSaleSecuritiesDebtSecuritiesCurrent",
                   "OtherShortTermInvestments",
                   # 2026+ 新 XBRL tag（INTU 等使用）
                   "DebtSecuritiesAvailableForSaleExcludingAccruedInterestCurrent",
                   "DebtSecuritiesAvailableForSaleAmortizedCostExcludingAccruedInterestAfterAllowanceForCreditLossCurrent"]
STI_TAGS = CASH_LIKE_EXTRA

EQ_TAGS = ["StockholdersEquity"]
# 债务 tag 优先级：同日期时前面的优先；跨日期时由 latest() 取【最大日期】
# 1/2 是显式口径（"含流动部分" / "长短合计"），3/4 是总分口径，5 含义模糊仅供参考
DEBT_TAGS = ["LongTermDebtAndCapitalLeaseObligationsIncludingCurrentMaturities",
             "DebtLongtermAndShorttermCombinedAmount",
             "LongTermDebt",
             "LongTermDebtNoncurrent",
             "DebtInstrumentCarryingAmount"]
SHARE_TAGS = ["WeightedAverageNumberOfDilutedSharesOutstanding", "CommonStockSharesOutstanding"]


def days(a, b):
    return (dt.date.fromisoformat(b) - dt.date.fromisoformat(a)).days


class Facts:
    def __init__(self, path):
        d = json.load(open(path, encoding="utf-8"))
        self.entity = d.get("entityName", "?")
        self.tax = d.get("facts", {}).get("us-gaap", {})

    def _items(self, tag):
        if tag not in self.tax:
            return []
        out = []
        for unit, items in self.tax[tag]["units"].items():
            if unit not in ("USD", "shares", "USD/shares"):
                continue
            out += items
        return out

    def series(self, tags, kind):
        """kind='annual'  -> 330-400 天
        kind='ytd'     -> 本年迄今：同一结束日取【最长】时长（H1 优先于 Q2）
                          [D-35] 不能取"最后一条"：同一 end 日期可能同时有
                          90 天（Q2）与 181 天（H1）两份，取错会让 TTM 偏小。
        """
        for tag in tags:
            rows = {}
            for it in self._items(tag):
                has_dur = "start" in it
                if kind == "instant":
                    if has_dur:
                        continue
                    rows[it["end"]] = it["val"]
                    continue
                if not has_dur:
                    continue
                n = days(it["start"], it["end"])
                if kind == "annual":
                    if not (330 <= n <= 400):
                        continue
                    rows[it["end"]] = it["val"]
                elif kind == "ytd":
                    if not (60 <= n <= 400):
                        continue
                    prev = rows.get(it["end"])
                    if prev is None or n > prev[0]:
                        rows[it["end"]] = (n, it["val"])
            if rows:
                if kind == "ytd":
                    rows = {k: v[1] for k, v in rows.items()}
                return tag, [rows[k] for k in sorted(rows)], sorted(rows)
        return None, [], []

    def ttm(self, tags, q_end=None):
        """TTM = 该季末之前的最近年度 + 本年迄今 - 去年同期
        q_end=None 时取最新季度。
        """
        _, av, ad = self.series(tags, "annual")
        _, yv, yd = self.series(tags, "ytd")
        if not av or not yv:
            return None
        if q_end is None:
            q_end = yd[-1]
        # 该季末之前最近的年度
        prior_fy = [(d_, v_) for d_, v_ in zip(ad, av) if d_ < q_end]
        if not prior_fy:
            return None
        fy_end, fy = prior_fy[-1]
        cur = dict(zip(yd, yv)).get(q_end)
        if cur is None:
            return None
        qd = dt.date.fromisoformat(q_end)
        tgt = qd.replace(year=qd.year - 1).isoformat()
        prior = dict(zip(yd, yv)).get(tgt)
        if prior is None:
            cand = [v_ for d_, v_ in zip(yd, yv) if d_[:5] == tgt[:5]]
            prior = cand[-1] if cand else None
        if prior is None:
            return None
        return fy + cur - prior

    def series_sum(self, base_tags, add_tags, kind="annual"):
        """[D-46] 主 tag + 附加 tag 求和（如 CapEx = PP&E + 资本化软件）
        仅在附加 tag 有同期数据时相加；无则退化为主 tag。"""
        _, bv, bd = self.series(base_tags, kind)
        if not bv:
            return [], []
        out = {d_: v_ for d_, v_ in zip(bd, bv)}
        _, av, ad = self.series(add_tags, kind)
        for d_, v_ in zip(ad, av):
            if d_ in out:
                out[d_] += v_
        ds = sorted(out)
        return [out[d] for d in ds], ds

    def instant_rows(self, tag):
        rows = {}
        for it in self._items(tag):
            if "start" in it:
                continue
            rows[it["end"]] = it["val"]     # 同日期后出现者胜（经重述后的值）
        return rows

    def balance_sheet(self):
        """[D-46/D-50] 资产负债表解析 —— **引擎与校验器共用的唯一路径**

        返回 (asof, {"cash":.., "equity":.., "debt":..}, {group: tag})

        为什么必须抽成函数：
        校验器曾三次"测了引擎从没走过的路径"而出现假绿：
          1. 只查数据可用性，不查引擎输出
          2. 用自己的 tag 列表
          3. 调 latest() 而引擎用 latest_common() + 求和
        共同源头都是：两边的解析路径不同。
        """
        cash_group = CASH_TAGS + CASH_LIKE_EXTRA
        asof, bsv, bstag = self.latest_common({"cash": cash_group,
                                               "equity": EQ_TAGS,
                                               "debt": DEBT_TAGS})
        if not asof:
            return None, {}, {}
        # cash 组：同日可能命中多个 tag（现金 + 短期投资）→ 必须【求和】
        # 但不能重复计同一个数字的多个别名（如 AFS 公允价值 vs 摊余成本）
        tot, seen, used = 0.0, [], []
        for t in cash_group:
            rows = self.instant_rows(t)
            if asof in rows:
                v = rows[asof]
                if any(abs(v - x) < 1 for x in seen):
                    continue
                tot += v
                seen.append(v)
                used.append(t)
        vals = {"cash": tot if used else bsv.get("cash"),
                "equity": bsv.get("equity"),
                "debt": bsv.get("debt")}
        tags = {"cash": used, "equity": [bstag.get("equity")], "debt": [bstag.get("debt")]}
        return asof, vals, tags

    def latest(self, tags):
        """[D-42] 在所有 tags 中取【最大日期】，同日期时按 tags 顺序优先。

        旧实现的问题：取"第一个有数据的 tag 的最后日期"。
        ITRI 实例：主 tag 只报到 2025-12-31，而
        DebtLongtermAndShorttermCombinedAmount 有 2026-06-30 的数据 → 结果停在旧日期，
        与 2026-06-30 的现金混算，净债务因此错误。
        """
        per_tag = {t: self.instant_rows(t) for t in tags}
        dates = [d for rows in per_tag.values() for d in rows]
        if not dates:
            return None, None, None
        best = max(dates)
        for t in tags:
            if best in per_tag[t]:
                return t, per_tag[t][best], best
        return None, None, None

    def latest_common(self, groups):
        """所有分组都必须有值的【最近共同日期】—— 用于保证资产负债表同日
        groups: {"cash": [...tags], "debt": [...], "equity": [...]}
        返回 (asof, {group: value}, {group: tag}) 或 (None, {}, {})
        """
        per = {}
        for g, tags in groups.items():
            per[g] = {}
            for t in tags:
                for d_, v_ in self.instant_rows(t).items():
                    per[g].setdefault(d_, (t, v_))
        if not per:
            return None, {}, {}
        common = set.intersection(*[set(v) for v in per.values()]) if per else set()
        if not common:
            return None, {}, {}
        best = max(common)
        vals = {g: per[g][best][1] for g in per}
        tags = {g: per[g][best][0] for g in per}
        return best, vals, tags


def pct(a, b):
    return (a / b * 100) if (a is not None and b) else None


def f(x, unit=""):
    if x is None:
        return "—"
    if unit == "%":
        return "%.1f%%" % x
    if unit == "x":
        return "%.2fx" % x
    a = abs(x)
    if a >= 1e12:
        return "%.2fT" % (x / 1e12)
    if a >= 1e9:
        return "%.2fB" % (x / 1e9)
    if a >= 1e6:
        return "%.1fM" % (x / 1e6)
    return "%.2f" % x


def main():
    ap = argparse.ArgumentParser(description="一手财务指标计算")
    ap.add_argument("ticker")
    ap.add_argument("--years", type=int, default=7)
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--score-inputs", action="store_true",
                    help="同时输出 alpha_score.py 的定量参数，避免手抄")
    a = ap.parse_args()

    path = os.path.join(SEC_DIR, "%s_facts.json" % a.ticker.lower())
    if not os.path.exists(path):
        print("✗ 找不到 %s —— 先跑: py scripts/alpha_fetch.py %s" % (path, a.ticker))
        return 1
    F = Facts(path)
    print("实体: %s" % F.entity)

    out = {"ticker": a.ticker.upper(), "entity": F.entity}

    # ---- 年度序列
    # [D-34] 必须按【日期】对齐，不能用下标索引平行数组：
    # 各 tag 的起始年份不同（Revenue 从 2017、GrossProfit 从 2007），
    # 用同一个 i 去取 rv[i] 和 gp[i] 会得到不同年份，静默产生错数。
    print("\n年度序列（10-K）")
    cols = [("Revenue", REV_TAGS), ("GrossProfit", GP_TAGS), ("OpInc", OP_TAGS),
            ("NetIncome", NI_TAGS), ("OCF", OCF_TAGS), ("CapEx", CAPEX_TAGS)]
    by_date = {}
    for label, tags in cols:
        _, vals, dates = F.series(tags, "annual")
        for d_, v_ in zip(dates, vals):
            by_date.setdefault(d_, {})[label] = v_
    all_dates = sorted(by_date)
    show = all_dates[-a.years:]
    print("%-14s %-10s %-10s %-10s %-10s %-10s %-10s" %
          (("年度",) + tuple(c[0] for c in cols)))
    for d_ in show:
        row = by_date[d_]
        print("%-14s %-10s %-10s %-10s %-10s %-10s %-10s" %
              ((d_[:10],) + tuple(f(row.get(c[0])) for c in cols)))
    _, rv, rd = F.series(REV_TAGS, "annual")
    _, gp, _ = F.series(GP_TAGS, "annual")
    _, op, _ = F.series(OP_TAGS, "annual")
    _, ni, _ = F.series(NI_TAGS, "annual")
    _, ocf, _ = F.series(OCF_TAGS, "annual")
    _, cx, _ = F.series(CAPEX_TAGS, "annual")
    cx_add, _ = F.series_sum(CAPEX_TAGS, CAPEX_ADD_TAGS, "annual")
    if cx_add:
        cx = cx_add

    # ---- TTM
    ttm_rev = F.ttm(REV_TAGS)
    ttm_gp = F.ttm(GP_TAGS)
    ttm_op = F.ttm(OP_TAGS)
    ttm_ni = F.ttm(NI_TAGS)
    ttm_ocf = F.ttm(OCF_TAGS)
    ttm_cx = F.ttm(CAPEX_TAGS)
    _cxa, _ = F.series_sum(CAPEX_TAGS, CAPEX_ADD_TAGS, "annual")
    _cxb, _ = F.series_sum(CAPEX_TAGS, CAPEX_ADD_TAGS, "ytd")
    if _cxa and _cxb:
        # 重新按 TTM 口径算：直接用 sum 后的年度/累计序列
        class _Tmp: pass
        tmp = _Tmp(); tmp.tax = F.tax; tmp.entity = F.entity
        import types
        g = types.MethodType(F.series_sum.__func__, tmp)
        # 用同一 TT​M 公式：FY + YTD_cur − YTD_prior
        _ad = dict(zip(F.series(CAPEX_TAGS, "annual")[2], _cxa))
        _yd = dict(zip(F.series(CAPEX_TAGS, "ytd")[2], _cxb))
        if _ad and _yd:
            _fy_d = [d for d in _ad if d <= sorted(_yd)[-1]]
            if _fy_d:
                _q = sorted(_yd)[-1]
                import datetime as _dt
                _t = _dt.date.fromisoformat(_q).replace(year=_dt.date.fromisoformat(_q).year-1).isoformat()
                if _q in _yd and _t in _yd:
                    ttm_cx = _ad[max(_fy_d)] + _yd[_q] - _yd[_t]
    ttm_da = F.ttm(DA_TAGS)
    ttm_fcf = (ttm_ocf - ttm_cx) if (ttm_ocf is not None and ttm_cx is not None) else None

    _, cash, cash_d = F.latest(CASH_TAGS)
    _, eq, eq_d = F.latest(EQ_TAGS)
    _, debt, debt_d = F.latest(DEBT_TAGS)
    # [D-42] 资产负债表三项必须同日，否则净债务/投入资本是混合口径的假数
    # [D-42] 资产负债表三项必须同日，否则净债务/投入资本是混合口径的假数
    # [D-46] 现金组 = 现金及等价物 + 短期投资（两者都具流动性）
    CASH_GROUP = CASH_TAGS + CASH_LIKE_EXTRA
    bs_date, bsv, bstag = F.latest_common({"cash": CASH_GROUP, "equity": EQ_TAGS, "debt": DEBT_TAGS})
    if bs_date:
        # cash 组可能命中多个 tag（现金 与 短期投资 分别在不同 tag），必须【求和】
        # 同日可能同时命中多个 tag（现金 与 短期投资 各一个）—— 必须求和，
        # 但不能重复计同一个 tag 的多个别名（如 AFS 公允价值与摊余成本）
        tot_cash, used, seen_val = 0.0, [], []
        for t in CASH_GROUP:
            rows = F.instant_rows(t)
            if bs_date in rows:
                v = rows[bs_date]
                if any(abs(v - x) < 1 for x in seen_val):
                    continue          # 同一数字的另一个别名，不重复计
                tot_cash += v; used.append(t); seen_val.append(v)
        cash = tot_cash if used else bsv["cash"]
        eq, debt = bsv["equity"], bsv["debt"]
        cash_d = eq_d = debt_d = bs_date

    q_end = "?"
    _, _, yd = F.series(REV_TAGS, "ytd")
    if yd:
        q_end = yd[-1]

    print("\nTTM（截至 %s）" % q_end)
    print("  Revenue          %s" % f(ttm_rev))
    print("  Gross Margin     %s" % f(pct(ttm_gp, ttm_rev), "%"))
    print("  Operating Margin %s" % f(pct(ttm_op, ttm_rev), "%"))
    print("  Net Margin       %s" % f(pct(ttm_ni, ttm_rev), "%"))
    print("  OCF              %s" % f(ttm_ocf))
    print("  CapEx            %s" % f(ttm_cx))
    print("  FCF              %s" % f(ttm_fcf))
    print("  FCF Margin       %s" % f(pct(ttm_fcf, ttm_rev), "%"))
    print("  Cash Conversion  %s" % f(pct(ttm_fcf, ttm_ni), "%"))

    # ---- 资产负债表（最新，且三项同日）
    print("\n资产负债表（最新，三项已对齐到同一日期）")
    bs_date, bsv2, bstag2 = F.balance_sheet()
    cash, eq, debt = bsv2.get("cash"), bsv2.get("equity"), bsv2.get("debt")
    cash_d = eq_d = debt_d = bs_date
    if bstag2.get("cash"):
        print("  [现金组 tag: %s]" % ", ".join(bstag2["cash"]))
    print("  Cash+短期投资 %s (%s)" % (f(cash), cash_d))
    print("  Equity %s (%s)" % (f(eq), eq_d))
    print("  Debt   %s (%s)" % (f(debt), debt_d))
    net_debt = (debt - cash) if (debt is not None and cash is not None) else None
    ebitda = (ttm_op + ttm_da) if (ttm_op is not None and ttm_da is not None) else None
    print("  Net Debt      %s" % f(net_debt))
    print("  EBITDA (TTM)  %s  [OpInc + D&A]" % f(ebitda))
    print("  NetDebt/EBITDA %s" % f(net_debt / ebitda if (net_debt is not None and ebitda) else None, "x"))

    # ---- ROIC（NOPAT / 投入资本）
    tax = F.ttm(TAX_TAGS)
    pretax = F.ttm(PRETAX_TAGS)
    rate = 0.21
    if tax is not None and pretax:
        rate = max(0.0, min(0.5, tax / pretax))
    nopat = ttm_op * (1 - rate) if ttm_op is not None else None
    ic = (debt + eq - cash) if None not in (debt, eq, cash) else None
    roic = pct(nopat, ic) if (nopat is not None and ic) else None
    print("\n资本回报")
    print("  有效税率     %s  [Tax/税前利润]" % f(rate * 100, "%"))
    print("  NOPAT        %s  [OpInc×(1-税率)]" % f(nopat))
    print("  投入资本     %s  [债+权益-现金]" % f(ic))
    print("  ROIC         %s" % f(roic, "%"))

    # ---- 增长率
    print("\n增长")
    for k in (3, 5):
        if len(rv) > k and rv[-1 - k]:
            cagr = ((rv[-1] / rv[-1 - k]) ** (1.0 / k) - 1) * 100
            print("  Revenue %d年 CAGR  %s" % (k, f(cagr, "%")))
    if len(rv) >= 2 and rv[-2]:
        print("  最近年度 YoY       %s" % f((rv[-1] / rv[-2] - 1) * 100, "%"))

    # ---- TTM 同比（比年度 YoY 更及时）
    prior_q_end = None
    if q_end != "?":
        qd = dt.date.fromisoformat(q_end)
        prior_q_end = qd.replace(year=qd.year - 1).isoformat()
    ttm_rev_prior = F.ttm(REV_TAGS, prior_q_end) if prior_q_end else None
    ttm_fcf_prior = None
    if prior_q_end:
        o = F.ttm(OCF_TAGS, prior_q_end)
        c = F.ttm(CAPEX_TAGS, prior_q_end)
        ttm_fcf_prior = (o - c) if (o is not None and c is not None) else None
    rev_g = (ttm_rev / ttm_rev_prior - 1) * 100 if (ttm_rev and ttm_rev_prior) else None
    fcf_g = (ttm_fcf / ttm_fcf_prior - 1) * 100 if (ttm_fcf and ttm_fcf_prior) else None
    print("  TTM Revenue YoY    %s   [TTM %s vs 去年同期 %s]" %
          (f(rev_g, "%"), f(ttm_rev), f(ttm_rev_prior)))
    print("  TTM FCF YoY        %s   [TTM %s vs 去年同期 %s]" %
          (f(fcf_g, "%"), f(ttm_fcf), f(ttm_fcf_prior)))

    out.update({
        "ttm_period": q_end, "ttm_revenue": ttm_rev, "ttm_gross_profit": ttm_gp,
        "ttm_op_income": ttm_op, "ttm_net_income": ttm_ni, "ttm_ocf": ttm_ocf,
        "ttm_capex": ttm_cx, "ttm_fcf": ttm_fcf,
        "gross_margin_pct": pct(ttm_gp, ttm_rev), "op_margin_pct": pct(ttm_op, ttm_rev),
        "net_margin_pct": pct(ttm_ni, ttm_rev), "fcf_margin_pct": pct(ttm_fcf, ttm_rev),
        "cash_conversion_pct": pct(ttm_fcf, ttm_ni),
        "revenue_growth_ttm_pct": rev_g, "fcf_growth_ttm_pct": fcf_g,
        "cash": cash, "equity": eq, "debt": debt, "net_debt": net_debt,
        "ebitda_ttm": ebitda,
        "net_debt_ebitda": (net_debt / ebitda) if (net_debt is not None and ebitda) else None,
        "tax_rate": rate, "nopat": nopat, "invested_capital": ic, "roic_pct": roic,
        "annual": {"end": rd, "revenue": rv, "gross_profit": gp, "op_income": op,
                   "net_income": ni, "ocf": ocf, "capex": cx},
    })
    if a.json:
        print("\n" + json.dumps(out, ensure_ascii=False, indent=1))

    # ---- [D-10 集成] 直接输出 alpha_score.py 的定量参数，避免手抄
    if a.score_inputs:
        print("\n给 alpha_score.py 的定量参数（可直接复制；moat/management 需人工判断）")
        bits = [
            ("--revenue-growth", rev_g), ("--organic-growth", None),
            ("--gross-margin", pct(ttm_gp, ttm_rev)),
            ("--operating-margin", pct(ttm_op, ttm_rev)),
            ("--fcf-growth", fcf_g), ("--fcf-margin", pct(ttm_fcf, ttm_rev)),
            ("--roic", roic),
            ("--net-debt-ebitda", (net_debt / ebitda) if (net_debt is not None and ebitda) else None),
            ("--moat", None), ("--management", None),
        ]
        parts = []
        for k, v in bits:
            parts.append("%s %s" % (k, ("%.2f" % v) if v is not None else "<人工>"))
        print("py scripts/alpha_score.py score " + " \\\n    ".join(parts))
        print("注: --organic-growth 需从公司披露取（XBRL 无此字段）；moat/management 为定性评分 0-5")
    return 0


if __name__ == "__main__":
    sys.exit(main())