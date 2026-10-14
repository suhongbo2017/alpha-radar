#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Alpha Radar one-command data and screening pipeline.

This command automates reproducible data collection and rule screening. It does
not manufacture a research-grade dossier, formal prediction, or portfolio
decision from mechanical output.
"""
import argparse
import datetime as dt
import json
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
RUNS = os.path.join(ROOT, "data", "runs")
TICKER_RE = re.compile(r"^[A-Z][A-Z0-9.\-]{0,9}$")


def run_stage(name, args, allow_failure=False):
    proc = subprocess.run(
        [sys.executable] + args,
        cwd=ROOT,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        encoding="utf-8",
        errors="replace",
    )
    result = {"name": name, "command": args, "returncode": proc.returncode,
              "output": proc.stdout}
    if proc.returncode and not allow_failure:
        result["fatal"] = True
    return result


def parse_json_output(output):
    # Some existing commands print a short human header before JSON. Find the
    # first complete JSON object rather than relying on a fixed line number.
    for i, ch in enumerate(output):
        if ch != "{":
            continue
        try:
            return json.loads(output[i:])
        except json.JSONDecodeError:
            continue
    return None


def write_research_draft(ticker, run_at, metrics, scenario, path):
    """Create an explicit, non-qualifying handoff document for human research."""
    def value(key):
        item = metrics.get(key)
        return "" if item is None else str(item)

    text = """# %s（待人工完成）— Alpha Radar 研究草稿

> 这是自动数据流程生成的研究草稿，不是正式 Alpha Radar 档案。
> 不得直接登记正式预测、Fair Value 或组合决策。
> 运行时间：%s
> 数据状态：rule-screened
> 规则情景：仅作低置信度筛选，不是内在价值。

## 0. 一句话结论

> 待人工研究后填写。

## 1. Business

- Business Model：待填写
- Revenue Sources：待填写
- Customers / 集中度：待填写
- Market / TAM：待填写
- Competitors：待填写

## 2. Fundamental（自动填充，需核对原文）

| 指标 | 自动值 | 备注 |
|---|---:|---|
| TTM 截止日 | %s | 需核对 10-K/10-Q |
| TTM Revenue | %s | SEC companyfacts |
| TTM Gross Margin | %s | SEC companyfacts |
| TTM Operating Margin | %s | SEC companyfacts |
| TTM FCF | %s | OCF - CapEx |
| TTM FCF Margin | %s | SEC companyfacts |
| ROIC | %s | 需核对投入资本和税率 |
| Net Debt / EBITDA | %s | 需核对现金、短投和租赁 |
| Shares Outstanding | %s | 需核对稀释口径 |
| Current Price | %s | 行情快照 |

## 3. Moat and Management

- 护城河证据：待填写
- 护城河趋势：待填写
- 管理层资本配置：待填写
- 股权激励与稀释：待填写
- 关键反证：待填写

## 4. Forecast

自动规则情景仅作筛选参考，不能直接复制为正式预测。

```json
%s
```

- Bull 假设及概率：待填写
- Base 假设及概率：待填写
- Bear 假设及概率：待填写
- 收入、利润、FCF、稀释股数和终值倍数桥接：待填写

## 5. Valuation

- 估值方法：待填写
- 2027 / 2030 Fair Value：待填写
- 每股价值推导：待填写
- Margin of Safety：待填写
- 失效条件：待填写

## 6. Decision

- Current Action：待填写
- 价格触发条件：待填写
- 组合层面影响：待填写

## 7. Evidence Checklist

- [ ] 最近 10-K/10-Q 原文已核对
- [ ] TTM、FY、币种、债务和租赁口径已记录
- [ ] 业务、竞争格局和护城河证据已记录
- [ ] Bull/Base/Bear 概率完整且合计 100%%
- [ ] 估值桥可从收入追溯到每股价值
- [ ] 研究报告已保存到 `analysis/%s_AlphaRadar.md`
- [ ] 已运行 `py scripts/research_snapshot.py generate`
- [ ] 快照状态为 `verified` 且档案等级为 `research`

