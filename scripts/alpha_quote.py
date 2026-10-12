#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""[D-29] 行情与估值快照 —— yfinance 的备选源

问题：`stock-analysis` skill 依赖 yfinance，实测已 429 限流：
    py stock_info.py APH → ❌ Too Many Requests
Alpha Radar 全流程都要用价格（决策回报、赔率、估值分位），不能只有单一来源。

本脚本的取值链（按顺序尝试，第一个成功即返回）：
    1. Yahoo Finance chart/quoteSummary  直连
    2. 同路径 走本地代理（ALPHA_PROXY，默认 http://127.0.0.1:7897）
说明：本机环境下直连 Yahoo 返回 000（不可达），走代理才能通。
      代理端口可用环境变量覆盖：ALPHA_PROXY=http://127.0.0.1:7897

用法:
    py scripts/alpha_quote.py APH
    py scripts/alpha_quote.py APH --json
    py scripts/alpha_quote.py APH --proxy http://127.0.0.1:7897
    py scripts/alpha_quote.py APH --offline    # 只用缓存

缓存: data/quotes/<TICKER>.json（当天有效）
"""
import argparse
import datetime as dt
import json
import os
import subprocess
import sys

try:
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
except Exception:
    pass

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
QDIR = os.path.join(ROOT, "data", "quotes")
DEFAULT_PROXY = os.environ.get("ALPHA_PROXY", "http://127.0.0.1:7897")
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36")


def fetch_json(url, proxy=None, timeout=25):
    cmd = ["curl", "-s", "--max-time", str(timeout), "-A", UA]
    if proxy:
        cmd += ["-x", proxy]
    cmd.append(url)
    try:
        p = subprocess.run(cmd, capture_output=True, text=True,
                           encoding="utf-8", errors="replace")
        if p.returncode != 0 or not (p.stdout or "").strip():
            return None
        return json.loads(p.stdout)
    except Exception:
        return None


def get_quote(ticker, proxy, offline=False):
    t = ticker.upper()
    cache = os.path.join(QDIR, "%s.json" % t)
    if offline:
        if os.path.exists(cache):
            return json.load(open(cache, encoding="utf-8")), "cache(offline)"
        return None, "offline 且无缓存"

    chart = ("https://query1.finance.yahoo.com/v8/finance/chart/%s"
             "?range=1y&interval=1d" % t)
    js = fetch_json(chart) or fetch_json(chart, proxy)
    src = "yahoo直连" if js else None
    if not js:
        js = fetch_json(chart, proxy)
        src = "yahoo代理" if js else None
    if not js:
        qs = ("https://query1.finance.yahoo.com/v10/finance/quoteSummary/%s"
              "?modules=price,defaultKeyStatistics,financialData" % t)
        js2 = fetch_json(qs) or fetch_json(qs, proxy)
        if js2:
            js, src = js2, (src or "yahoo代理")
    if not js:
        if os.path.exists(cache):
            return json.load(open(cache, encoding="utf-8")), "cache(回退)"
        return None, "全部来源失败"

    out = {"ticker": t, "fetched_at": dt.datetime.now().isoformat(timespec="seconds"),
           "source": src, "raw": js}
    r = (js.get("chart") or {}).get("result")
    if r:
        m = r[0].get("meta", {})
        closes = [c for c in ((r[0].get("indicators") or {}).get("quote") or [{}])[0].get("close", []) if c]
        out.update({
            "price": m.get("regularMarketPrice"),
            "prev_close": m.get("chartPreviousClose") or m.get("previousClose"),
            "currency": m.get("currency"),
            "exchange": m.get("fullExchangeName"),
            "market_time": dt.datetime.fromtimestamp(m.get("regularMarketTime", 0)).isoformat()
            if m.get("regularMarketTime") else None,
            "week52_high": m.get("fiftyTwoWeekHigh"),
            "week52_low": m.get("fiftyTwoWeekLow"),
            "price_1y_low": min(closes) if closes else None,
            "price_1y_high": max(closes) if closes else None,
        })
    os.makedirs(QDIR, exist_ok=True)
    with open(cache, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=1)
    return out, src


def main():
    ap = argparse.ArgumentParser(description="行情快照（yfinance 备选源）")
    ap.add_argument("ticker")
    ap.add_argument("--proxy", default=DEFAULT_PROXY)
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--offline", action="store_true")
    a = ap.parse_args()

    q, src = get_quote(a.ticker, a.proxy, a.offline)
    if not q:
        print("✗ 无法取得行情：%s" % src)
        print("  提示: 本机直连 Yahoo 不可达，需要本地代理。")
        print("        ALPHA_PROXY=http://127.0.0.1:7897 py scripts/alpha_quote.py %s" % a.ticker)
        return 1

    if a.json:
        print(json.dumps(q, ensure_ascii=False, indent=1))
        return 0

    p = q.get("price")
    print("%s  %s" % (q["ticker"], q.get("exchange") or ""))
    print("  价格        %s %s" % (p, q.get("currency") or ""))
    print("  前收        %s" % q.get("prev_close"))
    print("  行情时间    %s" % q.get("market_time"))
    print("  52周区间    %s – %s" % (q.get("week52_low"), q.get("week52_high")))
    if q.get("price_1y_high") and q.get("price_1y_low"):
        hi, lo = q["price_1y_high"], q["price_1y_low"]
        pct = (p - lo) / (hi - lo) * 100 if hi > lo else None
        print("  1年区间     %.2f – %.2f" % (lo, hi))
        if pct is not None:
            print("  位置        第 %.0f 分位（用于估值分位）" % pct)
    print("  数据源      %s" % src)
    print("  抓取时间    %s" % q["fetched_at"])
    return 0


if __name__ == "__main__":
    sys.exit(main())