#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Alpha Radar 门禁（Gate）运行器 —— 跨 shell 版本

为什么是 Python 而不是 bash：
    Herdr 新建 tab 的根 pane 在这个环境里起的是 PowerShell，`bash` 会解析到
    C:\\Windows\\System32\\bash.exe（WSL 占位符），而不是 git-bash。
    实测报错： "执行 Linux 程序的 Windows 子系统没有已安装的分发版"。
    所以门禁命令不能假设 pane 的 shell 是 bash。
    Python 在 PowerShell / cmd / git-bash 下都能被 `py` 拉起，是唯一共同点。

用法:
    py scripts/gates.py --list
    py scripts/gates.py --all
    py scripts/gates.py --only G4

约定（Herdr 编排依赖此约定）:
    每个门禁结束时输出唯一哨兵:
        __GATE_PASS__ <ID>
        __GATE_FAIL__ <ID>
    编排器用 `herdr pane wait-output --regex "__GATE_(PASS|FAIL)__ <ID>"` 等待。
"""
import os
import shutil
import subprocess
import sys

try:
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
except Exception:
    pass

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

GATES = [
    ("G1", "账本回归测试"),
    ("G2", "skill 副本同步"),
    ("G3", "真实数据完整性"),
    ("G4", "语法 / 导入"),
    ("G5", "文档-CLI 漂移"),
]

BASH_CANDIDATES = [
    r"C:\Program Files\Git\bin\bash.exe",   # 会自行设好 PATH（含 coreutils）
    r"C:\Program Files (x86)\Git\bin\bash.exe",
]


def find_bash():
    """优先用 git-bash 的 launcher（bin/bash.exe），它会设定好 PATH。
    usr\\bin\\bash.exe 直跑会缺 dirname/mktemp/tail/sed。"""
    for p in BASH_CANDIDATES:
        if os.path.exists(p):
            return p
    return shutil.which("bash")


BASH = find_bash()


def gate_cmd(gid):
    s = lambda *a: " ".join(a)
    if gid == "G1":
        return [BASH, "scripts/test_ledger.sh"]
    if gid == "G2":
        return [BASH, "scripts/sync_skills.sh", "--check"]
    if gid == "G3":
        return [sys.executable, "scripts/gates_data_integrity.py"]
    if gid == "G4":
        return [sys.executable, "-m", "py_compile", "scripts/alpha_ledger.py"]
    if gid == "G5":
        return [sys.executable, "scripts/check_doc_cli.py"]
    return None


def gate_name(gid):
    for g, n in GATES:
        if g == gid:
            return n
    return "未知"


def run_one(gid):
    name = gate_name(gid)
    cmd = gate_cmd(gid)
    print("─── %s  %s ───" % (gid, name))
    if not cmd:
        print("__GATE_FAIL__ %s (unknown gate)" % gid)
        return 1
    if cmd[0] is None:
        print("  ✗ 找不到可用于执行 .sh 的 bash（git-bash 未安装？）")
        print("__GATE_FAIL__ %s (no bash)" % gid)
        return 1
    try:
        r = subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True,
                           encoding="utf-8", errors="replace", timeout=600)
    except Exception as e:
        print("  ✗ 执行异常: %s" % e)
        print("__GATE_FAIL__ %s (exception)" % gid)
        return 1

    body = (r.stdout or "") + (r.stderr or "")
    lines = [l for l in body.splitlines() if l.strip()]
    tail = lines[-12:] if r.returncode == 0 else lines[-18:]
    for l in tail:
        print("  " + l)
    if r.returncode == 0:
        print("__GATE_PASS__ %s" % gid)
        return 0
    print("__GATE_FAIL__ %s (rc=%d)" % (gid, r.returncode))
    return 1


def main():
    args = sys.argv[1:] or ["--all"]
    if args[0] == "--list":
        for g, n in GATES:
            print("%s\t%s" % (g, n))
        return 0
    if args[0] == "--only":
        if len(args) < 2:
            print("用法: gates.py --only <ID>")
            return 2
        return run_one(args[1])
    if args[0] == "--all":
        rc = 0
        for g, _ in GATES:
            rc |= run_one(g)
        print("─── 汇总: %s ───" % ("全部通过" if rc == 0 else "存在失败"))
        return rc
    print("用法: gates.py [--all|--only <ID>|--list]")
    return 2


if __name__ == "__main__":
    sys.exit(main())