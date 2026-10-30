#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""[D-75] 站点构建的【唯一入口】—— 本地与 CI 共用同一条路径

为什么要单独抽一个脚本（而不是让 workflow 直接调 build_site.py）：

    用户明确指出："如果以后修改代码，本地预览还是要到 ACTIONS 上去检查"。
    这是对的 —— 如果 CI 和本地跑的是**不同的命令序列**，那"本地通过"就
    不能推出"CI 通过"，验证被迫依赖 Actions，反馈回路变长。

    本脚本把 CI 要做的每一步都收敛到这里。于是：
        **本地跑通 ⟺ CI 跑通**（CI 只多一步"上传产物"）
    我不需要 push 后去 Actions 看结果。

CI 里的调用（.github/workflows/pages.yml）:
    python3 scripts/pages_build.py --strict

本地等价命令:
    py scripts/pages_build.py --strict

用法:
    py scripts/pages_build.py                 # 构建 + 安全断言
    py scripts/pages_build.py --with-gates    # 再跑全部门禁（CI 用这个）
    py scripts/pages_build.py --strict        # 任一失败即以非零退出（CI 用）
    py scripts/pages_build.py --refresh       # 先重生研究快照，再构建（本地发布用）

注意：**CI 不使用 --refresh**。让 CI 重生快照会让 G9 永远变绿，
门禁就失去意义。快照只在本地「确认数据已更新」时重生，并与代码一起提交。
"""
import argparse
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
OUT = os.path.join(ROOT, "site", "index.html")
sys.path.insert(0, os.path.join(ROOT, "scripts"))

# 复用 build_site.py 的禁用字段表，避免两处维护
from build_site import FORBIDDEN, FORBIDDEN_RE  # noqa: E402


def step(n, title):
    print("\n[%d] %s" % (n, title))


def run(cmd):
    r = subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True,
                       encoding="utf-8", errors="replace")
    return r


def main():
    ap = argparse.ArgumentParser(description="站点构建唯一入口（本地与 CI 共用）")
    ap.add_argument("--with-gates", action="store_true",
                    help="同时跑全部 10 道门禁（CI 用）")
    ap.add_argument("--strict", action="store_true",
                    help="任一失败即以非零退出")
    ap.add_argument("--refresh", action="store_true",
                    help="先重生研究快照再构建（本地发布用；CI 不要用，否则 G9 永远绿）")
    a = ap.parse_args()
    ok = True

    # ── 0. 可选：重生研究快照
    if a.refresh:
        step(0, "重生研究快照 → data/research_snapshots/")
        r = run([sys.executable, "scripts/research_snapshot.py", "generate"])
        changed = [l for l in (r.stdout or "").splitlines() if "跳过" not in l]
        print("   " + "\n   ".join(changed[-6:] or ["（无）"]))
        if r.returncode != 0:
            print("   ✗ 快照生成失败")
            print((r.stderr or "")[-800:])
            return 1 if a.strict else 0

    # ── 1. 构建站点
    step(1, "构建站点 → site/index.html")
    r = run([sys.executable, "scripts/build_site.py"])
    print("   " + "\n   ".join((r.stdout or "").strip().splitlines()[-3:]))
    if r.returncode != 0:
        print("   ✗ 构建失败")
        print((r.stderr or "")[-800:])
        return 1 if a.strict else 0

    # ── 2. 安全断言（核心：公开站点不得含持仓数量）
    step(2, "安全断言：公开产物不得含数量类字段")
    if not os.path.exists(OUT):
        print("   ✗ 未生成 %s" % OUT)
        ok = False
    else:
        h = open(OUT, encoding="utf-8").read()
        leaks = [f for f in FORBIDDEN if f in h]
        leaks += [p for p in FORBIDDEN_RE if re.search(p, h)]
        kb = os.path.getsize(OUT) / 1024
        n_doc = h.count('class="dossier"')
        n_hold = h.count('pill">持有<')
        n_conf = h.count("🔴 冲突")
        print("   ✓ %.0f KB　档案 %d 份　持有标记 %d　冲突标记 %d" % (kb, n_doc, n_hold, n_conf))
        if leaks:
            print("   ✗ 🔴 含禁用字段: %s" % ", ".join(leaks))
            print("     仓库是公开的 —— 不要部署此产物")
            ok = False
        else:
            print("   ✓ 无数量类字段")

    # ── 3. 可选：全部门禁
    n_skip = 0
    if a.with_gates:
        step(3, "全部 10 道门禁")
        r = run([sys.executable, "scripts/gates.py", "--all"])
        lines = [l for l in (r.stdout or "").splitlines() if l.startswith("__GATE_")]
        for l in lines:
            print("   " + l)
        n_pass = sum(1 for l in lines if "__GATE_PASS__" in l)
        n_skip = sum(1 for l in lines if "__GATE_SKIP__" in l)
        n_total = len(lines)
        print("   通过 %d / 跳过 %d / 共 %d" % (n_pass, n_skip, n_total))
        if n_skip:
            # [D-97] SKIP 不是通过：必须在汇总里单独列出来，否则它就变成了隐藏的绿灯
            print("   ⏭  跳过 %d 道（本环境缺少外部输入，非断言失败；本地需补上后重跑）" % n_skip)
        if n_pass + n_skip != n_total:
            print("   ✗ 有门禁未通过")
            for l in (r.stdout or "").splitlines()[-25:]:
                if "✗" in l:
                    print("     " + l.strip())
            ok = False

    print("\n" + "=" * 58)
    if not ok:
        print("  ❌ 存在失败项 —— 不要部署")
    elif n_skip:
        print("  ⚠️ 可构建，但 %d 道门禁在本环境【跳过】而非通过" % n_skip)
        print("     若这是 CI：属预期（runner 没有 SEC facts / 未安装 skill 副本）")
        print("     若这是本地：先补上输入再重跑 —— 不要拿跳过当绿灯")
    else:
        print("  ✅ 可以部署（10 道门禁全过，CI 只会多一步上传）")
    print("=" * 58)
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())