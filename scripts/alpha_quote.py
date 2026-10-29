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


def get_quote(ticker, proxy, offline=False, post=False):
    """post=True 时，若盘后/盘前有成交，则用 fulldayPrice 作为 price，
    并把常规收盘价单独存为 regular_close 以便审计。

    为什么需要这个开关：财报在收盘后发布，常规收盘价已经不是
    「当前可成交价」。此时若仍用 regularMarketPrice，赔率会算错。
    默认关闭 —— 其它标的的既有快照不受影响。
    """
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
        regular = m.get("regularMarketPrice")
        fullday = m.get("fulldayPrice")
        use_post = bool(post) and m.get("hasPrePostMarketData") and fullday
        out.update({
            "price": fullday if use_post else regular,
            "regular_close": regular,
            "price_basis": "post" if use_post else "regular",
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


# ══════════════════════════════════════════════════════════════════
#  [D-68] 一致预期（分析师预测）—— Yahoo quoteSummary 需要 crumb
#  流程：fc.yahoo.com 取 cookie → /v1/test/getcrumb 取 crumb → 带两者请求
#  这是研究级情景的必要输入（规则情景缺的就是这块）
# ══════════════════════════════════════════════════════════════════
def fetch_estimates(ticker, proxy=DEFAULT_PROXY):
    import tempfile
    ck = os.path.join(tempfile.gettempdir(), "yh_ck_%s.txt" % ticker.upper())
    UA2 = UA
    def curl(args):
        cmd = ["curl", "-s", "--max-time", "30", "-A", UA2]
        if proxy:
            cmd += ["-x", proxy]
        cmd += args
        r = subprocess.run(cmd, capture_output=True, text=True,
                           encoding="utf-8", errors="replace")
        return r.stdout
    curl(["-c", ck, "https://fc.yahoo.com", "-o", os.devnull])
    crumb = curl(["-b", ck, "https://query1.finance.yahoo.com/v1/test/getcrumb"]).strip()
    if not crumb or "<" in crumb:
        return None
    url = ("https://query1.finance.yahoo.com/v10/finance/quoteSummary/%s"
           "?modules=earningsTrend,financialData,defaultKeyStatistics&crumb=%s"
           % (ticker.upper(), crumb))
    body = curl(["-b", ck, url])
    try:
        d = json.loads(body)
        r = (d.get("quoteSummary") or {}).get("result")
        return r[0] if r else None
    except Exception:
        return None


def cmd_estimates(a):
    r = fetch_estimates(a.ticker, a.proxy)
    if not r:
        print("✗ 无法取得一致预期（crumb 失效或该公司无覆盖）")
        return 1
    fd = r.get("financialData", {}) or {}
    ks = r.get("defaultKeyStatistics", {}) or {}

    def g(d_, k):
        v = d_.get(k)
        if isinstance(v, dict):
            return v.get("fmt") or v.get("raw")
        return v

    out = {"ticker": a.ticker.upper(),
           "target_mean": g(fd, "targetMeanPrice"), "target_high": g(fd, "targetHighPrice"),
           "target_low": g(fd, "targetLowPrice"), "target_median": g(fd, "targetMedianPrice"),
           "n_analysts": g(fd, "numberOfAnalystOpinions"),
           "recommendation": g(fd, "recommendationKey"),
           "current_price": g(fd, "currentPrice"),
           "revenue_growth": g(fd, "revenueGrowth"),
           "gross_margin": g(fd, "grossMargins"),
           "operating_margin": g(fd, "operatingMargins"),
           "return_on_equity": g(fd, "returnOnEquity"),
           "total_debt": g(fd, "totalDebt"), "total_cash": g(fd, "totalCash"),
           "forward_pe": g(ks, "forwardPE"), "trailing_pe": None,
           "trend": []}
    for t in (r.get("earningsTrend", {}) or {}).get("trend", []) or []:
        ee = (t.get("earningsEstimate") or {})
        re_ = (t.get("revenueEstimate") or {})
        out["trend"].append({
            "period": t.get("period"), "endDate": t.get("endDate"),
            "eps_avg": (ee.get("avg") or {}).get("raw"),
            "eps_low": (ee.get("low") or {}).get("raw"),
            "eps_high": (ee.get("high") or {}).get("raw"),
            "rev_avg": (re_.get("avg") or {}).get("raw"),
            "n": (ee.get("numberOfAnalysts") if isinstance(ee.get("numberOfAnalysts"), int)
                          else (ee.get("numberOfAnalysts") or {}).get("raw"))
             or (re_.get("numberOfAnalysts") if isinstance(re_.get("numberOfAnalysts"), int)
                 else (re_.get("numberOfAnalysts") or {}).get("raw")),
        })
    if a.json:
        print(json.dumps(out, ensure_ascii=False, indent=1))
        return 0
    print("%s 一致预期" % out["ticker"])
    print("  目标价      %s（区间 %s – %s，%s 位分析师，%s）"
          % (out["target_mean"], out["target_low"], out["target_high"],
             out["n_analysts"], out["recommendation"]))
    cp = out["current_price"]
    try:
        print("  现价        %s → 上行 %+.1f%%" % (cp, (out["target_mean"] / cp - 1) * 100))
    except Exception:
        pass
    print("  前瞻 PE     %s　｜　预期收入增速 %s" % (out["forward_pe"], out["revenue_growth"]))
    print("  %-8s %-12s %-14s %-14s %s" % ("期间", "截止", "EPS 均值", "收入均值", "家数"))
    for t in out["trend"]:
        print("  %-8s %-12s %-14s %-14s %s" % (
            t["period"], t["endDate"],
            ("%.2f" % t["eps_avg"]) if t["eps_avg"] else "—",
            ("%.1fB" % (t["rev_avg"] / 1e9)) if t["rev_avg"] else "—", t["n"]))
    return 0


def main():
    ap = argparse.ArgumentParser(description="行情快照（yfinance 备选源）")
    ap.add_argument("ticker")
    ap.add_argument("--proxy", default=DEFAULT_PROXY)
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--offline", action="store_true")
    ap.add_argument("--estimates", action="store_true",
                    help="[D-68] 取分析师一致预期（目标价 / EPS / 收入预测）")
    ap.add_argument("--post", action="store_true",
                    help="用盘后/盘前成交价作为现价（财报盘后发布时用）")
    a = ap.parse_args()

    if a.estimates:
        return cmd_estimates(a)

    q, src = get_quote(a.ticker, a.proxy, a.offline, a.post)
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
    if q.get("price_basis") == "post":
        print("  口径        盘后价（常规收盘 %s）" % q.get("regular_close"))
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