## Appendix

- 自动运行报告：`%s`
- 数据源与限制：待填写
""" % (ticker, run_at, value("ttm_period"), value("ttm_revenue"),
       value("gross_margin_pct"), value("op_margin_pct"), value("ttm_fcf"),
       value("fcf_margin_pct"), value("roic_pct"), value("net_debt_ebitda"),
       value("shares"), value("price"), json.dumps(scenario, ensure_ascii=False, indent=2),
       ticker, path)
    with open(path, "w", encoding="utf-8") as f:
        f.write(text)


def main():
    ap = argparse.ArgumentParser(description="Alpha Radar 一键数据分析与粗筛")
    ap.add_argument("ticker", help="股票代码，例如 NVDA")
    ap.add_argument("--force", action="store_true", help="强制刷新 SEC 数据")
    ap.add_argument("--offline", action="store_true", help="只用现有行情缓存，不请求行情")
    ap.add_argument("--no-cross", action="store_true", help="跳过外部交叉校验")
    ap.add_argument("--no-report", action="store_true", help="不生成 Markdown 运行报告")
    ap.add_argument("--no-draft", action="store_true", help="不生成研究草稿")
    a = ap.parse_args()

    ticker = a.ticker.upper().strip()
    if not TICKER_RE.fullmatch(ticker):
        ap.error("ticker 格式无效：%s" % ticker)

    started = dt.datetime.now().astimezone()
    stages = []
    if not a.offline:
        fetch = ["scripts/alpha_fetch.py", ticker]
        if a.force:
            fetch.append("--force")
        fetch_stage = run_stage("SEC 原始数据", fetch, allow_failure=True)
        stages.append(fetch_stage)
    else:
        stages.append({"name": "SEC 原始数据", "skipped": True,
                       "output": "--offline：跳过下载，使用本地数据"})

    quote = ["scripts/alpha_quote.py", ticker]
    if a.offline:
        quote.append("--offline")
    stages.append(run_stage("行情快照", quote, allow_failure=True))

    metrics = run_stage("一手财务指标", ["scripts/alpha_metrics.py", ticker, "--json"],
                        allow_failure=True)
    metrics["parsed"] = parse_json_output(metrics["output"])
    stages.append(metrics)

    verify_args = ["scripts/verify_data.py", ticker]
    if a.no_cross:
        verify_args.append("--no-cross")
    else:
        verify_args.append("--require-cross")
    verify_stage = run_stage("多层数据校验", verify_args, allow_failure=True)
    stages.append(verify_stage)

    scenario = run_stage("规则化情景", ["scripts/alpha_scenario.py", ticker, "--json"],
                         allow_failure=True)
    scenario["parsed"] = parse_json_output(scenario["output"])
    stages.append(scenario)

    verify_failed = verify_stage.get("returncode", 1) != 0
    scenario_data = scenario.get("parsed") or {}
    metrics_data = metrics.get("parsed") or {}
    if verify_failed:
        status = "failed"
    elif not metrics_data.get("ttm_period") or not metrics_data.get("ttm_revenue"):
        status = "blocked"
    else:
        status = "rule-screened"

    manual_prompts = [
        "核对最近 10-K/10-Q 原文：TTM 期间、收入、现金流、债务/租赁口径及币种。",
        "补充业务分部、客户集中度、竞争格局、定价权与护城河证据。",
        "评估管理层资本配置、股权稀释、激励和关联交易。",
        "建立可追溯的 Bull/Base/Bear 假设与概率；不得直接照抄规则情景。",
        "完成估值桥：收入/利润/FCF、稀释股数、终值假设、每股价值和安全边际。",
        "依据研究结论独立决定 Watch/Buy 等动作；本命令不会替用户写入正式决策。",
    ]
    data_gaps = []
    for key, label in (("ttm_period", "TTM 截止日"), ("ttm_revenue", "TTM 收入"),
                       ("ttm_fcf", "TTM 自由现金流"), ("roic_pct", "ROIC"),
                       ("net_debt_ebitda", "净债务/EBITDA"), ("price", "现价")):
        if metrics_data.get(key) is None:
            data_gaps.append(label)

    result = {
        "ticker": ticker,
        "run_at": started.isoformat(timespec="seconds"),
        "status": status,
        "qualification": {
            "dossier_grade": "rule" if status == "rule-screened" else "blocked",
            "formal_predictions": False,
            "formal_valuation": False,
            "portfolio_decisions": False,
        },
        "metrics": metrics_data,
        "scenario": scenario_data,
        "data_gaps": data_gaps,
        "stage_warnings": [
            "%s 阶段失败：%s" % (s["name"], (s.get("output") or "").strip()[-500:])
            for s in stages if not s.get("skipped") and s.get("returncode", 0) != 0
        ],
        "manual_prompts": manual_prompts,
        "stages": stages,
        "next_step": (
            "补充一手资料、行业研究和研究级档案后再登记正式预测"
            if status == "rule-screened" else
            ("修复数据校验错误后重跑" if status == "failed" else
             "修复数据源或补充真实 TTM Revenue/截止日")
        ),
    }
    os.makedirs(RUNS, exist_ok=True)
    stamp = started.strftime("%Y%m%d_%H%M%S")
    json_path = os.path.join(RUNS, "%s_%s.json" % (ticker, stamp))
    draft_path = None
    if status == "rule-screened" and not a.no_draft:
        draft_path = os.path.join(RUNS, "%s_%s_research_draft.md" % (ticker, stamp))
        write_research_draft(ticker, result["run_at"], metrics_data, scenario_data,
                             draft_path)
    result["research_draft"] = draft_path
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)

    if not a.no_report:
        md_path = os.path.join(RUNS, "%s_%s.md" % (ticker, stamp))
        with open(md_path, "w", encoding="utf-8") as f:
            f.write("# %s Alpha Radar 一键运行报告\n\n" % ticker)
            f.write("- 运行时间：%s\n- 自动状态：**%s**\n" % (result["run_at"], status))
            f.write("- 档案资格：`rule`，不可登记正式预测/正式估值/组合决策\n\n")
            f.write("## 机器指标\n\n```json\n%s\n```\n\n" %
                    json.dumps(metrics_data, ensure_ascii=False, indent=2))
            f.write("## 规则情景\n\n```json\n%s\n```\n\n" %
                    json.dumps(scenario_data, ensure_ascii=False, indent=2))
            f.write("## 阶段失败与数据源提示\n\n")
            f.write("\n".join("- %s" % x for x in result["stage_warnings"]) if result["stage_warnings"] else "- 无")
            f.write("\n\n## 自动发现的数据缺口\n\n")
            f.write("\n".join("- %s" % x for x in data_gaps) if data_gaps else "- 核心指标字段均有值")
            f.write("\n\n## 需要人工完成的研究判断\n\n")
            f.write("\n".join("- %s" % x for x in manual_prompts))
            f.write("\n\n## 后续动作\n\n%s\n" % result["next_step"])
    else:
        md_path = None

    print("Alpha Radar 一键运行：%s" % ticker)
    print("状态：%s" % status)
    print("结果：%s" % json_path)
    if md_path:
        print("报告：%s" % md_path)
    if draft_path:
        print("研究草稿：%s" % draft_path)
    for s in stages:
        mark = "跳过" if s.get("skipped") else ("通过" if s.get("returncode", 0) == 0 else "失败")
        print("  %-12s %s" % (mark, s["name"]))
    print("注意：自动规则情景不是研究级估值，也没有写入正式预测或投资决策。")
    return 0 if status != "failed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
