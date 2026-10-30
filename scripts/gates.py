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
import json
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
    ("G6", "账本已固化进 git"),
    ("G7", "一手数据多层校验"),
    ("G8", "站点安全构建"),
    ("G9", "研究快照一致性"),
    ("G10", "缺陷册自洽"),
]

EXPECTED_FILE = os.path.join(ROOT, "scripts", "expected_fail.json")


def load_expected(gid):
    """读取某道门禁的已知失败豁免。没有文件/没有该门禁 → []"""
    try:
        with open(EXPECTED_FILE, encoding="utf-8") as f:
            data = json.load(f)
    except Exception:
        return []
    return data.get(gid) or []


def defect_open(defect_id):
    """该缺陷是否仍未关闭（决定豁免是否还有效）。读 DEFECTS.md 主表。"""
    try:
        sys.path.insert(0, os.path.join(ROOT, "scripts"))
        from defect_stats import status_of
        st = status_of(defect_id)
        if st is None:
            return None            # 找不到这条缺陷
        return "已修复" not in st
    except Exception:
        return None


def apply_expected(gid, failures):
    """把实际失败与豁免表对齐。

    返回 (unexpected, expected_hit, expired, unknown_defect)
      unexpected    : 失败但不在豁免表 → 必须红
      expected_hit  : 失败且在豁免表，且绑定的缺陷仍未关闭 → 允许
      expired       : 在豁免表里，但本次已不再失败 → 豁免过期，必须红（防腐烂）
      unknown_defect: 在豁免表里，但绑定的缺陷 ID 不存在或已修好 → 必须红
    """
    exp = load_expected(gid)
    by_target = {e["target"].upper(): e for e in exp}
    failures = {f.upper() for f in failures}

    unexpected, expected_hit, expired, unknown = [], [], [], []
    for f in sorted(failures):
        e = by_target.get(f)
        if not e:
            unexpected.append(f)
            continue
        open_ = defect_open(e.get("defect", ""))
        if open_ is True:
            expected_hit.append((f, e.get("defect")))
        elif open_ is None:
            unknown.append((f, e.get("defect")))
        else:
            unknown.append((f, e.get("defect")))    # 缺陷已修好 → 不该再豁免
    for target, e in by_target.items():
        if target not in failures:
            expired.append((target, e.get("defect")))
    return unexpected, expected_hit, expired, unknown


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
    if gid == "G6":
        # 该脚本自己打印哨兵（因为它在 git 不存在时要给出具体修复提示）
        return [sys.executable, "scripts/gates_git_frozen.py", "--emit-sentinel"]
    if gid == "G8":
        # 该脚本自带哨兵
        return [sys.executable, "scripts/gates_site_safety.py"]
    if gid == "G7":
        # 多层数据校验（含外部交叉）。--require-cross：外部源不可用则判失败，
        # 因为只有外部源才能捕获 YTD 选择类错误（内部双路共享原语，不独立）。
        return [sys.executable, "scripts/verify_data.py", "--all", "--require-cross"]
    if gid == "G9":
        return [sys.executable, "scripts/research_snapshot.py", "validate"]
    if gid == "G10":
        # [D-92] 统计数字必须由主表生成。手写的统计行四个月内错了四项，
        # 而它恰好是全册最容易被引用的一句。
        # 该脚本自带哨兵。
        return [sys.executable, "scripts/defect_stats.py", "--check"]
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

    # ── [3B] 已知失败豁免：只豁免【具体 target + 已登记且未关闭的缺陷】
    if load_expected(gid):
        fails = [l.split("__VERIFY_FAIL__", 1)[1].strip()
                 for l in lines if l.startswith("__VERIFY_FAIL__")]
        fails = [f for f in fails if f.upper() != "ALL"]
        unexpected, hit, expired, unknown = apply_expected(gid, fails)
        for l in lines[-6:]:
            print("  " + l)
        ok = True
        if hit:
            print("  ⏭  已登记豁免 %d 项：%s" % (
                len(hit), "、".join("%s(%s)" % x for x in hit)))
        if unexpected:
            ok = False
            print("  ❌ 不在豁免表内的失败 %d 项：%s"
                  % (len(unexpected), "、".join(unexpected)))
            print("     → 这是【新问题】，必须处理；不要往 expected_fail.json 里加")
        if unknown:
            ok = False
            print("  ❌ 豁免无效 %d 项：%s（绑定的缺陷不存在或已修复，请移除该豁免）"
                  % (len(unknown), "、".join("%s→%s" % x for x in unknown)))
        if expired:
            ok = False
            print("  ❌ 豁免已过期 %d 项：%s（本次已不失败，请从 expected_fail.json 删除）"
                  % (len(expired), "、".join("%s→%s" % x for x in expired)))
        print("__GATE_%s__ %s%s" % ("PASS" if ok else "FAIL", gid,
                                    "" if ok else " (unexpected/expired)"))
        return 0 if ok else 1

    # G6 自带哨兵：去掉它，避免重复输出
    own = [l for l in lines if l.startswith("__GATE_")]
    lines = [l for l in lines if not l.startswith("__GATE_")]
    tail = lines[-12:] if r.returncode == 0 else lines[-18:]
    for l in tail:
        print("  " + l)
    if own:
        print(own[-1])
        return 0 if "__GATE_PASS__" in own[-1] else 1
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