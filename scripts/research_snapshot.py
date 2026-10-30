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
    """报告内容哈希 —— **必须先归一换行**。

    [D-98] 原实现直接 sha256(read_bytes())。.gitattributes 声明 `* text=auto eol=lf`，
    但 Windows 工作区里有些 .md 实际存成了 CRLF（写入工具的锅）。于是：
      · 本地（CRLF）哈希 = 7cf97f…，与快照一致 → G9 绿
      · CI / 新克隆（LF）哈希 = 5d0f94…，与快照不一致 → G9 红
    **同一份提交，本地绿、CI 红** —— 而 workflow 注释还写着“本地通过，CI 必通过”。

    修法：哈希基于“归一后的文本内容”（CRLF→LF），而不是字节原样。
    这样换行策略不再影响结论；真内容变了仍然会红。
    注：改动后快照里的 sha 需重生一次（它是派生数据，用 generate 重生，不手改 —— D-85）。
    """
    return hashlib.sha256(path.read_bytes().replace(b"\r\n", b"\n")).hexdigest()


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
            "shares", "shares_date", "shares_basis", "price", "market_cap",
            "tax_rate", "nopat", "invested_capital", "roic_pct")
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
        dest = OUT / (snap["ticker"] + ".json")
        # [D-85] 只改 generated_at 时不重写文件：否则每次 generate 都会
        # 把 20 个已跟踪文件弄脏（与 D-72 同类的工作区污染）。
        if dest.exists():
            try:
                old = json.loads(dest.read_text(encoding="utf-8"))
                a = {k: v for k, v in old.items() if k != "generated_at"}
                b = {k: v for k, v in snap.items() if k != "generated_at"}
                if a == b:
                    print("%-5s %-8s %s（内容未变，跳过）" % (snap["ticker"], snap["status"], dest.relative_to(ROOT)))
                    continue
            except Exception:
                pass
        dest.write_text(json.dumps(snap, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print("%-5s %-8s %s" % (snap["ticker"], snap["status"], dest.relative_to(ROOT)))


def validate():
    problems = []
    degraded = []          # [D-97] 无 SEC facts → 只校验结构/哈希，不重推指标
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
            # [D-97] SEC 原始 facts 被 .gitignore 排除 → CI/新克隆里根本没有。
            # 这时的正确行为不是把整个门禁跳过（那就连下面的哈希校验也一起没了），
            # 而是【逐标的降级】：结构 + 报告哈希照旧校验，只跳过“重新推指标”这一层，并说出来。
            if not (ANALYSIS / "sec" / (ticker.lower() + "_facts.json")).exists():
                print("⏭ %s: 本环境无 SEC facts（analysis/sec/%s_facts.json），"
                      "只校验了结构 + 报告哈希，未重推指标" % (ticker, ticker.lower()))
                degraded.append(ticker)
                continue
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
    if degraded:
        # 这句必须在 PASS 之前 —— 它说明这次 PASS 覆盖了什么、没覆盖什么
        print("⚠ %d 份只校验了结构/哈希（无 facts，未重推指标）：%s"
              % (len(degraded), ", ".join(degraded)))
    print("__SNAPSHOT_PASS__")
    return 0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("command", choices=["generate", "validate"])
    a = ap.parse_args()
    return generate() if a.command == "generate" else validate()


if __name__ == "__main__":
    sys.exit(main() or 0)
