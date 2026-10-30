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

# [D-58] 同时支持 us-gaap 与 ifrs-full（外国私人发行人：ASX/UMC 等用 IFRS）
TAXONOMIES = ["us-gaap", "ifrs-full", "dei"]   # 前者优先（dei 提供股数）

REV_TAGS = ["RevenueFromContractWithCustomerExcludingAssessedTax", "Revenues",
            "Revenue", "RevenueFromContractsWithCustomers"]
GP_TAGS = ["GrossProfit"]
COGS_TAGS = ["CostOfRevenue", "CostOfGoodsAndServicesSold", "CostOfSales"]
OP_TAGS = ["OperatingIncomeLoss", "ProfitLossFromOperatingActivities"]
NI_TAGS = ["NetIncomeLoss", "ProfitLoss", "ProfitLossAttributableToOwnersOfParent"]
OCF_TAGS = ["NetCashProvidedByUsedInOperatingActivities",
            "CashFlowsFromUsedInOperatingActivities"]
CAPEX_TAGS = ["PaymentsToAcquirePropertyPlantAndEquipment",
              "PurchaseOfPropertyPlantAndEquipmentClassifiedAsInvestingActivities",
              "PaymentsToAcquireProductiveAssets"]      # KTOS 等用这个
# [D-46] 资本化软件也属于 CapEx（对内自建软件的投资），不计入会低估 CapEx / 高估 FCF。
# 实测：INTU PP&E 0.175B + 资本化软件 0.046B = 0.221B = Yahoo 完全一致
CAPEX_ADD_TAGS = ["PaymentsToDevelopSoftware", "PaymentsForSoftware",
                  "PaymentsToAcquireSoftware"]
DA_TAGS = ["DepreciationDepletionAndAmortization", "DepreciationAmortizationAndAccretionNet",
           "DepreciationAndAmortisationExpense",
           # INTU 等用现金流量表里的摊销调整行
           "AdjustmentForAmortization"]
# [D-53] MSFT 等不报汇总 D&A tag，需用组成部分之和
DA_PARTS = ["Depreciation", "AmortizationOfIntangibleAssets",
            "FinanceLeaseRightOfUseAssetAmortization", "AmortizationOfDeferredCharges"]
TAX_TAGS = ["IncomeTaxExpenseBenefit", "IncomeTaxExpenseContinuingOperations"]
PRETAX_TAGS = ["ProfitLossBeforeTax",
               "IncomeLossFromContinuingOperationsBeforeIncomeTaxesExtraordinaryItemsNoncontrollingInterest",
               "IncomeLossFromContinuingOperationsBeforeIncomeTaxesMinorityInterestAndIncomeLossFromEquityMethodInvestments"]
# [D-46] 现金及现金等价物 —— 净债务必须扣除【短期投资】，否则会系统性高估净债务。
# 实测：APH 短期投资 0.6897B → 净债务 14.08B(错) vs 13.39B(对)
#       INTU 短期投资 2.495B → 净债务 2.96B(错) vs 0.47B(对)
CASH_TAGS = ["CashAndCashEquivalentsAtCarryingValue", "CashAndCashEquivalents"]
CASH_LIKE_EXTRA = ["ShortTermInvestments", "MarketableSecuritiesCurrent",
                   "AvailableForSaleSecuritiesDebtSecuritiesCurrent",
                   "OtherShortTermInvestments",
                   # 2026+ 新 XBRL tag（INTU 等使用）
                   "DebtSecuritiesAvailableForSaleExcludingAccruedInterestCurrent",
                   "DebtSecuritiesAvailableForSaleAmortizedCostExcludingAccruedInterestAfterAllowanceForCreditLossCurrent"]
STI_TAGS = CASH_LIKE_EXTRA

EQ_TAGS = ["StockholdersEquity", "Equity"]
# 债务 tag 优先级：同日期时前面的优先；跨日期时由 latest() 取【最大日期】
# 1/2 是显式口径（"含流动部分" / "长短合计"），3/4 是总分口径，5 含义模糊仅供参考
# [D-58] 债务 tag 分两类 —— 口径不同，不能混为一谈：
#   TOTAL：该 tag 本身就是【含流动部分的总债务】（us-gaap 惯例）
#   PART ：该 tag 只是【分项】，必须求和（IFRS 惯例，LongtermBorrowings 不含流动部分）
DEBT_TOTAL_TAGS = ["LongTermDebtAndCapitalLeaseObligationsIncludingCurrentMaturities",
                   "DebtLongtermAndShorttermCombinedAmount",
                   "LongTermDebt",
                   "DebtInstrumentCarryingAmount",
                   "Borrowings"]
