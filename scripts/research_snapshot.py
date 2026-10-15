#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Generate and validate auditable research snapshots."""
import argparse
import hashlib
import json
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
except Exception:
    pass

ROOT = Path(__file__).resolve().parent.parent
ANALYSIS = ROOT / "analysis"
OUT = ROOT / "data" / "research_snapshots"


def report_grade(text):
    head = text[:800]
    if "研究级" in head:
        return "research"
    if "规则输出" in text or "规则情景" in text:
        return "rule"
    return "report"


def sha256(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def run_metrics(ticker):
    p = subprocess.run([sys.executable, str(ROOT / "scripts" / "alpha_metrics.py"), ticker, "--json"],
                       cwd=ROOT, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=180)
    raw = p.stdout
    if "{" not in raw:
        raise RuntimeError((raw + "\n" + p.stderr).strip()[-1200:])
    try:
        return json.loads(raw[raw.index("{"):])
    except json.JSONDecodeError as e:
        raise RuntimeError("alpha_metrics JSON 无法解析: %s" % e)


def amount(text):
    m = re.search(r"([−-]?)\s*\$?\s*([0-9][0-9,]*(?:\.[0-9]+)?)\s*(T|B|M|K)?", text)
    if not m:
        return None
    scale = {"T": 1e12, "B": 1e9, "M": 1e6, "K": 1e3, None: 1}[m.group(3)]
    return (-1 if m.group(1) else 1) * float(m.group(2).replace(",", "")) * scale


def report_assertions(text):
    """Extract values only from canonical table/header forms."""
    patterns = {
        "price": r"Current Price.*?\$\s*([0-9][0-9,]*(?:\.[0-9]+)?)",
        "ttm_revenue": r"\|\s*Revenue（TTM[^|]*\|\s*([^|]+)",
        "ttm_fcf": r"\|\s*(?:\*\*)?FCF（TTM）(?:\*\*)?\s*\|\s*([^|]+)",
        "roic_pct": r"\|\s*(?:\*\*)?ROIC(?:\*\*)?\s*\|\s*([−-]?[0-9]+(?:\.[0-9]+)?)%",
        "net_debt_ebitda": r"(?:Net Debt / EBITDA|ND/EBITDA|Net Debt/EBITDA)\s*(?:\|\s*)?(?:\*\*)?([−-]?[0-9]+(?:\.[0-9]+)?)x",
    }
    out = {}
    for key, pattern in patterns.items():
        m = re.search(pattern, text, re.I)
        if not m:
            continue
        try:
            out[key] = float(m.group(1).replace(",", "")) if key in ("price", "roic_pct", "net_debt_ebitda") else amount(m.group(1))
        except ValueError:
            pass
    return out


def close(a, b, grade="research"):
    # Research reports use precise values; rule/report dossiers often round to
    # 0.01B or 0.1%, so their displayed value cannot support a tight check.
    tolerance = {"research": 0.012, "report": 0.06, "rule": 0.12}.get(grade, 0.012)
    return a is not None and b is not None and abs(a - b) <= max(abs(b) * tolerance, 0.02)


def snapshot_for(path):
    ticker = path.stem.replace("_AlphaRadar", "").upper()
    text = path.read_text(encoding="utf-8")
    try:
        metrics = run_metrics(ticker)
        has_ttm = bool(metrics.get("ttm_period") not in (None, "?", "") and metrics.get("ttm_revenue") is not None)
        # A financial-company report may have a TTM value while the generic
        # industrial-company verifier has hard source mismatches. Such a
        # report must not become formally qualified until its metric adapter
        # is repaired and independently verified.
        adapter_blocked = "未通过通用数据校验" in text or "数据校验未通过" in text
        usable = has_ttm and not adapter_blocked
        status = "verified" if usable else "blocked"
        if adapter_blocked:
            error = "报告明确标注为数据校验未通过，等待金融机构口径适配"
        else:
            error = None if usable else "缺少真实 TTM 截止日或营业收入"
        if not usable:
            metrics = {k: v for k, v in metrics.items() if k in ("ticker", "entity")}
    except Exception as e:
        metrics, status, error = {"ticker": ticker}, "blocked", str(e)
    keys = ("ticker", "entity", "ttm_period", "ttm_revenue", "ttm_gross_profit", "ttm_op_income",
            "ttm_net_income", "ttm_ocf", "ttm_capex", "ttm_fcf", "gross_margin_pct", "op_margin_pct",
            "net_margin_pct", "fcf_margin_pct", "cash_conversion_pct", "revenue_growth_ttm_pct",
            "fcf_growth_ttm_pct", "cash", "equity", "debt", "net_debt", "ebitda_ttm", "net_debt_ebitda",
            "shares", "shares_date", "price", "market_cap", "tax_rate", "nopat", "invested_capital", "roic_pct")
    return {
        "schema_version": 1, "ticker": ticker, "status": status,
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "report": {"path": str(path.relative_to(ROOT)).replace("\\", "/"), "sha256": sha256(path),
                   "grade": report_grade(text), "assertions": report_assertions(text)},
        "qualification": {
            "data_status": status,
            "formal_predictions": status == "verified" and report_grade(text) == "research",
            "formal_valuation": status == "verified" and report_grade(text) == "research",
            "portfolio_decisions": status == "verified" and report_grade(text) == "research",
        },
        "data": {k: metrics[k] for k in keys if k in metrics}, "error": error,
    }


def generate():
    OUT.mkdir(parents=True, exist_ok=True)
    paths = sorted(ANALYSIS.glob("*_AlphaRadar.md"))
    if not paths:
        raise SystemExit("没有找到 analysis/*_AlphaRadar.md")
    for path in paths:
        snap = snapshot_for(path)
        (OUT / (snap["ticker"] + ".json")).write_text(json.dumps(snap, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print("%-5s %-8s %s" % (snap["ticker"], snap["status"], (OUT / (snap["ticker"] + ".json")).relative_to(ROOT)))


def validate():
    problems = []
    paths = sorted(ANALYSIS.glob("*_AlphaRadar.md"))
    for path in paths:
        ticker = path.stem.replace("_AlphaRadar", "").upper()
        out = OUT / (ticker + ".json")
        if not out.exists():
            problems.append("%s: 缺少研究快照" % ticker)
            continue
        try:
            snap = json.loads(out.read_text(encoding="utf-8"))
        except Exception as e:
            problems.append("%s: 快照 JSON 无法解析: %s" % (ticker, e))
            continue
        if snap.get("schema_version") != 1:
            problems.append("%s: 不支持的快照 schema" % ticker)
        if snap.get("report", {}).get("sha256") != sha256(path):
            problems.append("%s: 报告已改变，请重新生成研究快照" % ticker)
        if snap.get("status") == "blocked":
            print("⚠ %s: blocked（%s）" % (ticker, snap.get("error") or "数据不足"))
            continue
        try:
            current = run_metrics(ticker)
        except Exception as e:
            problems.append("%s: 当前指标无法生成: %s" % (ticker, e))
            continue
        old = snap.get("data", {})
        for key, value in current.items():
            if key in old and old[key] != value:
                problems.append("%s: %s 已变化（快照=%r，当前=%r）" % (ticker, key, old[key], value))
        for shown_key, metric_key in {"price": "price", "ttm_revenue": "ttm_revenue", "ttm_fcf": "ttm_fcf",
                                      "roic_pct": "roic_pct", "net_debt_ebitda": "net_debt_ebitda"}.items():
            shown, actual = snap.get("report", {}).get("assertions", {}).get(shown_key), current.get(metric_key)
            grade = snap.get("report", {}).get("grade", "research")
            if shown is not None and actual is not None and not close(shown, actual, grade):
                problems.append("%s: 报告 %s=%r 与指标引擎 %s=%r 不一致（档案等级=%s）" %
                                (ticker, shown_key, shown, metric_key, actual, grade))
    if problems:
        for p in problems:
            print("❌ " + p)
        print("__SNAPSHOT_FAIL__")
        return 1
    print("✅ 研究快照一致：%d 份" % len(paths))
    print("__SNAPSHOT_PASS__")
    return 0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("command", choices=["generate", "validate"])
    a = ap.parse_args()
    return generate() if a.command == "generate" else validate()


if __name__ == "__main__":
    sys.exit(main() or 0)
