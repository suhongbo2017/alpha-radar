#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Alpha Radar —— 规则化情景生成（[D-66]）

为什么需要：对一个没有现成行业研究的标的，手拍 Bull/Base/Bear 会引入主观性。
本工具用**写死的规则**从已验证的一手指标推出三情景，保证：
  · 可复现（同输入同输出）
  · 可审计（规则可见，见下）
  · 承认不确定（输出标注"规则生成，非研究结论"）

规则
────
  g_base = clamp(TTM Revenue YoY × 0.5, 0%, 12%)      # 一半的增速可持续
  g_bull = clamp(TTM Revenue YoY × 0.9, 0%, 25%)      # 接近当前增速
  g_bear = min(TTM Revenue YoY × 0.1, 0%)             # 增速归零或按比例转负

  利润率系数：Bull ×1.10 / Base ×1.00 / Bear ×0.90
  倍数系数  ：Bull ×1.20 / Base ×1.00 / Bear × f(风险)
      f(风险) = 0.70 − min(0.30, max(0, NetDebt/EBITDA) × 0.05)
                       − (0.10 if FCF < 0 else 0)     # 加杠杆/烧钱 → 更狠的 Bear

  规模上限（[D-67]）：增速必须随体量衰减 —— 一家 $5T 公司不可能连续 5 年 25%。
      MC < $10B  → 上限 25%      MC < $100B → 18%
      MC < $1T   → 12%          MC ≥ $1T   → 8%
      g_bull = min(g_bull, 上限)      g_base = min(g_base, 上限 × 0.6)

  价值 = 当前市值 × (1+g)^5 × 利润率系数 × 倍数系数
  概率 = 25% / 50% / 25%

使用:
  py scripts/alpha_scenario.py NVDA
  py scripts/alpha_scenario.py NVDA --json
"""
import argparse
import json
import subprocess
import sys

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass


def clamp(x, lo, hi):
    return max(lo, min(hi, x))


def main():
    ap = argparse.ArgumentParser(description="规则化情景生成")
    ap.add_argument("ticker")
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args()
    o = subprocess.run(["py", "scripts/alpha_metrics.py", a.ticker, "--json"],
                       capture_output=True, text=True, encoding="utf-8", errors="replace").stdout
    if "{" not in o:
        print("✗ 无法取得 %s 的指标" % a.ticker)
        return 1
    j = json.loads(o[o.index("{"):])
    mc, yoy = j.get("market_cap"), j.get("revenue_growth_ttm_pct")
    if not mc or yoy is None:
        print("✗ %s 数据不足（缺市值或增速）" % a.ticker)
        return 1
    nde = j.get("net_debt_ebitda") or 0
    fcf = j.get("ttm_fcf") or 0
    # [D-67] 规模上限：体量越大，可持续增速越低
    cap = 25.0 if mc < 1e10 else 18.0 if mc < 1e11 else 12.0 if mc < 1e12 else 8.0
    gb = clamp(yoy * 0.5, 0, min(12.0, cap * 0.6))
    gu = clamp(yoy * 0.9, 0, cap)
    gd = min(yoy * 0.1, 0)
    bear_m = 0.70 - min(0.30, max(0.0, nde) * 0.05) - (0.10 if fcf < 0 else 0.0)
    bear_m = max(0.30, bear_m)
    B = mc * (1 + gu / 100) ** 5 * 1.10 * 1.20
    Ba = mc * (1 + gb / 100) ** 5
    Be = mc * (1 + gd / 100) ** 5 * 0.90 * bear_m
    W = 0.25 * B + 0.50 * Ba + 0.25 * Be
    up = (W / mc - 1) * 100
    dn = (1 - Be / mc) * 100
    od = up / dn if dn > 0 else None
    out = {"ticker": a.ticker.upper(), "market_cap": mc, "revenue_yoy": yoy,
           "g_base": gb, "g_bull": gu, "g_bear": gd, "bear_multiple": bear_m,
           "growth_cap": cap,
           "bull": B, "base": Ba, "bear": Be, "weighted": W,
           "upside_pct": up, "downside_pct": dn, "odds": od,
           "cagr5_pct": ((W / mc) ** 0.2 - 1) * 100,
           "note": "规则生成，非研究结论（见 alpha_scenario.py 头部规则）"}
    if a.json:
        print(json.dumps(out, ensure_ascii=False, indent=1))
        return 0
    print("%s（规则化情景　市值 %s）" % (out["ticker"], "%.1fB" % (mc / 1e9)))
    print("  增速假设    Bull %.2f%% / Base %.2f%% / Bear %.2f%%（TTM YoY %.1f%%，规模上限 %.0f%%）"
          % (gu, gb, gd, yoy, cap))
    print("  Bear 倍数系数 %.2f（净杠杆 %.2fx，FCF %s）"
          % (bear_m, nde, "正" if fcf > 0 else "负"))
    print("  Bull %8.1fB　Base %8.1fB　Bear %8.1fB　加权 %8.1fB"
          % (B / 1e9, Ba / 1e9, Be / 1e9, W / 1e9))
    print("  上行 %+.0f%%　下行 %.0f%%　赔率 %s　5年CAGR %.1f%%"
          % (up, dn, ("%.2f:1" % od) if od else "n/a", out["cagr5_pct"]))
    print("  ⚠ 规则生成，非研究结论")
    return 0


if __name__ == "__main__":
    sys.exit(main())
