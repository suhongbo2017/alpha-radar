#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Gate G8 —— 站点安全与可读性

为什么需要：仓库是**公开**的（GitHub）。站点若把持仓数据带进去并部署，等于公开账户明细。
本门禁做三件事：
  1. 用默认参数（不含持仓）重新构建站点
  2. 断言输出中**不含任何持仓数量字段**
  3. [D-76] 断言**可读性下限**未被改回去（面向视力不佳者）

第 3 条的理由：用户明确要求 UI 要方便视力不好的人观看。
原设计有 11 个文字元素里 10 个 <=13px、浅色次要文字对比度仅 4.33:1（低于 WCAG AA）。
修复后必须防止被无意改回去 —— 否则这类回归没有任何信号。

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

# 禁用词表**从 build_site 导入**，保证单一来源（避免两处维护 + 口径漂移）
sys.path.insert(0, os.path.join(ROOT, "scripts"))
from build_site import FORBIDDEN  # noqa: E402


def main():
    # [D-72] 构建到**临时文件**，不要覆盖已提交的 site/index.html。
    # 旧实现就地重建 → 每次跑门禁都把工作区弄脏 → **会挡住 git pull**（实测发生过）。
    # 门禁要能随时跑而不产生副作用。
    import tempfile
    tmp = os.path.join(tempfile.gettempdir(), "ar_site_gate_%d.html" % os.getpid())
    r = subprocess.run([sys.executable, "scripts/build_site.py", "--out", tmp],
                       cwd=ROOT, capture_output=True, text=True, encoding="utf-8",
                       errors="replace")
    if r.returncode != 0:
        print("  ✗ 站点构建失败")
        for l in (r.stderr or r.stdout or "").splitlines()[-8:]:
            print("    " + l)
        print("__GATE_FAIL__ G8")
        return 1

    if not os.path.exists(tmp):
        print("  ✗ 构建成功但未生成产物")
        print("__GATE_FAIL__ G8")
        return 1

    h = open(tmp, encoding="utf-8").read()
    leaks = [f for f in FORBIDDEN if f in h]
    kb = os.path.getsize(tmp) / 1024
    try:
        os.remove(tmp)
    except Exception:
        pass
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

    print("  ✓ 站点已构建 %.0f KB，含 %d 份档案（构建到临时文件，不污染工作区）" % (kb, n_doc))
    print("  ✓ 无持仓数量字段")

    # [D-76] 可读性下限断言
    a11y = [
        ("字号变量 --fs", "var(--fs)" in h),
        ("最小字号兜底 font-size:max", "font-size:max(" in h),
        ("字号调节控件", 'onclick="fs(' in h),
        ("高对比度开关", 'onclick="hc()"' in h),
        ("设置持久化 localStorage", "localStorage" in h),
        ("浅色次要文字对比度修正", "--mut:#4a5a55" in h),
        ("正文行宽限制 52ch", "max-width:52ch" in h),
        ("尊重 reduced-motion", "prefers-reduced-motion" in h),
        ("无障碍标注 aria-label", "aria-label" in h),
    ]
    miss = [n for n, ok_ in a11y if not ok_]
    if miss:
        print("  ✗ 可读性项缺失: %s" % ", ".join(miss))
        print("     （用户要求 UI 方便视力不好的人观看 —— 不要降低字号/对比度）")
        print("__GATE_FAIL__ G8")
        return 1
    print("  ✓ 可读性下限完整（字号/对比度/行宽/控件，共 %d 项）" % len(a11y))
    if unbalanced:
        print("  ⚠️ 标签不平衡: %s" % ", ".join(unbalanced))
    print("__GATE_PASS__ G8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
