#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Gate G5 —— 文档 / CLI 漂移自检（多工具版）

起因：v1.0 时 SKILL.md 写着"估值类不计分"，而 report 实际给 FairValue 打了 B 级。
文档和代码各说各话，没有任何机制能发现。这个门禁就是那个机制。

检查：
  1. 每个工具的每个子命令，都必须在 SKILL.md 里出现
  2. 各子命令的关键选项，必须在 SKILL.md 里出现
  3. SKILL.md 里提到的 <工具> <子命令>，必须是真实存在的子命令（反向检查）
  4. report 的 9 个章节名，都必须在 SKILL.md 里有说明

退出码：0 = 一致，1 = 漂移
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
SKILL = os.path.join(ROOT, "Alpha_Radar_SKILL.md")

TOOLS = [
    ("scripts/alpha_ledger.py", "alpha_ledger.py"),
    ("scripts/alpha_score.py", "alpha_score.py"),
    ("scripts/alpha_fetch.py", "alpha_fetch.py"),
    ("scripts/alpha_metrics.py", "alpha_metrics.py"),
    ("scripts/alpha_quote.py", "alpha_quote.py"),
]

# 内部/次要选项，不强制出现在文档里
IGNORE_OPTS = {"-h", "--help", "--allow-duplicate", "--allow-custom", "--force", "--json"}

REPORT_SECTIONS = ["主评分", "概率加权预测", "情景区间命中", "历史版本对照",
                   "估值输出对照", "预测能力", "误差归因分布", "决策 vs 结果"]

problems = []


def fail(msg):
    problems.append(msg)
    print("  ✗ " + msg)


def run(script, args):
    p = subprocess.run([sys.executable, os.path.join(ROOT, script)] + args,
                       capture_output=True, text=True, encoding="utf-8", errors="replace")
    return (p.stdout or "") + (p.stderr or "")


def main():
    if not os.path.exists(SKILL):
        print("  ✗ 找不到 %s" % SKILL)
        return 1
    skill = open(SKILL, encoding="utf-8").read()

    for script, label in TOOLS:
        top = run(script, ["--help"])
        m = re.search(r"\{([a-z][a-z0-9_,]*)\}", top)
        subs = m.group(1).split(",") if m else []

        if subs:
            print("  %s 子命令 %d 个: %s" % (label, len(subs), ", ".join(subs)))
            for s in subs:
                if ("%s %s" % (label, s)) not in skill:
                    fail("%s 子命令 '%s' 在 SKILL.md 中没有出现（文档漂移）" % (label, s))
        else:
            print("  %s（无子命令）" % label)
            if label not in skill:
                fail("%s 在 SKILL.md 中没有出现" % label)

        # 选项：顶层 + 每个子命令
        helps = [top] + [run(script, [s, "--help"]) for s in subs]
        opts = set()
        for h in helps:
            opts |= set(re.findall(r"--[a-z][a-z0-9-]+", h))
        for opt in sorted(opts - IGNORE_OPTS):
            if opt not in skill:
                fail("%s 选项 '%s' 在 SKILL.md 中没有出现（文档漂移）" % (label, opt))

        # 反向：文档提到的子命令必须真实存在
        for s in sorted(set(re.findall(re.escape(label) + r" ([a-z][a-z0-9]+)", skill))):
            if subs and s not in subs:
                fail("SKILL.md 提到 '%s %s'，但 CLI 里并不存在（文档漂移）" % (label, s))

    # report 章节
    probed = run("scripts/alpha_ledger.py", ["report"])
    for sec in REPORT_SECTIONS:
        if sec in probed and sec not in skill:
            fail("报告章节 '%s' 未在 SKILL.md 中说明" % sec)

    if problems:
        print("  G5: %d 处漂移" % len(problems))
        return 1
    print("  G5: 文档与 CLI 一致")
    return 0


if __name__ == "__main__":
    sys.exit(main())