DEBT_PART_TAGS = ["ShorttermBorrowings", "CurrentPortionOfLongtermBorrowings",
                  "LongtermBorrowings", "LongTermDebtNoncurrent"]
DEBT_TAGS = DEBT_TOTAL_TAGS + DEBT_PART_TAGS   # 兼容旧引用
# [D-54] **融资租赁负债属于有息债务**，必须计入总债务。
# 实测：MSFT 用融资租赁建数据中心，金额 $66.59B。
# 不计入会把一家净负债公司说成"净现金"（-36.55B → +30.04B）。
# 注意：FinanceLeaseLiability 已含流动+非流动，优先用它，避免重复计。
FINLEASE_COMBINED = ["FinanceLeaseLiability"]
FINLEASE_PARTS = ["FinanceLeaseLiabilityNoncurrent", "FinanceLeaseLiabilityCurrent"]
# 经营租赁单独列示，**不计入净债务**（为了与 EBITDA 口径一致），作为备忘项
# [D-88] 股数必须分两组：
#   流通股（instant）  —— 市值 = 现价 × 流通股数，用这个
#   加权平均（duration）—— 只是 EPS 的分母，是【期间假设值】，绝不能用来算市值
#
# 实测（2026-10-30）：原实现把加权平均排在第一位，21 家公司里 16 家市值偏差 ≥0.5%，
# 最大 NVTS +28.6%、SOFI +5.7%、APH +4.6%、NFLX +2.2%。
# 多类别股本（GOOGL A/B/C、NFLX A/B）在 XBRL 里已合计成一个无维度的合并值，可直接用。
SHARE_TAGS_OUTSTANDING = ["CommonStockSharesOutstanding",           # 期末流通股（首选）
                          "EntityCommonStockSharesOutstanding"]     # 申报封面日流通股
SHARE_TAGS_AVG = ["WeightedAverageNumberOfDilutedSharesOutstanding",  # 仅作兜底
                  "WeightedAverageNumberOfSharesOutstandingBasic"]
SHARE_TAGS = SHARE_TAGS_OUTSTANDING + SHARE_TAGS_AVG                  # 兼容旧引用


def _minus1y(d):
    """上一年同日（2/29 → 2/28）"""
    try:
        return d.replace(year=d.year - 1)
    except ValueError:
        return d.replace(year=d.year - 1, day=28)


def days(a, b):
    return (dt.date.fromisoformat(b) - dt.date.fromisoformat(a)).days


