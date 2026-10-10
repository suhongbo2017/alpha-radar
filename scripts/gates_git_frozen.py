#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Gate G6 —— 账本已固化进 git（[D-18] / [A0] / [A1]）

为什么需要这个门禁：
    铁律「旧预测永不覆盖」在 v1.1 之前**没有任何技术保障** ——
    predictions.jsonl 可被任何文本编辑器静默改写。
    现在账本进了 git，但"进了 git"这个事实本身也需要被持续检验，
    否则很容易出现：记了一条预测，却忘了提交；或者改了文件，却以为已固化。

检查：
  1. 当前目录在 git 工作树里
  2. data/*.jsonl 已被跟踪
  3. HEAD 中的 predictions.jsonl 行数 >= 基线（防误删）
  4. 工作区的 data/*.jsonl 与 HEAD 一致（不存在"已记录未固化"）
  5. 有提交历史

退出码：0 = 已固化，1 = 未固化/缺失
"""
import os
import subprocess
import sys

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BASELINE_PRED = 15          # 2026-10-07 首次固化时的条数
LEDGER_FILES = ["data/predictions.jsonl", "data/actuals.jsonl", "data/decisions.jsonl"]

problems = []


def git(*args):
    return subprocess.run(["git"] + list(args), cwd=ROOT, capture_output=True,
                          text=True, encoding="utf-8", errors="replace")


def main():
    r = git("rev-parse", "--is-inside-work-tree")
    if r.returncode != 0:
        print("  ✗ 当前目录不是 git 工作树 —— 账本无任何技术保障（见 DEFECTS.md D-18）")
        print("    修复: git init && git add -A && git commit")
        print("__GATE_FAIL__ G6")
        return 1

    n = git("rev-list", "--count", "HEAD")
    if n.returncode != 0 or not n.stdout.strip().isdigit():
        problems.append("没有任何提交历史")
    else:
        print("  提交数: %s" % n.stdout.strip())

    # 跟踪状态 + 与 HEAD 一致性
    for f in LEDGER_FILES:
        path = os.path.join(ROOT, f)
        if not os.path.exists(path):
            print("  – %s 尚未创建（跳过）" % f)
            continue
        tracked = git("ls-files", "--error-unmatch", f)
        if tracked.returncode != 0:
            problems.append("%s 存在但未被 git 跟踪" % f)
            continue
        diff = git("diff", "--quiet", "HEAD", "--", f)
        if diff.returncode != 0:
            problems.append("%s 有未固化的改动（记了但没提交）" % f)
        else:
            print("  ✓ %s 已固化且与 HEAD 一致" % f)

    # 基线防误删
    head = git("show", "HEAD:data/predictions.jsonl")
    if head.returncode == 0:
        cnt = len([l for l in head.stdout.splitlines() if l.strip()])
        print("  HEAD 中 predictions.jsonl: %d 条" % cnt)
        if cnt < BASELINE_PRED:
            problems.append("HEAD 中预测条数 %d < 基线 %d（可能有记录被删除）"
                            % (cnt, BASELINE_PRED))
    else:
        problems.append("无法从 HEAD 读取 data/predictions.jsonl")

    if problems:
        for p in problems:
            print("  ✗ " + p)
        print("  G6: %d 处问题" % len(problems))
        print("__GATE_FAIL__ G6")
        return 1
    print("  G6: 账本已固化进 git")
    print("__GATE_PASS__ G6")
    return 0


if __name__ == "__main__":
    sys.exit(main())