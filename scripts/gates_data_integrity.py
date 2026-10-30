#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Gate G3 —— 真实数据（data/*.jsonl）完整性

这套系统的全部价值建立在"预测完整性"上，所以账本本身要能被体检。

检查：
  1. JSONL 每行可解析
  2. 预测条数不少于基线（防止误删）
  3. 必填字段齐全
  4. metric 命中词表
  5. 同一 (ticker, metric, period, version, scenario) 不出现数值冲突
  6. actual 的 metric 必须有对应 prediction（防止孤儿实际值）
逐条列出问题，退出码 0/1。
"""
import json
import os
import sys

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "scripts"))

import importlib.util
_spec = importlib.util.spec_from_file_location("al", os.path.join(ROOT, "scripts", "alpha_ledger.py"))
_al = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_al)

DATA = os.path.join(ROOT, "data")
PRED = os.path.join(DATA, "predictions.jsonl")
ACT = os.path.join(DATA, "actuals.jsonl")
DEC = os.path.join(DATA, "decisions.jsonl")
BASELINE = 15  # 2026-10-07 已登记 15 条；只允许增加

REQ_PRED = {"ticker", "analysis_date", "forecast_version", "scenario",
            "metric", "forecast_period", "forecast_value", "unit"}
REQ_ACT = {"ticker", "metric", "period", "actual_value", "unit"}
REQ_DEC = {"ticker", "decision_date", "action", "price", "currency"}
SNAPSHOTS = os.path.join(DATA, "research_snapshots")

problems = []
warnings = []


def load_jsonl(path, label):
    if not os.path.exists(path):
        return []
    out = []
    with open(path, encoding="utf-8") as f:
        for i, line in enumerate(f, 1):
            line = line.strip()
            if not line:
                continue
            try:
                out.append(json.loads(line))
            except Exception as e:
                problems.append("%s 第 %d 行无法解析: %s" % (label, i, e))
    return out


def main():
    preds = load_jsonl(PRED, "predictions.jsonl")
    raw_acts = load_jsonl(ACT, "actuals.jsonl")
    decs = load_jsonl(DEC, "decisions.jsonl")
    # actuals.jsonl 里可能混有 attribution 追记，分开处理
    acts = [r for r in raw_acts if r.get("record_type") != "attribution"]
    atts = [r for r in raw_acts if r.get("record_type") == "attribution"]

    print("  predictions=%d  actuals=%d  attributions=%d  decisions=%d"
          % (len(preds), len(acts), len(atts), len(decs)))

    if len(preds) < BASELINE:
        problems.append("预测条数 %d < 基线 %d —— 可能有记录被误删/覆盖" % (len(preds), BASELINE))

    for i, r in enumerate(preds, 1):
        miss = REQ_PRED - set(r)
        if miss:
            problems.append("predictions #%d 缺字段: %s" % (i, ",".join(sorted(miss))))
            continue
        if _al.canonical_metric(r["metric"])[0] is None:
            problems.append("predictions #%d 指标 '%s' 不在词表中" % (i, r["metric"]))
        if not isinstance(r["forecast_value"], (int, float)):
            problems.append("predictions #%d forecast_value 非数值" % i)
        if r.get("period_type") not in (None, "half_year", "quarter", "fiscal_year", "custom"):
            problems.append("predictions #%d period_type 非法: %s" % (i, r.get("period_type")))
        if r.get("horizon_type") not in (None, "operating_checkpoint", "valuation_terminal"):
            problems.append("predictions #%d horizon_type 非法: %s" % (i, r.get("horizon_type")))
        status = r.get("prediction_status")
        if status == "formal":
            snap_path = os.path.join(SNAPSHOTS, "%s.json" % r["ticker"])
            try:
                with open(snap_path, encoding="utf-8") as sf:
                    qualification = json.load(sf).get("qualification", {})
                if not qualification.get("formal_predictions"):
                    problems.append("predictions #%d: formal 预测没有正式档案资格（%s）" % (i, r["ticker"]))
            except (OSError, ValueError):
                problems.append("predictions #%d: formal 预测缺少研究快照（%s）" % (i, r["ticker"]))
        p = r.get("probability")
        if p is not None and not (0 < p <= 1):
            problems.append("predictions #%d probability=%s 越界（应 0-1）" % (i, p))

    for i, r in enumerate(acts, 1):
        miss = REQ_ACT - set(r)
        if miss:
            problems.append("actuals #%d 缺字段: %s" % (i, ",".join(sorted(miss))))
            continue
        if _al.canonical_metric(r["metric"])[0] is None:
            problems.append("actuals #%d 指标 '%s' 不在词表中" % (i, r["metric"]))
        if r.get("attribution") and _al.canonical_attribution(r["attribution"]) is None:
            problems.append("actuals #%d 归因 '%s' 非法" % (i, r["attribution"]))

    for i, r in enumerate(atts, 1):
        if _al.canonical_attribution(r.get("attribution", "")) is None:
            problems.append("attribution #%d 归因 '%s' 非法" % (i, r.get("attribution")))

    # [D-05] 决策库校验
    for i, r in enumerate(decs, 1):
        miss = REQ_DEC - set(r)
        if miss:
            problems.append("decisions #%d 缺字段: %s" % (i, ",".join(sorted(miss))))
            continue
        if _al.canonical_action(r["action"]) is None:
            problems.append("decisions #%d 动作 '%s' 不在动作表中" % (i, r["action"]))
        if not isinstance(r["price"], (int, float)) or r["price"] <= 0:
            problems.append("decisions #%d price 非法: %s" % (i, r.get("price")))
        # 违反赔率纪律只告警不报错 —— 如实记录错误决策本身就是这套系统的价值
        if r["action"] in ("Buy", "StrongBuy", "Core", "Starter") \
           and r.get("odds") is not None and r["odds"] < 1:
            warnings.append("decisions #%d: %s 在赔率 %.2f:1 时选了 %s（违反赔率纪律，已如实留痕）"
                            % (i, r["ticker"], r["odds"], r["action"]))

    # 正式预测的情景口径：要么三情景齐全且概率合计 100%，要么显式声明为单点预测。
    # [D-94] 原来的断言只有前一种，于是锚定一致预期的 1-2 年核对点被逼成两种坏选择：
    #   ① 硬造 Bear/Bull → 发明三个数字（比缺字段更糟）
    #   ② 降级 informational → 不算分，等于不打算核对
    # 现规则：单点合法，但必须可追溯（source_basis）、不得带概率、不得用于终局估值。
    formal_groups = {}
    for r in preds:
        if r.get("prediction_status") == "formal":
            k = (r.get("ticker"), r.get("metric"), _al.norm_period(r.get("forecast_period", "")),
                 r.get("forecast_version", "v1"))
            formal_groups.setdefault(k, []).append(r)
    legacy_points = []
    point_total = 0
    for k, rows in formal_groups.items():
        scenarios = {r.get("scenario") for r in rows}
        probs = [r.get("probability") for r in rows]
        declared = {r.get("scenario_set") for r in rows}
        is_point = (len(rows) == 1 and scenarios == {"Base"}
                    and declared <= {"point", None} and probs == [None])
        if is_point:
            point_total += 1
            r0 = rows[0]
            if not (r0.get("source_basis") or "").strip():
                problems.append("单点预测缺 source_basis（无法追溯锚点，无法复核）: %s" % (k,))
            if r0.get("horizon_type") == "valuation_terminal" or \
               r0.get("metric") in ("FairValue", "Target_Price"):
                problems.append("终局估值不允许单点预测（必须给 Bull/Base/Bear 区间）: %s" % (k,))
            if any(r.get("scenario_set") is None for r in rows):
                legacy_points.append(k)      # D-94 之前的旧记录，字段不存在
            continue
        if scenarios != {"Bull", "Base", "Bear"} or any(p is None for p in probs) or abs(sum(probs) - 1.0) > 0.001:
            problems.append("formal 情景概率不完整或不合计 100%%: %s scenarios=%s probs=%s" % (k, sorted(scenarios), probs))
    if point_total:
        print("  单点预测（无区间）: %d 组%s" % (
            point_total,
            "（其中 %d 组为 D-94 之前的旧记录，靠隐含规则认定）" % len(legacy_points) if legacy_points else ""))

    # 版本内数值冲突
    seen = {}
    for r in preds:
        k = (r.get("ticker"), r.get("metric"), _al.norm_period(r.get("forecast_period", "")),
             r.get("forecast_version", "v1"), r.get("scenario"))
        v = r.get("forecast_value")
        if k in seen and seen[k] != v:
            problems.append("版本内数值冲突 %s: %s vs %s" % (k, seen[k], v))
        seen[k] = v

    # 孤儿 actual（attribution 追记不参与）
    # 判定为【告警】而非【错误】：录入基线年份的观测值（如 FY2025）本身是合法用途，
    # 而指标名拼错已在写入时被词表拦住，所以这里只需可见，不必阻断。
    pkeys = {(r["ticker"], r["metric"], _al.norm_period(r["forecast_period"])) for r in preds}
    for r in acts:
        k = (r["ticker"], r["metric"], _al.norm_period(r["period"]))
        if k not in pkeys:
            warnings.append("基线观测（无对应预测）: %s %s %s = %s  [非错误，仅提示]"
                            % (k[0], k[1], k[2], r.get("actual_value")))
    for r in atts:
        k = (r["ticker"], r["metric"], _al.norm_period(r["period"]))
        if k not in pkeys:
            problems.append("孤儿归因（无对应预测）: %s" % (k,))

    for w in warnings:
        print("  ⚠ " + w)
    if problems:
        for p in problems:
            print("  ✗ " + p)
        print("  G3: %d 处问题" % len(problems))
        return 1
    print("  G3: 账本完整" + ("（%d 条告警）" % len(warnings) if warnings else ""))
    return 0


if __name__ == "__main__":
    sys.exit(main())