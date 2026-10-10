#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""[D-14] SEC 一手数据自动取数

之前 skill 说"取一手数据"，但没有任何命令 —— 这是每次分析都要走的路，却最费人工。

实测已确认可用（无需代理）：
    https://www.sec.gov/files/company_tickers.json          200, 10434 家 ticker→CIK
    https://data.sec.gov/api/xbrl/companyfacts/CIK##########.json   200
    https://data.sec.gov/submissions/CIK##########.json     200

用法:
    py scripts/alpha_fetch.py APH                 # ticker → CIK → companyfacts → extract
    py scripts/alpha_fetch.py --cik 820313
    py scripts/alpha_fetch.py APH --no-extract    # 只下载，不跑提取
    py scripts/alpha_fetch.py APH --force         # 忽略缓存重新下载

产物:
    analysis/sec/company_tickers.json       （缓存，24h）
    analysis/sec/<ticker>_facts.json        （SEC companyfacts 原始 JSON）
    analysis/sec/<ticker>.txt               （extract2.py 提取的结构化序列）
"""
import argparse
import datetime as dt
import json
import os
import subprocess
import sys
import urllib.request

try:
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
except Exception:
    pass

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SEC_DIR = os.path.join(ROOT, "analysis", "sec")
TICKERS = os.path.join(SEC_DIR, "company_tickers.json")
TTL_HOURS = 24

# SEC 要求带可联系身份的 User-Agent，否则可能被限流/拒绝
UA = os.environ.get("ALPHA_SEC_UA", "alpha-radar research (contact: local-user@example.com)")


def log(msg):
    print("  " + msg)


def fetch(url, dest, force=False, ttl_hours=TTL_HOURS):
    """带 TTL 缓存的下载。返回 (path, from_cache)"""
    if os.path.exists(dest) and not force:
        age = (dt.datetime.now().timestamp() - os.path.getmtime(dest)) / 3600.0
        if age < ttl_hours:
            return dest, True
    # 不请求 gzip：urllib 不会自动解压，会把 gzip 字节直接写进缓存文件
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            raw = r.read()
    except Exception as e:
        raise RuntimeError("下载失败 %s: %s" % (url, e))
    # 防御：万一服务端仍然返回 gzip，就地解压
    if raw[:2] == b"\x1f\x8b":
        import gzip
        raw = gzip.decompress(raw)
    if not raw.lstrip()[:1] in (b"{", b"["):
        raise RuntimeError("返回内容不是 JSON（前 80 字节: %r）" % raw[:80])
    with open(dest, "wb") as f:
        f.write(raw)
    return dest, False


def resolve_cik(ticker, force=False):
    path, cached = fetch("https://www.sec.gov/files/company_tickers.json", TICKERS, force)
    data = json.load(open(path, encoding="utf-8"))
    t = ticker.upper()
    for v in data.values():
        if v.get("ticker", "").upper() == t:
            return int(v["cik_str"]), v.get("title", ""), cached
    return None, None, cached


def pad(cik):
    return "CIK%010d" % cik


def main():
    p = argparse.ArgumentParser(description="SEC 一手数据取数")
    p.add_argument("ticker", nargs="?", help="股票代码，如 APH")
    p.add_argument("--cik", type=int, help="直接给 CIK（跳过 ticker 映射）")
    p.add_argument("--force", action="store_true", help="忽略缓存")
    p.add_argument("--no-extract", action="store_true", help="只下载，不跑 extract2.py")
    p.add_argument("--submissions", action="store_true", help="同时取 submissions（近期申报清单）")
    a = p.parse_args()

    os.makedirs(SEC_DIR, exist_ok=True)

    cik, title = a.cik, ""
    if cik:
        tag = "cik%d" % cik
    else:
        if not a.ticker:
            p.error("需要 ticker 或 --cik")
        cik, title, cached = resolve_cik(a.ticker, a.force)
        if cik is None:
            log("✗ 在 SEC company_tickers.json 中找不到 ticker '%s'" % a.ticker)
            log("  提示: 只有在美国 SEC 注册申报的公司才在此表中（港股/A股不在）")
            return 1
        tag = a.ticker.lower()
        log("ticker %s → CIK %010d  %s%s" % (a.ticker.upper(), cik, title,
                                             "  (tickers 表命中缓存)" if cached else ""))

    facts_path = os.path.join(SEC_DIR, "%s_facts.json" % tag)
    url = "https://data.sec.gov/api/xbrl/companyfacts/%s.json" % pad(cik)
    try:
        path, cached = fetch(url, facts_path, a.force)
    except RuntimeError as e:
        log("✗ %s" % e)
        return 1
    size = os.path.getsize(path) / 1e6
    log("companyfacts: %s (%.1f MB)%s" % (os.path.relpath(path, ROOT), size,
                                          "  [缓存]" if cached else "  [新下载]"))

    try:
        d = json.load(open(path, encoding="utf-8"))
        n = len(d.get("facts", {}).get("us-gaap", {}))
        log("entity=%s  us-gaap tag 数=%d  最后更新=%s"
            % (d.get("entityName"), n, max(
                (it.get("filed", "") for tax in d.get("facts", {}).values()
                 for t in tax.values() for u in t.get("units", {}).values() for it in u),
                default="?")))
    except Exception as e:
        log("⚠ 解析 companyfacts 时异常: %s" % e)

    if a.submissions:
        sp = os.path.join(SEC_DIR, "%s_submissions.json" % tag)
        try:
            fetch("https://data.sec.gov/submissions/%s.json" % pad(cik), sp, a.force)
            log("submissions: %s" % os.path.relpath(sp, ROOT))
        except RuntimeError as e:
            log("⚠ submissions 下载失败: %s" % e)

    if not a.no_extract:
        ex = os.path.join(SEC_DIR, "extract2.py")
        if not os.path.exists(ex):
            log("⚠ 找不到 extract2.py，跳过提取")
        else:
            out = os.path.join(SEC_DIR, "%s.txt" % tag)
            with open(out, "w", encoding="utf-8") as f:
                r = subprocess.run([sys.executable, ex, path],
                                   stdout=f, stderr=subprocess.PIPE,
                                   encoding="utf-8", errors="replace")
            if r.returncode == 0:
                log("提取完成: %s (%d 行)" % (os.path.relpath(out, ROOT),
                                              len(open(out, encoding="utf-8").readlines())))
            else:
                log("⚠ extract2.py 返回 %d: %s" % (r.returncode, (r.stderr or "")[-300:]))

    log("")
    log("下一步: 读 %s，与 10-K/10-Q 原文交叉验证后再写进 Alpha Radar 档案"
        % os.path.relpath(os.path.join(SEC_DIR, "%s.txt" % tag), ROOT))
    return 0


if __name__ == "__main__":
    sys.exit(main())