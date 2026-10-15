#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Archive SEC filings for tickers already present in Alpha Radar.

The archive is append-only by accession number. Raw filing files stay local;
filing metadata is written to data/filing_archive.jsonl for audit and review.

Examples:
    py scripts/alpha_archive.py --once
    py scripts/alpha_archive.py --ticker NVDA --forms 10-K,10-Q,8-K
    py scripts/alpha_archive.py --ticker NVDA --since 2026-01-01
"""
import argparse
import datetime as dt
import hashlib
import json
import os
import re
import sys
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SEC_DIR = os.path.join(ROOT, "analysis", "sec")
ARCHIVE_DIR = os.path.join(SEC_DIR, "archive")
INDEX = os.path.join(ROOT, "data", "filing_archive.jsonl")
UA = os.environ.get("ALPHA_SEC_UA", "alpha-radar research (contact: local-user@example.com)")
DEFAULT_FORMS = {"10-K", "10-K/A", "10-Q", "10-Q/A", "8-K"}


def die(msg):
    print("✗ " + msg, file=sys.stderr)
    return 1


def sec_get(url):
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept-Encoding": "gzip, deflate"})
    with urllib.request.urlopen(req, timeout=60) as response:
        raw = response.read()
    if raw[:2] == b"\x1f\x8b":
        import gzip
        raw = gzip.decompress(raw)
    return raw


def load_json(path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def resolve_tickers():
    tickers = set()
    snap_dir = os.path.join(ROOT, "data", "research_snapshots")
    if os.path.isdir(snap_dir):
        tickers.update(os.path.basename(p)[:-5].upper()
                       for p in os.listdir(snap_dir) if p.endswith(".json"))
    analysis_dir = os.path.join(ROOT, "analysis")
    if os.path.isdir(analysis_dir):
        tickers.update(re.match(r"^([A-Za-z0-9.-]+)_AlphaRadar\.md$", p).group(1).upper()
                       for p in os.listdir(analysis_dir)
                       if re.match(r"^[A-Za-z0-9.-]+_AlphaRadar\.md$", p))
    return sorted(tickers)


def load_index():
    rows = []
    if not os.path.exists(INDEX):
        return rows
    with open(INDEX, encoding="utf-8") as f:
        for line_no, line in enumerate(f, 1):
            if not line.strip():
                continue
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError as exc:
                raise RuntimeError("filing_archive.jsonl 第 %d 行无法解析: %s" % (line_no, exc))
    return rows


def append_index(row):
    os.makedirs(os.path.dirname(INDEX), exist_ok=True)
    with open(INDEX, "a", encoding="utf-8", newline="\n") as f:
        f.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")


def sha256(data):
    return hashlib.sha256(data).hexdigest()


def archive_one(ticker, cik, filing, force=False):
    accession = filing["accessionNumber"]
    acc_dir = os.path.join(ARCHIVE_DIR, ticker, accession)
    os.makedirs(acc_dir, exist_ok=True)
    acc_path = accession.replace("-", "")
    primary = filing.get("primaryDocument") or (accession + ".txt")
    base = "https://www.sec.gov/Archives/edgar/data/%s/%s" % (int(cik), acc_path)
    files = {
        "filing_txt": (base + "/%s.txt" % acc_path, os.path.join(acc_dir, "%s.txt" % acc_path)),
        "primary_document": (base + "/" + primary, os.path.join(acc_dir, primary)),
        "index_json": (base + "/index.json", os.path.join(acc_dir, "index.json")),
    }
    saved = {}
    for kind, (url, dest) in files.items():
        if os.path.exists(dest) and not force:
            raw = open(dest, "rb").read()
        else:
            raw = sec_get(url)
            tmp = dest + ".tmp"
            with open(tmp, "wb") as f:
                f.write(raw)
            os.replace(tmp, dest)
        saved[kind] = {"path": os.path.relpath(dest, ROOT).replace("\\", "/"),
                       "bytes": len(raw), "sha256": sha256(raw), "url": url}
    return saved


def recent_filings(submissions):
    recent = submissions.get("filings", {}).get("recent", {}) or {}
    keys = list(recent.keys())
    n = len(recent.get("accessionNumber", []))
    for i in range(n):
        yield {k: recent.get(k, [None] * n)[i] for k in keys}


def archive_ticker(ticker, forms, since, known, force=False):
    from alpha_fetch import resolve_cik
    cik, title, _ = resolve_cik(ticker, force=False)
    if cik is None:
        return 0, 1, "SEC 未找到 ticker"
    url = "https://data.sec.gov/submissions/CIK%010d.json" % cik
    submissions = json.loads(sec_get(url).decode("utf-8"))
    count, warnings = 0, 0
    rows = [f for f in recent_filings(submissions)
            if f.get("form") in forms and (not since or (f.get("filingDate") or "") >= since)]
    rows.sort(key=lambda f: (f.get("filingDate") or "", f.get("accessionNumber") or ""))
    print("%s %s: 发现 %d 份目标申报" % (ticker, title, len(rows)))
    for filing in rows:
        accession = filing.get("accessionNumber")
        if not accession:
            continue
        key = (ticker, accession)
        if key in known:
            if force:
                try:
                    archive_one(ticker, cik, filing, force=True)
                    print("  ↻ %s %s %s（已刷新文件，索引不重复追加）" %
                          (filing.get("form"), filing.get("filingDate"), accession))
                except Exception as exc:
                    warnings += 1
                    print("  ⚠ %s %s 刷新失败: %s" % (ticker, accession, exc))
            continue
        try:
            artifacts = archive_one(ticker, cik, filing, force=force)
            row = {
                "record_type": "sec_filing",
                "ticker": ticker,
                "cik": int(cik),
                "accession_number": accession,
                "form": filing.get("form"),
                "filing_date": filing.get("filingDate"),
                "report_date": filing.get("reportDate"),
                "acceptance_datetime": filing.get("acceptanceDateTime"),
                "primary_document": filing.get("primaryDocument"),
                "company_name": title,
                "source": "SEC EDGAR",
                "artifacts": artifacts,
                "archived_at": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
            }
            append_index(row)
            known.add(key)
            count += 1
            print("  ✓ %s %s %s" % (filing.get("form"), filing.get("filingDate"), accession))
        except Exception as exc:
            warnings += 1
            print("  ⚠ %s %s 归档失败: %s" % (ticker, accession, exc))
    return count, warnings, None


def main():
    p = argparse.ArgumentParser(description="归档已分析标的的 SEC 财报原文")
    p.add_argument("--ticker", action="append", help="只处理指定 ticker，可重复")
    p.add_argument("--forms", default=",".join(sorted(DEFAULT_FORMS)), help="逗号分隔的 SEC 表单")
    p.add_argument("--since", help="只归档该日期之后的申报，格式 YYYY-MM-DD")
    p.add_argument("--force", action="store_true", help="重新下载已归档文件，但不追加重复索引")
    p.add_argument("--once", action="store_true", help="显式执行一次；默认行为也只执行一次")
    a = p.parse_args()
    try:
        forms = {x.strip().upper() for x in a.forms.split(",") if x.strip()}
        if not forms:
            return die("至少指定一个 SEC 表单")
        if a.since and not re.match(r"^\d{4}-\d{2}-\d{2}$", a.since):
            return die("--since 必须是 YYYY-MM-DD")
        tickers = sorted({x.upper() for x in (a.ticker or resolve_tickers())})
        known = {(r.get("ticker"), r.get("accession_number")) for r in load_index()
                 if r.get("record_type") == "sec_filing"}
        total = warnings = 0
        for ticker in tickers:
            try:
                n, w, err = archive_ticker(ticker, forms, a.since, known, a.force)
                total += n; warnings += w
                if err:
                    print("  ⚠ %s: %s" % (ticker, err))
                    warnings += 1
            except Exception as exc:
                print("  ⚠ %s: 检测失败: %s" % (ticker, exc))
                warnings += 1
        print("归档完成：新增 %d 份，警告 %d，索引 %s" % (total, warnings, os.path.relpath(INDEX, ROOT)))
        return 0 if not warnings else 2
    except Exception as exc:
        return die(str(exc))


if __name__ == "__main__":
    sys.path.insert(0, os.path.dirname(__file__))
    sys.exit(main())
