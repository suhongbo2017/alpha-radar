#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Alpha Radar 辅助计算器 —— 评分锚 / 仓位 / 快速筛查

解决三个缺陷：
  [D-10] Fundamental Score 不可复现 —— 权重表看着量化，实际是主观打分。
         本文件把每一项写死阈值锚，同一组输入必然得到同一个分数。
  [D-11] 仓位阶梯与赔率脱钩 —— 0.5:1 和 3.9:1 用同一张表。
         本文件让仓位 = f(赔率, 置信度)，并硬性规定 赔率<1:1 不得建仓。
  [D-12] 无快速筛查档 —— 观察名单一多就崩。
         `lite` 只要三项输入，15 分钟筛掉 90%。

用法:
  py scripts/alpha_score.py score --revenue-growth 8 --organic-growth 6 \\
      --gross-margin 39 --operating-margin 28 --fcf-growth 22 --fcf-margin 19 \\
      --roic 20.2 --net-debt-ebitda 2.1 --moat 4.2 --management 4.0
  py scripts/alpha_score.py size --odds 0.5 --confidence Medium
  py scripts/alpha_score.py lite --revenue-growth 8 --moat-trend up --valuation-pct 85
  py scripts/alpha_score.py anchors          # 打印全部评分锚
"""
import argparse
import json
import sys

try:
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
except Exception:
    pass

# ══════════════════════════════════════════════════════════════════
#  [D-10] 评分锚：权重与阈值全部写死，保证可复现
# ══════════════════════════════════════════════════════════════════
# 每项: (权重, 方向, [(阈值, 得分比例), ...])  高者优先匹配
ANCHORS = {
    "revenue_growth":   (10, "high", [(25, 1.0), (15, .8), (8, .6), (3, .4), (0, .2)]),
    "organic_growth":   (10, "high", [(20, 1.0), (12, .8), (6, .6), (2, .4), (0, .2)]),
    "gross_margin":     (8,  "high", [(50, 1.0), (40, .8), (30, .6), (20, .4), (10, .2)]),
    "operating_margin": (10, "high", [(25, 1.0), (18, .8), (12, .6), (7, .4), (3, .2)]),
    "fcf_growth":       (12, "high", [(25, 1.0), (15, .8), (8, .6), (3, .4), (0, .2)]),
    "fcf_margin":       (10, "high", [(25, 1.0), (18, .8), (12, .6), (6, .4), (0, .2)]),
    "roic":             (12, "high", [(20, 1.0), (15, .8), (10, .6), (7, .4), (4, .2)]),
    "net_debt_ebitda":  (8,  "low",  [(1, 1.0), (2, .8), (3, .6), (4, .4), (5, .2)]),
    "moat":             (12, "of5",  [(5, 1.0)]),
    "management":       (8,  "of5",  [(5, 1.0)]),
}
LABEL = {
    "revenue_growth": "Revenue Growth %", "organic_growth": "Organic Growth %",
    "gross_margin": "Gross Margin %", "operating_margin": "Operating Margin %",
    "fcf_growth": "FCF Growth %", "fcf_margin": "FCF Margin %", "roic": "ROIC %",
    "net_debt_ebitda": "Net Debt/EBITDA (x)", "moat": "Moat (0-5)", "management": "Management (0-5)",
}


def frac(key, v):
    if v is None:
        return None
    w, direction, bands = ANCHORS[key]
    if direction == "of5":
        return max(0.0, min(1.0, v / 5.0))
    if direction == "low":                 # 越低越好
        for t, f in bands:                 # bands 升序
            if v <= t:
                return f
        return 0.0
    for t, f in bands:                     # bands 降序
        if v >= t:
            return f
    return 0.0


def grade(total):
    return ("Exceptional" if total >= 90 else "Excellent" if total >= 80 else
            "Good" if total >= 70 else "Average" if total >= 60 else "Weak")


def cmd_anchors(a):
    print("Fundamental Score 评分锚（写死，保证可复现）\n")
    print("%-24s %-5s %s" % ("项目", "权重", "阈值 → 得分比例"))
    print("-" * 88)
    for k, (w, d, bands) in ANCHORS.items():
        if d == "of5":
            desc = "线性: 值/5 → 比例"
        elif d == "low":
            desc = "  ".join("<=%g→%.0f%%" % (t, f * 100) for t, f in bands)
        else:
            desc = "  ".join(">=%g→%.0f%%" % (t, f * 100) for t, f in bands)
        print("%-24s %-5d %s" % (LABEL[k], w, desc))
    print("-" * 88)
    print("总分 = Σ(权重 × 比例)，满分 %d" % sum(w for w, _, _ in ANCHORS.values()))
    return 0


def cmd_score(a):
    vals = {k: getattr(a, k) for k in ANCHORS}
    rows, total, missing = [], 0.0, []
    for k, (w, d, _) in ANCHORS.items():
        f = frac(k, vals[k])
        if f is None:
            missing.append(k)
            rows.append((k, w, None, None))
            continue
        pts = w * f
        total += pts
        rows.append((k, w, vals[k], pts))

    print("Fundamental Score")
    print("-" * 62)
    print("%-24s %-5s %-10s %s" % ("项目", "权重", "输入", "得分"))
    for k, w, v, pts in rows:
        print("%-24s %-5d %-10s %s" % (
            LABEL[k], w, ("%.4g" % v) if v is not None else "（未提供）",
            ("%.1f" % pts) if pts is not None else "—"))
    print("-" * 62)
    got = sum(w for k, w, v, p in rows if p is not None)
    print("合计: %.1f / %d（已提供项满分 %d）→ %.1f%%  %s"
          % (total, sum(w for w, _, _ in ANCHORS.values()), got,
             (100.0 * total / got) if got else 0, grade(100.0 * total / got if got else 0)))
    if missing:
        print("\n⚠ 缺项: %s —— 该分数不可与其他公司直接比较" % ", ".join(LABEL[m] for m in missing))
    print("\n同一组输入必然得到同一分数（这就是可复现的含义）。")
    if a.json:
        print(json.dumps({"total": round(total, 2), "max_provided": got,
                          "pct": round(100.0 * total / got, 1) if got else 0,
                          "items": {k: (v, p) for k, w, v, p in rows}}, ensure_ascii=False, indent=1))
    return 0


# ══════════════════════════════════════════════════════════════════
#  [D-11] 仓位 = f(赔率, 置信度)，赔率 <1:1 一律不建仓
# ══════════════════════════════════════════════════════════════════
ODDS_BANDS = [   # (下限赔率, 建议仓位区间)
    (4.0, (35, 50)),
    (2.5, (20, 35)),
    (1.5, (10, 20)),
    (1.0, (5, 10)),
]
CONF_MULT = {"Low": 0.5, "Medium": 0.8, "High": 1.0}


def cmd_size(a):
    odds, conf = a.odds, a.confidence
    print("仓位建议")
    print("-" * 62)
    print("输入: 赔率 %.2f:1   置信度 %s   单标的上限 %g%%   当前仓位 %s%%"
          % (odds, conf, a.max_weight, a.current_weight if a.current_weight is not None else "—"))

    if odds < 1.0:
        print("\n⛔ 结论: **不建仓（0%）**")
        print("   理由: 赔率 %.2f:1 < 1:1 —— 承担的风险大于潜在回报。" % odds)
        print("   这条是硬规则，不因'公司很优秀'或'基本面很好'而豁免。")
        print("   APH 就是这类样本: 基本面 9/10，但赔率 0.5:1，所以动作是 Watch 而非 Buy。")
        return 0

    lo, hi = next((b for t, b in ODDS_BANDS if odds >= t), (5, 10))
    m = CONF_MULT.get(conf, 0.8)
    lo2, hi2 = lo * m, hi * m
    hi2 = min(hi2, a.max_weight)
    lo2 = min(lo2, hi2)

    print("\n赔率档位: %.0f–%.0f%%  ×  置信度系数 %s(%.1f×)  →  %.0f–%.0f%%"
          % (lo, hi, conf, m, lo2, hi2))
    if a.max_weight < hi * m:
        print("  已被单标的上限 %g%% 截断。" % a.max_weight)

    if a.current_weight is not None:
        d = a.current_weight - hi2
        if a.current_weight < lo2:
            print("\n建议: **加仓** 到 %.0f–%.0f%%（当前 %.g%%，低于区间下沿）" % (lo2, hi2, a.current_weight))
        elif a.current_weight > hi2:
            print("\n建议: **减仓** 到 %.0f–%.0f%%（当前 %.g%%，超出区间上沿 %.1fpp）"
                  % (lo2, hi2, a.current_weight, d))
        else:
            print("\n建议: **持有**（当前 %.g%% 已在 %.0f–%.0f%% 区间内）" % (a.current_weight, lo2, hi2))
    else:
        print("\n建议: 建仓目标 **%.0f–%.0f%%**" % (lo2, hi2))
    print("\n注意: 这是上限约束，不是买入信号。买入还需先满足基本面与价格条件。")
    return 0


# ══════════════════════════════════════════════════════════════════
#  [D-12] 快速筛查档
# ══════════════════════════════════════════════════════════════════
def cmd_lite(a):
    rg, mt, vp = a.revenue_growth, a.moat_trend, a.valuation_pct
    grow = "↑ 加速" if rg >= 15 else "→ 稳定" if rg >= 5 else "↓ 放缓"
    moat = {"up": "↑ 加强", "flat": "→ 稳定", "down": "↓ 削弱"}.get(mt, "?")
    val = ("🟢 低位" if vp <= 40 else "🟡 中位" if vp <= 70 else "🔴 高位")

    print("Alpha Radar Lite —— 15 分钟筛查")
    print("-" * 62)
    print("  Revenue Growth  %.4g%%   →  基本面  %s" % (rg, grow))
    print("  Moat Trend      %-6s  →  护城河  %s" % (mt, moat))
    print("  Valuation       第 %.0f 分位  →  估值  %s" % (vp, val))
    print("-" * 62)

    ok_g, ok_m = grow.startswith("↑"), moat.startswith("↑")
    ok_v = vp <= 70
    if ok_g and ok_m and ok_v:
        print("  结论: ✅ **升级到完整 Alpha Radar**（三项同时满足）")
    elif grow.startswith("↓") and moat.startswith("↓"):
        print("  结论: ❌ **放弃** —— 基本面与护城河同时恶化，跌多少都不买")
    elif not ok_v and ok_g and ok_m:
        print("  结论: 👀 **只进观察名单** —— 公司好但价格太高（典型: APH 型）")
    else:
        print("  结论: ⏸ **不投入深度研究** —— 至少一项不满足，把时间给别人")

    print("\n  三项的规则: 基本面↑ + 护城河↑ + 估值不在高位 → 才值得跑全流程。")
    print("  三项中任何一项为↓都要先解释清楚，否则不进入下一档。")
    return 0


def main():
    p = argparse.ArgumentParser(description="Alpha Radar 辅助计算器")
    sub = p.add_subparsers(dest="cmd", required=True)

    q = sub.add_parser("anchors", help="打印 Fundamental Score 评分锚")
    q.set_defaults(func=cmd_anchors)

    q = sub.add_parser("score", help="[D-10] 按固定阈值锚计算 Fundamental Score（可复现）")
    for k in ANCHORS:
        q.add_argument("--" + k.replace("_", "-"), dest=k, type=float, default=None)
    q.add_argument("--json", action="store_true")
    q.set_defaults(func=cmd_score)

    q = sub.add_parser("size", help="[D-11] 按赔率与置信度给仓位（赔率<1 不建仓）")
    q.add_argument("--odds", type=float, required=True, help="赔率 = 上行空间 / 下行空间")
    q.add_argument("--confidence", default="Medium", choices=["Low", "Medium", "High"])
    q.add_argument("--max-weight", type=float, default=25, help="单标的上限 %%，默认 25")
    q.add_argument("--current-weight", type=float, default=None)
    q.set_defaults(func=cmd_size)

    q = sub.add_parser("lite", help="[D-12] 快速筛查（三项输入）")
    q.add_argument("--revenue-growth", dest="revenue_growth", type=float, required=True)
    q.add_argument("--moat-trend", dest="moat_trend", default="flat",
                   choices=["up", "flat", "down"])
    q.add_argument("--valuation-pct", dest="valuation_pct", type=float, required=True,
                   help="当前估值在自身历史区间的百分位 0-100")
    q.set_defaults(func=cmd_lite)

    a = p.parse_args()
    sys.exit(a.func(a))


if __name__ == "__main__":
    main()