#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Gate G8 —— 站点安全构建

为什么需要：仓库是**公开**的（GitHub）。站点若把持仓数据带进去并部署，等于公开账户明细。
本门禁做两件事：
  1. 用默认参数（不含持仓）重新构建站点
  2. 断言输出中**不含任何持仓字段**

同时也验证站点生成器本身可用（构建失败 = 页面不可用）。

退出码：0 = 安全，1 = 有泄漏或构建失败
"""
import os
import re
import subprocess
import sys

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "site", "index.html")

# 公开站点绝不该出现的字段
FORBIDDEN = ["market_value", "cost_basis", "unrealized_pnl", "realized_pnl",
             "avg_cost", "positions.json", "qty"]


def main():
    r = subprocess.run([sys.executable, "scripts/build_site.py"], cwd=ROOT,
                       capture_output=True, text=True, encoding="utf-8",
                       errors="replace")
    if r.returncode != 0:
        print("  ✗ 站点构建失败")
        for l in (r.stderr or r.stdout or "").splitlines()[-8:]:
            print("    " + l)
        print("__GATE_FAIL__ G8")
        return 1

    if not os.path.exists(OUT):
        print("  ✗ 构建成功但未生成 %s" % OUT)
        print("__GATE_FAIL__ G8")
        return 1

    h = open(OUT, encoding="utf-8").read()
    leaks = [f for f in FORBIDDEN if f in h]
    kb = os.path.getsize(OUT) / 1024
    n_doc = h.count('class="dossier"')

    if leaks:
        print("  ✗ 🔴 站点含持仓/敏感字段: %s" % ", ".join(leaks))
        print("    仓库是公开的 —— 不要部署此产物")
        print("__GATE_FAIL__ G8")
        return 1

    # HTML 标签平衡（粗检）
    unbalanced = []
    for tag in ("table", "pre", "blockquote", "ul", "ol", "div", "section"):
        o = len(re.findall(r"<%s[ >]" % tag, h))
        c = len(re.findall(r"</%s>" % tag, h))
        if o != c:
            unbalanced.append("%s(%d/%d)" % (tag, o, c))

    print("  ✓ 站点已构建 %.0f KB，含 %d 份档案" % (kb, n_doc))
    print("  ✓ 无持仓/敏感字段")
    if unbalanced:
        print("  ⚠️ 标签不平衡: %s" % ", ".join(unbalanced))
    print("__GATE_PASS__ G8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
