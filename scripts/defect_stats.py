#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""缺陷册自洽检查 —— DEFECTS.md 的统计数字必须由表格生成，不能手写

起因（D-92）：
    统计行一直是手写的。为了让审查能引用"S1 修了几个"，我用正则重数了一遍表格，
    发现四项全错，而且"S1 全部已修复"与 D-18 的"⛔ 待批准"直接矛盾。
    更讽刺的是：我修正统计行之后又新增了一条缺陷，计数再次漂移 ——
    **修复动作本身制造了同一类错误。**

    结论：这类数字不该由人维护。

用法:
    py scripts/defect_stats.py            # 打印统计（供人复制/核对）
    py scripts/defect_stats.py --write    # 就地重写 DEFECTS.md 的统计表
    py scripts/defect_stats.py --check    # 只比对，不一致则退出码 1（门禁用）
    py scripts/defect_stats.py --json     # 机器可读

表格约定（主表，位于「二、缺陷登记（主表）」）：
    | D-XX | S1 | 描述 | ✅ 已修复 |
状态列含「已修复」= 关闭；其余（⬜ 未修复 / ⛔ 待批准 / …）= 未关闭。
"""
import argparse
import json
import os
import re
import sys

try:
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
except Exception:
    pass

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEFECTS = os.path.join(ROOT, "DEFECTS.md")

SEVERITIES = ["S1", "S2", "S3", "S4"]

# 主表行：| **D-80** | **S1** | 描述 | ✅ 已修复 |
ROW_RE = re.compile(r"^\|\s*\**\s*(D-\d+)\s*\**\s*\|"
                    r"\s*\**\s*(S[1-4])\s*\**\s*\|"
                    r"\s*(.*?)\s*\|"
                    r"\s*(.*?)\s*\|\s*$", re.M)

STATS_HEAD = "**统计（"
STATS_HEAD_OLD = "**统计**："


def parse_rows(text):
    """→ [{id, sev, desc, status, fixed}]"""
    out = []
    for m in ROW_RE.finditer(text):
        did, sev, desc, status = m.group(1), m.group(2), m.group(3), m.group(4)
        out.append({"id": did, "sev": sev, "desc": desc,
                    "status": status, "fixed": "已修复" in status})
    return out


def summarize(rows):
    s = {}
    for sev in SEVERITIES:
        sub = [r for r in rows if r["sev"] == sev]
        s[sev] = {"total": len(sub),
                  "fixed": sum(1 for r in sub if r["fixed"]),
                  "open": sum(1 for r in sub if not r["fixed"])}
    s["total"] = {"total": len(rows),
                  "fixed": sum(1 for r in rows if r["fixed"]),
                  "open": sum(1 for r in rows if not r["fixed"])}
    s["open_items"] = ["%s(%s)" % (r["id"], r["sev"]) for r in rows if not r["fixed"]]
    return s


def render_stats(s):
    """生成可直接写进 DEFECTS.md 的统计块（不含锚点标题）"""
    lines = ["| 等级 | 合计 | 已修复 | 未关闭 |", "|---|---:|---:|---:|"]
    for sev in SEVERITIES:
        d = s[sev]
        lines.append("| %s | %d | %d | %d |" % (sev, d["total"], d["fixed"], d["open"]))
    t = s["total"]
    lines.append("| **合计** | **%d** | **%d** | **%d** |" % (t["total"], t["fixed"], t["open"]))
    lines.append("")
    lines.append("**未关闭明细**：%s" % ("、".join(s["open_items"]) if s["open_items"] else "无"))
    return "\n".join(lines)


def status_of(defect_id, text=None):
    """某条缺陷是否已关闭。供门禁的 expected-fail 机制判断"豁免是否还有效"。"""
    text = text if text is not None else open(DEFECTS, encoding="utf-8").read()
    for r in parse_rows(text):
        if r["id"] == defect_id:
            return r["status"]
    return None


def _stats_block_span(text):
    """定位统计块 = 标题行 + 空行 + 小表 + 空行 + 「未关闭明细」行。

    必须精确到「未关闭明细」这一行为止 —— 不能一路延伸到下一个分隔线。
    统计块后面常跟着更正说明（blockquote），里面会引用旧文案
    （例如"上一版写的是「S1 全部已修复」"），把它算进块内会产生**假警报**。
    这是 D-73 / D-90 的老问题：断言不能把"对错误的引用"当成"错误本身"。
    """
    i = text.find(STATS_HEAD)
    if i < 0:
        i = text.find(STATS_HEAD_OLD)
    if i < 0:
        return None, None
    m = re.search(r"^\*\*未关闭明细\*\*：.*$", text[i:], re.M)
    if m:
        return i, i + m.end()
    j = text.find(chr(10) * 2, i)
    return i, (j if j >= 0 else len(text))



def cmd_show(a):
    text = open(DEFECTS, encoding="utf-8").read()
    s = summarize(parse_rows(text))
    if a.json:
        print(json.dumps(s, ensure_ascii=False, indent=1))
        return 0
    print("DEFECTS.md 主表实数（按行解析，非手工统计）\n" + "=" * 52)
    print(render_stats(s))
    return 0


def cmd_check(a):
    text = open(DEFECTS, encoding="utf-8").read()
    rows = parse_rows(text)
    if not rows:
        print("❌ 无法从主表解析出任何缺陷行（表格格式变了？）")
        print("__DEFECT_STATS_FAIL__")
        return 1
    s = summarize(rows)
    i, k = _stats_block_span(text)
    if i is None:
        print("❌ DEFECTS.md 找不到统计块（'**统计（' 或 '**统计**：'）")
        print("__DEFECT_STATS_FAIL__")
        return 1

    block = text[i:k]
    problems = []
    # 逐等级核对数字：块内必须出现 "| S1 | 31 | 30 | 1 |"
    for sev in SEVERITIES:
        d = s[sev]
        pat = re.compile(r"\|\s*%s\s*\|\s*%d\s*\|\s*%d\s*\|\s*\**\s*%d\s*\**\s*\|"
                         % (sev, d["total"], d["fixed"], d["open"]))
        if not pat.search(block):
            problems.append("%s：表格实数 合计%d/修复%d/未关闭%d，统计块里找不到一致的行"
                            % (sev, d["total"], d["fixed"], d["open"]))

    # "全部已修复" 类断言必须与实数一致
    if re.search(r"全部已修复", block):
        bad = [r["id"] for r in rows if not r["fixed"]]
        if bad:
            problems.append("统计块声称「全部已修复」，但仍有 %d 条未关闭：%s"
                            % (len(bad), "、".join(bad[:8])))

    # 未关闭明细必须逐项出现
    for item in s["open_items"]:
        did = item.split("(")[0]
        if did not in block:
            problems.append("未关闭项 %s 未出现在统计块的明细里" % did)

    if problems:
        for p in problems:
            print("❌ " + p)
        print()
        print("应为：")
        print(render_stats(s))
        print("__DEFECT_STATS_FAIL__")
        return 1
    print("✅ 缺陷册统计与主表一致：共 %d 条（修复 %d / 未关闭 %d）"
          % (s["total"]["total"], s["total"]["fixed"], s["total"]["open"]))
    print("__DEFECT_STATS_PASS__")
    return 0


def cmd_write(a):
    text = open(DEFECTS, encoding="utf-8").read()
    s = summarize(parse_rows(text))
    i, k = _stats_block_span(text)
    if i is None:
        print("❌ 找不到统计块，未改动")
        return 1
    new = ("**统计（由 `scripts/defect_stats.py --write` 从主表生成，勿手改）**：\n\n"
           + render_stats(s) + "\n\n")
    open(DEFECTS, "w", encoding="utf-8", newline="\n").write(text[:i] + new + text[k:])
    print("✓ 已重写统计块：共 %d 条（修复 %d / 未关闭 %d）"
          % (s["total"]["total"], s["total"]["fixed"], s["total"]["open"]))
    return 0


def main():
    ap = argparse.ArgumentParser(description="缺陷册自洽检查")
    g = ap.add_mutually_exclusive_group()
    g.add_argument("--check", action="store_true", help="比对统计与表格，不一致退出 1")
    g.add_argument("--write", action="store_true", help="按表格重写统计块")
    g.add_argument("--json", action="store_true", help="机器可读输出")
    a = ap.parse_args()
    if a.check:
        return cmd_check(a)
    if a.write:
        return cmd_write(a)
    return cmd_show(a)


if __name__ == "__main__":
    sys.exit(main() or 0)