class Facts:
    def __init__(self, path):
        d = json.load(open(path, encoding="utf-8"))
        self.entity = d.get("entityName", "?")
        # [D-58] 合并多分类标准（us-gaap 优先：同名 tag 取 us-gaap）
        facts = d.get("facts", {})
        self.tax = {}
        for tax in reversed(TAXONOMIES):
            self.tax.update(facts.get(tax, {}))
        self.taxonomies = [t for t in TAXONOMIES if facts.get(t)]
        self.currency = d.get("currency")

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
        # [D-63] **跨 tag 合并**，而不是"取第一个有数据的 tag"。
        # 实测：NVTS 中途从 NetIncomeLoss 换到 ProfitLoss，
        # 旧实现取到 NetIncomeLoss 就返回 → 2026 年的季度完全看不见，
        # TTM 静默退回 FY2025。合并后同一日期由【优先级更高】的 tag 占位。
        # [D-64] 陈旧 tag 防护：先把全部 tag 扫一遍，取最新日期；
        # 最新日期落后 3 年以上的 tag **丢弃**。
        # 实测：NFLX 的 GrossProfit 停在 2011 年，合并后把 TTM 毛利算成 1.64B（真值约 48%×48B）
        all_dates = []
        for tag in tags:
            for it in self._items(tag):
                all_dates.append(it["end"])
        newest = max(all_dates) if all_dates else None
        rows, used = {}, []
        for tag in tags:
            _ds = [it["end"] for it in self._items(tag)]
            if newest and _ds:
                _lag = (dt.date.fromisoformat(newest) -
                        dt.date.fromisoformat(max(_ds))).days
                if _lag > 3 * 365:
                    continue          # 陈旧 tag
            got = False
            for it in self._items(tag):
                has_dur = "start" in it
                if kind == "instant":
                    if has_dur:
                        continue
                    if it["end"] not in rows:
                        rows[it["end"]] = it["val"]
                    got = True
                    continue
                if not has_dur:
                    continue
                n = days(it["start"], it["end"])
                if kind == "annual":
                    if not (330 <= n <= 400):
                        continue
                    if it["end"] not in rows:
                        rows[it["end"]] = it["val"]
                    got = True
                elif kind == "ytd":
                    if not (60 <= n <= 400):
                        continue
                    prev = rows.get(it["end"])
                    if prev is None or n > prev[0]:
                        rows[it["end"]] = (n, it["val"])
                    got = True
            if got:
                used.append(tag)
        if rows:
            if kind == "ytd":
                rows = {k: v[1] for k, v in rows.items()}
            return used[0] if used else None, [rows[k] for k in sorted(rows)], sorted(rows)
        return None, [], []

    def _sum_maps(self, tags, add_tags, kind):
        """主 tag 序列 + 附加 tag 序列（求和），按日期对齐"""
        _, bv, bd = self.series(tags, kind)
        m = dict(zip(bd, bv))
        if add_tags:
            _, av, ad = self.series(add_tags, kind)
            for d_, v_ in zip(ad, av):
                if d_ in m:
                    m[d_] += v_
        return m

    def ttm(self, tags, add_tags=None, q_end=None):
        """[D-53] TTM = 基准年度 + 本年迄今 − 去年同期

        关键的边界规则（旧实现错在这里）：
          · 若季末**恰好等于**某财年末 E  →  TTM 就是该财年值，
            此时基准年度必须是 **E 的上一年**，不能是 E 本身。
          · 否则基准年度 = E 之前最近的已结束财年。

        实测教训：MSFT 季末 = 财年末 2026-06-30，
        旧逻辑算成 115.95 + 115.95 − 64.55 = 167.35B（CapEx）—— 当年被重复计一次。
        """
        am_ = self._sum_maps(tags, add_tags, "annual")
        ym_ = self._sum_maps(tags, add_tags, "ytd")
        if not am_ or not ym_:
            return None
        if q_end is None:
            q_end = max(ym_)
        # [D-65] q_end 也需"最近日期"回退：52/53 周财年的季末逐年漂移
        # （NVDA: 2026-07-26 vs 2025-07-27），精确匹配会落空 → 去年同期返回 None
        if q_end not in ym_:
            _qd = dt.date.fromisoformat(q_end)
            _near = [(abs((dt.date.fromisoformat(d_) - _qd).days), d_)
                     for d_ in ym_ if abs((dt.date.fromisoformat(d_) - _qd).days) <= 14]
            if _near:
                q_end = min(_near)[1]
            else:
                return None
        if q_end in am_:
            return am_[q_end]            # 季末正好是财年末
        prior_fy = [(d_, v_) for d_, v_ in am_.items() if d_ < q_end]
        if not prior_fy:
            return None
        fy_end, fy = max(prior_fy)
        cur = ym_.get(q_end)
        if cur is None:
            return None
        qd = dt.date.fromisoformat(q_end)
        tgt = _minus1y(qd)
        prior = ym_.get(tgt.isoformat())
        if prior is None:
            # [D-60] 52/53 周财年（NVDA 1月、QCOM 9月、KTOS 12月底）的同期日期
            # 不落在同一月日（如 2026-06-28 vs 2025-06-29），必须按【最接近日期】找
            near = [(abs((dt.date.fromisoformat(d_) - tgt).days), d_, v_)
                    for d_, v_ in ym_.items()
                    if d_ < q_end and abs((dt.date.fromisoformat(d_) - tgt).days) <= 14]
            prior = min(near)[2] if near else None
        if prior is None:
            return None
        return fy + cur - prior

    def ttm_or_parts(self, primary, parts):
        """先用汇总 tag；无数据则用组成部分之和（如 MSFT 的 D&A）"""
        v = self.ttm(primary)
        if v is not None:
            return v
        return self.ttm(parts[:1], add_tags=parts[1:]) if parts else None

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

    def debt_at(self, asof):
        """[D-58] 某日的有息债务：优先「合计 tag」，否则「分项求和」
        返回 (value, 说明)
        """
        for t in DEBT_TOTAL_TAGS:
            rows = self.instant_rows(t)
            if asof in rows:
                return rows[asof], t
        tot, used = 0.0, []
        for t in DEBT_PART_TAGS:
            rows = self.instant_rows(t)
            if asof in rows:
                tot += rows[asof]
                used.append(t)
        return (tot if used else 0.0), ("+".join(used) if used else None)

    def finlease_at(self, asof):
        """[D-54] 某日的融资租赁负债：优先合计 tag，否则流动+非流动求和"""
        for t in FINLEASE_COMBINED:
            rows = self.instant_rows(t)
            if asof in rows:
                return rows[asof], t
        tot, used = 0.0, []
        for t in FINLEASE_PARTS:
            rows = self.instant_rows(t)
            if asof in rows:
                tot += rows[asof]
                used.append(t)
        return (tot if used else 0.0), (",".join(used) if used else None)

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
        # [D-62] 三项可用性统一定义：现金组有值 + 权益有值 + 债务（含融资租赁）> 0
        # 不再"debt_at 失败就回退到另一条路径" —— 那会产生第二条解析路径（D-50 的教训）
        cd, ed, dd = set(), set(), set()
        for t_ in cash_group:
            cd |= set(self.instant_rows(t_))
        for t_ in EQ_TAGS:
            ed |= set(self.instant_rows(t_))
        for t_ in DEBT_TOTAL_TAGS + DEBT_PART_TAGS:
            for d_ in self.instant_rows(t_):
                if self.debt_at(d_)[0]:
                    dd.add(d_)
        common = cd & ed & dd
        if not common:
            return None, {}, {}
        asof = max(common)
        _, bsv, bstag = self.latest_common({"cash": cash_group,
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
        dval, dtags_used = self.debt_at(asof)
        vals = {"cash": tot if used else bsv.get("cash"),
                "equity": bsv.get("equity"),
                "debt": dval}
        # [D-54] 总债务 = 有息债务 + 融资租赁负债
        fl, fl_tag = self.finlease_at(asof)
        if fl:
            vals["debt_bearing"] = vals["debt"]
            vals["debt"] = (vals["debt"] or 0) + fl
        vals["finance_lease"] = fl
        ol_rows = self.instant_rows("OperatingLeaseLiability")
        vals["operating_lease"] = ol_rows.get(asof, 0.0)
        tags = {"cash": used, "equity": [bstag.get("equity")],
                "debt": [dtags_used, fl_tag]}
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
    print("实体: %s　｜　分类标准: %s" % (F.entity, ", ".join(F.taxonomies)))

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
    if ttm_gp is None or (ttm_rev and ttm_gp / ttm_rev < 0.05):
        # [D-64] 毛利缺失或明显失真 → 用 Revenue − COGS 派生
        _cogs = F.ttm(COGS_TAGS)
        if _cogs and ttm_rev:
            ttm_gp = ttm_rev - _cogs
    ttm_op = F.ttm(OP_TAGS)
    ttm_ni = F.ttm(NI_TAGS)
    ttm_ocf = F.ttm(OCF_TAGS)
    ttm_cx = F.ttm(CAPEX_TAGS, add_tags=CAPEX_ADD_TAGS)
    ttm_da = F.ttm_or_parts(DA_TAGS, DA_PARTS)
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
    print("  营业收入 Revenue          %s" % f(ttm_rev))
    print("  Gross Margin     %s" % f(pct(ttm_gp, ttm_rev), "%"))
    print("  Operating Margin %s" % f(pct(ttm_op, ttm_rev), "%"))
    print("  Net Margin       %s" % f(pct(ttm_ni, ttm_rev), "%"))
    print("  经营现金流 OCF              %s" % f(ttm_ocf))
    print("  资本开支 CapEx            %s" % f(ttm_cx))
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
    if bsv2.get("finance_lease"):
        print("    └ 其中债务 = 有息 %s + **融资租赁 %s**（[D-54]）"
              % (f(bsv2.get("debt_bearing")), f(bsv2.get("finance_lease"))))
    if bsv2.get("operating_lease"):
        print("    └ 备忘：经营租赁 %s（**未计入净债务**，为与 EBITDA 口径一致）"
              % f(bsv2.get("operating_lease")))
    print("  Equity %s (%s)" % (f(eq), eq_d))
    _dt = (bstag2 or {}).get("debt")
    print("  Debt   %s (%s)%s" % (f(debt), debt_d,
                                 ("  [%s]" % _dt[0]) if isinstance(_dt, (list, tuple)) and _dt and _dt[0] else ""))
    net_debt = (debt - cash) if (debt is not None and cash is not None) else None
    ebitda = (ttm_op + ttm_da) if (ttm_op is not None and ttm_da is not None) else None
    print("  Net Debt      %s" % f(net_debt))
    print("  EBITDA（TTM）  %s  [营业利润 OpInc + 折旧摊销 D&A]" % f(ebitda))
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
    # ---- 股数与市值（估值倍数要用）
    sh, sh_d, sh_src, sh_basis = None, None, None, None

    # ① 优先：期末流通股（instant fact）
    #
    # 两条护栏，都是实测踩出来的：
    #   a) 按 tag 优先级逐组取，组内取最新 —— 不能跨 tag 取 max(end)，
    #      否则申报封面日（2026-10-23）会压过期末日（2026-09-30）。
    #   b) 新鲜度：股数日期必须距离 TTM 期末 ≤120 天。
    #      NVTS 曾在 companyfacts 里只剩 2024-08-02 的封面股数，
    #      不设护栏就会把两年前的股数当成现值（市值少算 24%）。
    best = None
    for _t in SHARE_TAGS_OUTSTANDING:
        cand = None
        for _u, _items in (F.tax.get(_t, {}).get("units", {}) or {}).items():
            for it in _items:
                if "start" in it:
                    continue
                if cand is None or it["end"] > cand[1]:
                    cand = (it["val"], it["end"], _t)
        if cand:
            if q_end and q_end != "?":
                try:
                    # 只拒「比期末旧」的股数；比期末新是正常的（封面日/后续申报）
                    if days(cand[1], q_end) > 120:
                        continue        # 太旧，换下一个 tag / 走兜底
                except Exception:
                    pass
            best = cand
            break
    if best:
        sh, sh_d, sh_src = best
        sh_basis = "outstanding"

    # ② 兜底：季度加权平均（严格 85-95 天，排除 YTD）
    if not sh:
        for _t in SHARE_TAGS_AVG:
            for _u, _items in (F.tax.get(_t, {}).get("units", {}) or {}).items():
                rows = {it["end"]: it["val"] for it in _items
                        if "start" in it and 85 <= days(it["start"], it["end"]) <= 95}
                if rows:
                    k = max(rows)
                    sh, sh_d, sh_src = rows[k], k, _t
                    sh_basis = "diluted-avg-quarter"
            if sh:
                break
    px = None
    try:
        _qp = os.path.join(ROOT, "data", "quotes", "%s.json" % a.ticker.upper())
        if os.path.exists(_qp):
            px = json.load(open(_qp, encoding="utf-8")).get("price")
    except Exception:
        pass
    mc = (px * sh) if (px and sh) else None
    print("\n股数与市值")
    print("  股数        %s (%s)" % (("%.3fM" % (sh / 1e6)) if sh else "—", sh_d))
    print("  现价        %s" % (("%.2f" % px) if px else "—（先跑 alpha_quote.py）"))
    print("  市值        %s" % f(mc))
    if mc and ttm_fcf:
        print("  P/FCF       %.1fx   (FCF yield %.1f%%)" % (mc / ttm_fcf, ttm_fcf / mc * 100))
    if mc and ttm_ni:
        print("  P/E (TTM)   %.1fx" % (mc / ttm_ni))

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
    ttm_rev_prior = F.ttm(REV_TAGS, q_end=prior_q_end) if prior_q_end else None
    ttm_fcf_prior = None
    if prior_q_end:
        o = F.ttm(OCF_TAGS, q_end=prior_q_end)
        c = F.ttm(CAPEX_TAGS, add_tags=CAPEX_ADD_TAGS, q_end=prior_q_end)
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
        "shares": sh, "shares_date": sh_d, "shares_src": sh_src,
        "shares_basis": sh_basis, "price": px, "market_cap": mc,
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