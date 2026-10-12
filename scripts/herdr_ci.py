#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""[D-28] Alpha Radar × Herdr 门禁编排器（跨 shell 版本）

原 herdr_ci.sh 的入口是 bash，如果从 PowerShell pane 启动就会挂。
本文件用 Python，PowerShell / cmd / git-bash 下都能用 `py` 拉起。

设计原则
─────────
1. 并行只用于【只读门禁】。G1–G5 都不写盘（G1 用临时库）。
2. 构建任务（改 scripts/alpha_ledger.py）必须串行 —— 同一文件并发写会互相覆盖。
3. 拓扑：专用 workspace + 每门禁一个 tab（整幅 pane）。不用 pane split（会得到窄列）。
4. pane 侧命令跨 shell 安全：一律 `py scripts/gates.py --only <ID>`，不用 bash。
5. 条件用哨兵 `__GATE_PASS__/__GATE_FAIL__ <ID>` + `herdr pane wait-output --regex`，不 sleep 轮询。
6. 先跑 canary（最快门禁）验证链路，失败即中止并给出诊断。
7. 需人工批准的任务（git init）永不自动执行。

用法:
    py scripts/herdr_ci.py                 # 门禁扇出 1 遍，结束关闭 workspace
    py scripts/herdr_ci.py --repeat 3      # 跑 3 遍
    py scripts/herdr_ci.py --keep          # 保留 workspace 供人工查看
    py scripts/herdr_ci.py --build A2,A3   # 串行构建队列（人工批准项会拒绝）
"""
import argparse
import json
import os
import subprocess
import sys
import time

try:
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
except Exception:
    pass

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
GATES = ["G1", "G2", "G3", "G4", "G5", "G6", "G7", "G8"]
GATE_NAMES = {"G1": "账本回归测试", "G2": "skill 副本同步", "G3": "真实数据完整性",
              "G4": "语法 / 导入", "G5": "文档-CLI 漂移", "G6": "账本已固化进 git", "G7": "一手数据多层校验", "G8": "站点安全构建"}
CANARY = "G4"
WS_LABEL = "alpha-radar-ci"

TASKS = {
    "A0": ("git init + 首次提交（固化 15 条预测）", True),
    "A1": ("预测写入后自动 commit 钩子", False),
    "A2": ("Decision Database", False),
    "A3": ("due 复盘提醒", False),
    "A4": ("probability 参与概率加权预测", False),
    "A5": ("误差归因入库 + 归因分布", False),
    "A6": ("SEC 自动取数 alpha_fetch.py", False),
    "A7": ("文档-CLI 漂移自检", False),
    "A8": ("Fundamental Score 评分锚", False),
    "A9": ("仓位 = f(赔率,置信度)", False),
    "A10": ("Alpha Radar Lite", False),
}


def die(msg, code=1):
    print("✗ " + msg)
    sys.exit(code)


def herdr(*args, check=True):
    """调用 herdr，返回解析后的 JSON result；失败返回 None"""
    cmd = ["herdr"] + list(args)
    p = subprocess.run(cmd, capture_output=True, text=True,
                       encoding="utf-8", errors="replace")
    if p.returncode != 0:
        if check:
            print("  ✗ herdr %s 失败: %s" % (" ".join(args), (p.stderr or "").strip()[:300]))
        return None
    try:
        return json.loads(p.stdout).get("result", {})
    except Exception:
        return None


def herdr_rc(*args, timeout=None):
    """只关心退出码（用于 wait-output）"""
    try:
        p = subprocess.run(["herdr"] + list(args), capture_output=True, text=True,
                           encoding="utf-8", errors="replace", timeout=timeout)
        return p.returncode
    except subprocess.TimeoutExpired:
        return 124


def herdr_text(*args):
    """取原始 stdout —— `pane read` 的输出要当文本看，不能当 JSON 解析"""
    try:
        p = subprocess.run(["herdr"] + list(args), capture_output=True, text=True,
                           encoding="utf-8", errors="replace", timeout=60)
        return p.stdout or ""
    except Exception:
        return ""


def read_pane(pane, lines=80):
    return herdr_text("pane", "read", pane, "--source", "recent-unwrapped",
                      "--lines", str(lines))


def gate_names_from_cli():
    """从 gates.py 取权威名称，避免编排器与门禁表脱节"""
    try:
        p = subprocess.run([sys.executable, os.path.join(ROOT, "scripts", "gates.py"), "--list"],
                           capture_output=True, text=True, encoding="utf-8", errors="replace")
        out = {}
        for line in p.stdout.splitlines():
            if "\t" in line:
                k, v = line.split("\t", 1)
                out[k.strip()] = v.strip()
        return out or GATE_NAMES
    except Exception:
        return GATE_NAMES


class Orc:
    def __init__(self, keep=False):
        self.ws = None
        self.keep = keep

    def create_ws(self):
        r = herdr("workspace", "create", "--cwd", ROOT, "--label", WS_LABEL, "--no-focus")
        if not r:
            die("workspace create 失败")
        self.ws = r["workspace"]["workspace_id"]
        print("  ✓ workspace %s (%s, --no-focus)" % (self.ws, WS_LABEL))
        return self.ws

    def new_tab(self, label):
        r = herdr("tab", "create", "--workspace", self.ws, "--cwd", ROOT,
                  "--label", label, "--no-focus")
        if not r:
            return None, None
        return r["tab"]["tab_id"], r["root_pane"]["pane_id"]

    def close_tab(self, tab):
        if tab:
            herdr("tab", "close", tab, check=False)

    def cleanup(self):
        if self.ws and not self.keep:
            herdr("workspace", "close", self.ws, check=False)
            print("  ✓ 已关闭 workspace %s" % self.ws)
        elif self.ws:
            print("  ▸ 保留 workspace %s。查看: herdr workspace focus %s" % (self.ws, self.ws))


def canary(orc, timeout_ms):
    print("▌ 预检 canary（%s）：验证 pane 起得来、哨兵能回、命令跨 shell 可用" % CANARY)
    tab, pane = orc.new_tab("canary")
    if not pane:
        die("canary tab 创建失败")
    herdr("pane", "run", pane, "py scripts/gates.py --only %s" % CANARY, check=False)
    rc = herdr_rc("pane", "wait-output", pane, "--regex",
                  "__GATE_(PASS|FAIL)__ %s" % CANARY,
                  "--source", "recent-unwrapped", "--timeout", "90000")
    text = read_pane(pane, 60)
    if rc == 0 and ("__GATE_PASS__ %s" % CANARY) in text:
        print("  ✓ canary 通过（pane %s 正常响应哨兵）\n" % pane)
        orc.close_tab(tab)
        return True
    print("  ✗ canary 失败。pane 输出:")
    for line in text.splitlines()[-12:]:
        print("      " + line)
    orc.close_tab(tab)
    print("  提示: 检查该 pane 里 'py' 是否可用；用 --keep 保留现场排查。")
    return False


def run_fanout(orc, round_no, timeout_ms, names):
    print("▌ 第 %d 轮：并行扇出 %d 个门禁（只读，安全并行）" % (round_no, len(GATES)))
    tabs, panes = [], []
    for g in GATES:
        tab, pane = orc.new_tab(g)
        if not pane:
            print("  ✗ %s tab 创建失败" % g)
            continue
        tabs.append(tab)
        panes.append((g, pane))
        herdr("pane", "run", pane, "py scripts/gates.py --only %s" % g, check=False)
    print("  ✓ 已启动 %d 个 pane: %s\n" % (len(panes), " ".join(p for _, p in panes)))

    print("  ⧖ 条件等待（哨兵 __GATE_(PASS|FAIL)__ <ID>）...")
    for g, pane in panes:
        rc = herdr_rc("pane", "wait-output", pane, "--regex",
                      "__GATE_(PASS|FAIL)__ %s" % g,
                      "--source", "recent-unwrapped", "--timeout", str(timeout_ms))
        if rc != 0:
            print("    ⏱ %s 超时 (%dms)" % (g, timeout_ms))
    print()

    print("▌ 第 %d 轮：汇总" % round_no)
    print("  %-4s %-8s %s" % ("GATE", "结果", "说明"))
    print("  " + "─" * 74)
    failed = 0
    for g, pane in panes:
        out = read_pane(pane, 80)
        if "__GATE_PASS__ %s" % g in out:
            st = "PASS"
        elif "__GATE_FAIL__ %s" % g in out:
            st, failed = "FAIL", failed + 1
        else:
            st, failed = "TIMEOUT", failed + 1
        detail = ""
        for line in out.splitlines():
            s = line.strip()
            if ("通过 " in s and "失败" in s) or s.startswith("G%s:" % g[1]) or "已一致" in s:
                detail = s
        print("  %-4s %-8s %s  |  %s" % (g, st, names.get(g, ""), detail))
    print()
    for tab in tabs:
        orc.close_tab(tab)
    return failed == 0


def main():
    ap = argparse.ArgumentParser(description="Alpha Radar × Herdr 门禁编排器")
    ap.add_argument("--repeat", type=int, default=1)
    ap.add_argument("--keep", action="store_true")
    ap.add_argument("--build", default="", help="串行构建队列，逗号分隔，如 A2,A3")
    ap.add_argument("--timeout-ms", type=int,
                    default=int(os.environ.get("ALPHA_CI_TIMEOUT_MS", "150000")))
    a = ap.parse_args()

    if os.environ.get("HERDR_ENV") != "1":
        die("未运行在 Herdr 内 (HERDR_ENV != 1)。拒绝从外部操纵会话。")
    if subprocess.run(["herdr", "--version"], capture_output=True).returncode != 0:
        die("找不到 herdr 可执行文件")

    names = gate_names_from_cli()
    print("▌ Alpha Radar × Herdr 门禁编排 v3（跨 shell）")
    print("  调用者 : ws=%s tab=%s pane=%s"
          % (os.environ.get("HERDR_WORKSPACE_ID"), os.environ.get("HERDR_TAB_ID"),
             os.environ.get("HERDR_PANE_ID")))
    print("  cwd    : %s" % ROOT)
    print("  轮次   : %d   超时: %dms" % (a.repeat, a.timeout_ms))
    print()

    orc = Orc(keep=a.keep)
    orc.create_ws()
    print()
    ok = True
    try:
        if not canary(orc, a.timeout_ms):
            ok = False
        else:
            for r in range(1, a.repeat + 1):
                if not run_fanout(orc, r, a.timeout_ms, names):
                    ok = False

        if a.build:
            print("▌ 串行构建队列: %s" % a.build)
            print("  规则：单一写者 —— 所有构建任务都改 scripts/alpha_ledger.py，必须串行。\n")
            for t in [x.strip() for x in a.build.split(",") if x.strip()]:
                desc, needs = TASKS.get(t, ("未知任务", False))
                if needs:
                    print("  ⛔ %s  %s" % (t, desc))
                    print("     → 拒绝自动执行：会改变仓库形态（新建 .git），需你人工批准。")
                    ok = False
                    continue
                print("  ▸ %s  %s" % (t, desc))
                print("     ⚠ 这不是编排器能自动完成的事 —— 实现需由人/agent 编写代码。")
                print("       编排器负责的是：排队 + 每步后跑门禁 + 失败即停。")
            print()
    finally:
        orc.cleanup()

    print("═" * 64)
    if ok:
        print("  ✅ 全部通过（门禁执行 %d 次 + canary 1 次）" % (len(GATES) * a.repeat))
    else:
        print("  ❌ 存在未通过项 —— 不要进入下一阶段构建")
    print("═" * 64)
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())