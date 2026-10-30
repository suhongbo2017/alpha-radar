#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""[D-13] 持仓与组合雷达（Radar Board）

设计原则（与账本一致）：
  · **交易 append-only** —— 买卖只追加，不改写
  · **持仓是派生状态** —— 从交易流计算得出，不手工维护
  · **分析结论是数据，不是散文** —— 存 data/analyses.jsonl，供跨公司比较

三个数据文件：
  data/analyses.jsonl      每次 Alpha Radar 分析的结论（append-only，新日期=新记录）
  data/transactions.jsonl  买卖交易（append-only）
  data/portfolio.json      现金与其他组合设置（当前状态）

命令:
  py scripts/alpha_portfolio.py analysis --ticker APH --score 84.6 --lifecycle "2.5→3" \
      --roic 19.2 --wacc 10.4 --net-debt-ebitda 1.46 --odds 0.92 \
      --weighted 125.2 --bear 46 --action Watch --price 87.24 --prob 0.45
  py scripts/alpha_portfolio.py buy  --ticker MSFT --shares 10 --price 500 --date 2026-03-01
  py scripts/alpha_portfolio.py sell --ticker MSFT --shares 4  --price 560 --date 2026-09-01
  py scripts/alpha_portfolio.py cash --amount 25000
  py scripts/alpha_portfolio.py holdings
  py scripts/alpha_portfolio.py board          # 组合雷达（分析 + 持仓 + 一致性）
  py scripts/alpha_portfolio.py check          # 只列冲突
"""
import argparse
import datetime as dt
import json
import os
import sys

try:
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
except Exception:
    pass

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(ROOT, "data")
ANALYSES = os.path.join(DATA, "analyses.jsonl")
TXNS = os.path.join(DATA, "transactions.jsonl")
PORTF = os.path.join(DATA, "portfolio.json")
QUOTES = os.path.join(DATA, "quotes")
# [D-73] 持仓数据分两级敏感度：
#   holdings.json —— **只存标的**，可入库、可公开。用于"持有/未持有"与冲突判定。
#   positions.json —— 含数量/成本/盈亏，**仅本地**（gitignored）。仅用于仓位%/盈亏显示。
SNAPSHOT = os.path.join(DATA, "positions.json")
HOLDINGS = os.path.join(DATA, "holdings.json")


def load_holdings_tickers():
    """只含标的的持仓清单（可公开）"""
    if not os.path.exists(HOLDINGS):
        return set(), None
    try:
        d = json.load(open(HOLDINGS, encoding="utf-8"))
        return {str(t).upper() for t in d.get("tickers", [])}, d.get("as_of")
    except Exception:
        return set(), None

# 建仓类动作（与分析结论比对时用）
ENTRY_ACTIONS = {"Buy", "StrongBuy", "Core", "Starter"}
HOLD_ACTIONS = {"Hold", "Core", "Buy", "StrongBuy", "Starter"}
EXIT_ACTIONS = {"Trim", "Exit", "Watch"}


def die(m):
    print("✗ " + m)
    sys.exit(2)


def load(path):
    if not os.path.exists(path):
        return []
    out = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                out.append(json.loads(line))
    return out


def append(path, rec):
    os.makedirs(DATA, exist_ok=True)
    with open(path, "a", encoding="utf-8") as f:
        f.write(json.dumps(rec, ensure_ascii=False) + "\n")


def save_portf(d):
    os.makedirs(DATA, exist_ok=True)
    with open(PORTF, "w", encoding="utf-8") as f:
        json.dump(d, f, ensure_ascii=False, indent=1)


def load_portf():
    if os.path.exists(PORTF):
        return json.load(open(PORTF, encoding="utf-8"))
    return {"base_currency": "USD", "cash": 0.0}


def latest_price(ticker):
    p = os.path.join(QUOTES, "%s.json" % ticker.upper())
    if os.path.exists(p):
        try:
            d = json.load(open(p, encoding="utf-8"))
            return d.get("price"), d.get("market_time") or d.get("fetched_at")
        except Exception:
            pass
    return None, None


def fmt(x, unit=""):
    if x is None:
        return "—"
    a = abs(x)
    if a >= 1e12:
        s = "%.2fT" % (x / 1e12)
    elif a >= 1e9:
        s = "%.2fB" % (x / 1e9)
    elif a >= 1e6:
        s = "%.2fM" % (x / 1e6)
    elif a >= 1e3:
        s = "%,.0f".replace(",", "") % x
    else:
        s = "%.2f" % x
    return (s + unit) if unit else s


# ══════════════════════════════════════════════════════════
#  持仓派生（平均成本法）
# ══════════════════════════════════════════════════════════
def load_snapshot():
    """券商快照（alpha_portfolio.py sync 或手工写入）"""
    if not os.path.exists(SNAPSHOT):
        return None
    try:
        d = json.load(open(SNAPSHOT, encoding="utf-8"))
    except Exception:
        return None
    out = {}
    for p_ in d.get("positions", []):
        if not p_.get("qty"):
            continue
        code = str(p_.get("code", "")).upper()
        tick = code.split(".")[-1] if "." in code else code
        out[tick] = {
            "shares": float(p_["qty"]),
            "avg_cost": float(p_.get("avg_cost") or 0),
            "cost": float(p_.get("cost_basis") or (p_.get("avg_cost", 0) * p_.get("qty", 0))),
            "realized": float(p_.get("realized_pnl") or 0),
            "last": p_.get("last"), "name": p_.get("name"),
            "last_pnl": float(p_.get("unrealized_pnl") or 0),
            "source": d.get("source", "snapshot"),
            "snapshot_date": d.get("quote_date") or d.get("fetched_at"),
        }
    flat = {}
    for p_ in d.get("positions", []):
        if p_.get("qty"):
            continue
        code = str(p_.get("code", "")).upper()
        flat[code.split(".")[-1] if "." in code else code] = float(p_.get("realized_pnl") or 0)
    return {"holdings": out, "flat": flat, "totals": d.get("totals", {}),
            "date": d.get("quote_date") or d.get("fetched_at"), "raw": d}


def derive_holdings():
    """[D-13/D-73] 持仓来源优先级：本地全量快照 > 只含标的的清单 > 手工交易流

    分级敏感度：
      positions.json（本地，含数量）→ 给出 shares/avg_cost/last_pnl
      holdings.json（可公开，仅标的）→ 只标记"持有"，数量相关字段为 None
    """
    snap = load_snapshot()
    if snap and snap["holdings"]:
        return snap["holdings"], [], snap
    tickers, asof = load_holdings_tickers()
    if tickers:
        return {t: {"shares": None, "avg_cost": None, "cost": None, "realized": None,
                    "last": None, "name": None, "last_pnl": None,
                    "source": "holdings.json（仅标的）", "snapshot_date": asof}
                for t in sorted(tickers)}, [], None
    txns = sorted(load(TXNS), key=lambda r: (r["ticker"], r["date"], r.get("logged_at", "")))
    pos = {}
    for t in txns:
        k = t["ticker"].upper()
        p = pos.setdefault(k, {"shares": 0.0, "cost": 0.0, "realized": 0.0,
                               "fees": 0.0, "first": t["date"], "last": t["date"]})
        p["fees"] += float(t.get("fee", 0) or 0)
        if t["action"] == "buy":
            p["cost"] += t["shares"] * t["price"]
            p["shares"] += t["shares"]
        else:
            if t["shares"] > p["shares"] + 1e-9:
                print("  ⚠ %s 卖出 %.4f 股超过持有 %.4f 股（忽略超额部分）"
                      % (k, t["shares"], p["shares"]))
                t = dict(t, shares=p["shares"])
            avg = (p["cost"] / p["shares"]) if p["shares"] else 0.0
            p["realized"] += t["shares"] * (t["price"] - avg)
            p["cost"] -= t["shares"] * avg
            p["shares"] -= t["shares"]
        p["last"] = t["date"]
    out = {}
    for k, p in pos.items():
        if p["shares"] > 1e-9:
            p["avg_cost"] = p["cost"] / p["shares"]
            out[k] = p
    return out, txns, None


def build_rows():
    """合并：分析结论 + 持仓 + 行情"""
    holds, txns, snap = derive_holdings()
    # 最新一条分析（按 ticker）
    latest = {}
    for a in sorted(load(ANALYSES), key=lambda r: (r["ticker"], r.get("analysis_date", ""))):
        latest[a["ticker"].upper()] = a
    tickers = sorted(set(holds) | set(latest))
    rows = []
    for t in tickers:
        h, a = holds.get(t), latest.get(t)
        px, px_time = latest_price(t)
        # 价格优先级：自取行情 > 券商快照的 last > 成本价（最后兜底）
        if px is None and h and h.get("last"):
            px, px_time = h["last"], h.get("snapshot_date")
        # [D-73] shares 可能为 None（只有标的清单时）→ 市值不可算，降级为 None
        mv = None
        if h and h.get("shares") and px:
            mv = h["shares"] * px
        elif h and h.get("shares") and h.get("avg_cost"):
            mv = h["shares"] * h["avg_cost"]
        rows.append({"ticker": t, "hold": h, "analysis": a, "price": px,
                     "price_time": px_time, "market_value": mv})
    return rows, load_portf(), snap


def cmd_buy(a):
    if a.shares <= 0 or a.price <= 0:
        die("shares / price 必须为正")
    rec = {"record_type": "txn", "ticker": a.ticker.upper(), "action": "buy",
           "date": a.date or dt.date.today().isoformat(), "shares": a.shares,
           "price": a.price, "fee": a.fee or 0, "currency": a.currency,
           "note": a.note or "", "logged_at": dt.datetime.now().isoformat(timespec="seconds")}
    append(TXNS, rec)
    print("✓ 买入已记录：%s %.4f 股 @ %.4f（%s）"
          % (rec["ticker"], rec["shares"], rec["price"], rec["date"]))
    print("  ⤷ 注意：交易是 append-only 事实，改错请记一笔反向交易（不要改文件）")
    return 0


def cmd_sell(a):
    if a.shares <= 0 or a.price <= 0:
        die("shares / price 必须为正")
    holds, _, _snap = derive_holdings()
    h = holds.get(a.ticker.upper())
    if not h:
        die("没有 %s 的持仓" % a.ticker.upper())
    if a.shares > h["shares"] + 1e-9:
        die("卖出 %.4f 股超过持有 %.4f 股" % (a.shares, h["shares"]))
    avg = h["avg_cost"]
    rec = {"record_type": "txn", "ticker": a.ticker.upper(), "action": "sell",
           "date": a.date or dt.date.today().isoformat(), "shares": a.shares,
           "price": a.price, "fee": a.fee or 0, "currency": a.currency,
           "note": a.note or "", "logged_at": dt.datetime.now().isoformat(timespec="seconds")}
    append(TXNS, rec)
    print("✓ 卖出已记录：%s %.4f 股 @ %.4f（成本 %.4f，本次实现盈亏 %+.2f）"
          % (rec["ticker"], rec["shares"], rec["price"], avg, a.shares * (a.price - avg)))
    return 0


def cmd_cash(a):
    p = load_portf()
    p["cash"] = a.amount
    p["cash_updated"] = dt.date.today().isoformat()
    save_portf(p)
    print("✓ 现金余额 = %s %s" % (fmt(a.amount), p.get("base_currency", "USD")))
    return 0


def cmd_analysis(a):
    # [2C] 赔率必须显式声明口径。否则总览会把「规则引擎按市值+增速+杠杆算出的数」
    # 与「人工 bottom-up 研判的数」排在同一个序里 —— 实测 MSFT 两者相差 6.2 倍
    # （记录 4.49 vs 引擎 0.72）。这是 D-43 的复发形态。
    if a.odds is not None and a.odds < 0:
        die("--odds 不能为负")
    rec = {"record_type": "analysis", "ticker": a.ticker.upper(),
           "analysis_date": a.date or dt.date.today().isoformat(),
           "price": a.price, "fundamental_score": a.score, "lifecycle": a.lifecycle,
           "roic": a.roic, "wacc": a.wacc, "net_debt_ebitda": a.net_debt_ebitda,
           "odds": a.odds, "odds_basis": a.odds_basis,
           "weighted_value": a.weighted, "bear_value": a.bear,
           "action": a.action, "moat": a.moat,
           "dossier": a.dossier or "analysis/%s_AlphaRadar.md" % a.ticker.upper(),
           "logged_at": dt.datetime.now().isoformat(timespec="seconds")}
    append(ANALYSES, rec)
    print("✓ 分析结论已记录：%s %s score=%s odds=%s action=%s"
          % (rec["ticker"], rec["analysis_date"], a.score, a.odds, a.action))
    return 0


def _verdict(hold, ana):
    """持仓 vs 分析结论的一致性判定"""
    if not ana:
        return "❓", "无分析档案"
    act = ana.get("action")
    odds = ana.get("odds")
    if hold:
        if odds is not None and odds < 1 and act in EXIT_ACTIONS:
            return "🔴", "持有中，但赔率 %.2f<1 且分析为 %s" % (odds, act)
        if act in HOLD_ACTIONS and (odds is None or odds >= 1):
            return "✅", "一致（%s / 赔率 %s）" % (act, ("%.2f" % odds) if odds else "—")
        return "🟡", "持有中，分析为 %s（赔率 %s）" % (act, ("%.2f" % odds) if odds else "—")
    else:
        if act in ENTRY_ACTIONS and (odds is not None and odds >= 1):
            return "💡", "未持有，但赔率 %.2f≥1 且分析为 %s" % (odds, act)
        if odds is not None and odds < 1:
            return "⚪", "未持有，赔率 %.2f<1" % odds
        return "⚪", "未持有（%s）" % (act or "—")


def cmd_sync(a):
    """[D-13] 从券商 API 拉取持仓

    认证：HTTP Basic Auth（realm "futu-tracker"）
    凭据来源（优先级）：命令行 → 环境变量 FUTU_API_USER / FUTU_API_PASS → data/.futu_auth
    **凭据一律不写入仓库**（data/.futu_auth 已在 .gitignore）
    """
    import base64
    import subprocess
    u = a.user or os.environ.get("FUTU_API_USER")
    p = a.password or os.environ.get("FUTU_API_PASS")
    authfile = os.path.join(DATA, ".futu_auth")
    if (not u or not p) and os.path.exists(authfile):
        try:
            d = json.load(open(authfile, encoding="utf-8"))
            u, p = d.get("user"), d.get("password")
        except Exception:
            pass
    if not u or not p:
        print("✗ 缺少凭据。三种提供方式（任选其一）：")
        print("   1) 环境变量： FUTU_API_USER=xxx FUTU_API_PASS=yyy py scripts/alpha_portfolio.py sync")
        print("   2) 命令行：   py scripts/alpha_portfolio.py sync --user xxx --password yyy")
        print("   3) 本地文件： %s  内容 {\"user\":\"xxx\",\"password\":\"yyy\"}" % authfile)
        print("   （该文件已在 .gitignore 中，不会进版本库）")
        return 2

    token = base64.b64encode(("%s:%s" % (u, p)).encode()).decode()
    cmd = ["curl", "-s", "--max-time", "40", "-H", "Authorization: Basic %s" % token,
           "-H", "Accept: application/json"]
    if a.proxy:
        cmd += ["-x", a.proxy]
    cmd.append(a.url)
    r = subprocess.run(cmd, capture_output=True, text=True,
                       encoding="utf-8", errors="replace")
    body = (r.stdout or "").strip()
    if not body:
        print("✗ 空响应（curl rc=%s）。若为 401 请检查凭据。" % r.returncode)
        return 1
    try:
        data = json.loads(body)
    except Exception:
        print("✗ 响应不是 JSON，前 400 字节：\n%s" % body[:400])
        return 1

    os.makedirs(DATA, exist_ok=True)
    raw_path = os.path.join(DATA, "positions_raw.json")
    with open(raw_path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=1)
    print("✓ 已取回原始响应 → %s" % os.path.relpath(raw_path, ROOT))

    rows = data if isinstance(data, list) else (
        data.get("positions") or data.get("data") or data.get("list") or [])
    if not rows:
        print("⚠ 未在响应中识别出持仓数组。已存原始响应，请查看字段名后调整映射。")
        print("  顶层键：%s" % (list(data.keys()) if isinstance(data, dict) else type(data).__name__))
        return 0

    if a.dry_run:
        print("\n--dry-run：不写入交易流。识别到 %d 条，字段样本：" % len(rows))
        for r_ in rows[:5]:
            print("   %s" % json.dumps(r_, ensure_ascii=False)[:220])
        return 0

    # 字段映射（宽松：兼容常见命名）
    def pick(d_, *names):
        for n in names:
            for k in d_:
                if k.lower().replace("_", "") == n.lower().replace("_", ""):
                    return d_[k]
        return None

    # 直接保存为快照（保留券商给的 avg_cost / realized_pnl / last）
    snap = {"source": "futu-api", "fetched_at": dt.date.today().isoformat(),
            "quote_date": None, "currency": "USD",
            "totals": data.get("totals") if isinstance(data, dict) else {},
            "positions": []}
    for r_ in rows:
        if not isinstance(r_, dict):
            continue
        qd = r_.get("quote_date")
        if qd and not snap["quote_date"]:
            snap["quote_date"] = qd
        snap["positions"].append({k: r_.get(k) for k in
                                  ("code", "name", "qty", "avg_cost", "cost_basis", "last",
                                   "market_value", "unrealized_pnl", "unrealized_pct",
                                   "realized_pnl", "quote_date")})
    with open(SNAPSHOT, "w", encoding="utf-8") as f:
        json.dump(snap, f, ensure_ascii=False, indent=1)
    # [D-73] 默认**只写标的**（可公开）；--full 才写含数量的本地快照
    tickers = sorted({str(p_.get("code", "")).split(".")[-1].upper()
                      for p_ in rows if isinstance(p_, dict) and p_.get("qty")})
    hj = {"_note": "只保存【标的】，不保存数量/成本/盈亏（可公开的最小信息集）",
          "as_of": snap.get("quote_date"), "source": "broker-api", "tickers": tickers}
    with open(HOLDINGS, "w", encoding="utf-8") as f:
        json.dump(hj, f, ensure_ascii=False, indent=1)
    print("✓ 已保存持仓标的 → %s（%d 个，不含数量）"
          % (os.path.relpath(HOLDINGS, ROOT), len(tickers)))
    if a.full:
        with open(SNAPSHOT, "w", encoding="utf-8") as f:
            json.dump(snap, f, ensure_ascii=False, indent=1)
        print("  含数量的本地快照 → %s（⚠️ 已 gitignore，勿入库）"
              % os.path.relpath(SNAPSHOT, ROOT))
    else:
        print("  未写入含数量的快照（如需仓位%%/盈亏，加 --full）")
    return 0


def cmd_holdings(a):
    rows, pf, snap = build_rows()
    holds = [(r, ) for r in rows if r["hold"]]
    if not holds:
        print("（还没有持仓记录。用 `buy` 记录买入）")
        return 0
    if any(h.get("shares") is None for _r, h in [(r, r["hold"]) for r in rows] if h):
        print("持仓（仅标的 —— 本地无含数量的快照，故不显示仓位/盈亏）")
        print("%-6s %-10s %s" % ("TICKER", "分析动作", "说明"))
        print("-" * 62)
        for r in rows:
            if r["hold"]:
                an = r["analysis"] or {}
                od = an.get("odds")
                print("%-6s %-10s %s" % (r["ticker"], an.get("action", "—"),
                                         ("赔率 %.2f" % od) if od is not None else "无赔率（规则级或无效）"))
        print("-" * 62)
        print("共 %d 个持仓标的。要看仓位%%/盈亏：`sync --full` 拉取含数量的本地快照。"
              % sum(1 for r in rows if r["hold"]))
        return 0
    print("持仓（按市值降序）")
    print("%-6s %10s %10s %10s %12s %10s %12s %s" %
          ("TICKER", "股数", "均价", "现价", "市值", "未实现", "占股票%", "分析动作"))
    print("-" * 96)
    tot = sum(r["market_value"] for r, in holds if r["market_value"])
    rows_sorted = sorted([r for r, in holds], key=lambda r: -(r["market_value"] or 0))
    for r in rows_sorted:
        h, an = r["hold"], r["analysis"]
        un = (r["market_value"] - h["cost"]) if r["market_value"] else None
        wpct = (r["market_value"] / tot * 100) if (r["market_value"] and tot) else None
        print("%-6s %10.4f %10.2f %10s %12s %10s %11s%% %s" % (
            r["ticker"], h["shares"], h["avg_cost"],
            ("%.2f" % r["price"]) if r["price"] else "—",
            fmt(r["market_value"]), fmt(un),
            ("%.1f" % wpct) if wpct is not None else "—",
            (an or {}).get("action", "—")))
    print("-" * 96)
    print("股票市值合计 %s　｜　现金 %s　｜　组合总值 %s"
          % (fmt(tot), fmt(pf.get("cash", 0)), fmt(tot + (pf.get("cash") or 0))))
    if not pf.get("cash"):
        print("  ⚠ 现金未设置（`cash --amount N`）—— 上面的占组合% 实际是占股票市值%")
    if snap:
        t = snap.get("totals", {})
        print("快照 %s（%s）　｜　未实现 %s　｜　未实现%% %.2f%%"
              % (snap.get("date"), snap.get("raw", {}).get("source", ""),
                 fmt(snap["raw"].get("totals", {}).get("unrealized_pnl")),
                 snap["raw"].get("totals", {}).get("unrealized_pct") or 0))
        print("已平仓累计（不在上表中）：")
        for k, v in sorted(snap.get("flat", {}).items()):
            print("   %-6s 已实现 %s" % (k, fmt(v)))
    if tot:
        print("\n占组合％（含现金）：")
        for r in rows_sorted:
            if r["market_value"]:
                print("  %-6s %5.2f%%" % (r["ticker"],
                                          r["market_value"] / (tot + (pf.get("cash") or 0)) * 100))
    return 0


def cmd_board(a):
    rows, pf, snap = build_rows()
    cash = pf.get("cash") or 0.0
    tot_mv = sum(r["market_value"] or 0 for r in rows)
    total = tot_mv + cash

    granular = any(r["hold"] and r["hold"].get("shares") for r in rows)
    print("🛰️ 组合雷达（Radar Board）　%s%s" % (
        dt.date.today().isoformat(),
        "" if granular else "　（仅标的视图 —— 本地无含数量的快照）"))
    print("═" * 104)
    print("%-6s %6s %6s %9s %7s %9s %9s %7s %-9s %s" %
          ("TICKER", "基本面", "赔率", "现价", "仓位", "市值", "未实现", "盈亏%",
           "分析动作", "一致性"))
    print("─" * 104)

    def sortkey(r):
        o = (r["analysis"] or {}).get("odds")
        return -(o if o is not None else -99)

    for r in sorted(rows, key=sortkey):
        t, h, an = r["ticker"], r["hold"], r["analysis"]
        wpct = (r["market_value"] / total * 100) if (r["market_value"] and total) else None
        un = (h.get("last_pnl") if (h and h.get("last_pnl") is not None)
              else ((r["market_value"] - h["cost"]) if (h and r["market_value"]) else None))
        mark, why = _verdict(h, an)
        pnlpct = ((h["last"] / h["avg_cost"] - 1) * 100
                  if (h and h.get("last") and h.get("avg_cost")) else None)
        print("%-6s %6s %6s %9s %7s %9s %9s %7s %-9s %s %s" % (
            t,
            ("%.1f" % an["fundamental_score"]) if an and an.get("fundamental_score") is not None else "—",
            ("%.2f" % an["odds"]) if an and an.get("odds") is not None else "—",
            ("%.2f" % r["price"]) if r["price"] else "—",
            (("%.1f%%" % wpct) if wpct is not None else "—") if h else "—",
            fmt(r["market_value"]) if h else "—",
            fmt(un) if un is not None else "—",
            ("%+.1f%%" % pnlpct) if pnlpct is not None else "—",
            (an or {}).get("action", "—"),
            mark, why))
    print("─" * 104)
    if not granular:
        print("共 %d 个持仓标的。数量/仓位/盈亏不可用 —— 本地无 positions.json（已 gitignore）。"
              % sum(1 for r in rows if r["hold"]))
    else:
        print("股票市值 %s　｜　现金 %s　｜　组合总值 %s　｜　股票仓位 %.1f%%　｜　现金 %.1f%%"
              % (fmt(tot_mv), fmt(cash), fmt(total),
                 (tot_mv / total * 100) if total else 0, (cash / total * 100) if total else 0))
    # 集中度（不依赖任何主题映射，纯客观）
    held = sorted([r for r in rows if r["hold"] and r["market_value"]],
                  key=lambda r: -r["market_value"])
    if held and tot_mv and all(r["market_value"] for r in held):
        w = [r["market_value"] / tot_mv for r in held]
        hhi = sum(x * x for x in w)
        print("")
        print("集中度：%d 个持仓　｜　Top1 %.1f%%　｜　Top3 %.1f%%　｜　Top5 %.1f%%　｜　HHI %.3f"
              % (len(held), w[0] * 100, sum(w[:3]) * 100, sum(w[:5]) * 100, hhi))
        n50 = 0
        acc = 0.0
        for x in w:
            acc += x
            n50 += 1
            if acc >= 0.5:
                break
        print("　　→ 前 %d 个持仓占一半；HHI %.3f 属%s集中"
              % (n50, hhi, "高度" if hhi > 0.25 else "中度" if hhi > 0.15 else "分散"))
        print("　　注意：HHI 只衡量**权重分散度**，不衡量**相关性**。"
              "若多个持仓是同一主题（如 AI/半导体），实际风险远高于 HHI 所示。")

    conf = [(r["ticker"], _verdict(r["hold"], r["analysis"])) for r in rows]
    n_red = sum(1 for _, (m, _w) in conf if m == "🔴")
    n_idea = sum(1 for _, (m, _w) in conf if m == "💡")
    n_unc = sum(1 for _, (m, _w) in conf if m == "❓")
    print("\n🔴 持仓与分析冲突 %d　｜　💡 达标但未持有 %d　｜　❓ 无分析档案 %d" % (n_red, n_idea, n_unc))
    if n_red:
        print("   → 冲突项需要显式决定：减仓，或**用新证据修订分析**（不能两头都算数）")
    return 0


def cmd_check(a):
    rows, _, snap = build_rows()
    issues = []
    for r in rows:
        m, w = _verdict(r["hold"], r["analysis"])
        if m in ("🔴", "❓", "🟡"):
            issues.append((r["ticker"], m, w))
    if not issues:
        print("✅ 持仓与分析结论无冲突")
        return 0
    print("持仓 vs 分析结论　——　需要显式处理的项目")
    print("-" * 78)
    for t, m, w in issues:
        print("  %s %-6s %s" % (m, t, w))
    print("-" * 78)
    print("""处理方式（二选一，不能两头都算数）：
  a) 调仓 —— 记录 sell
  b) 修订分析 —— 用新证据重跑 Alpha Radar，并用 analysis 命令登记新结论（不改旧记录）""")
    return 0


def main():
    ap = argparse.ArgumentParser(description="持仓与组合雷达")
    sub = ap.add_subparsers(dest="cmd", required=True)

    q = sub.add_parser("analysis", help="登记一条 Alpha Radar 分析结论")
    q.add_argument("--ticker", required=True)
    q.add_argument("--score", type=float, default=None, help="Fundamental Score /100")
    q.add_argument("--lifecycle", default=None)
    q.add_argument("--moat", type=float, default=None)
    q.add_argument("--roic", type=float, default=None)
    q.add_argument("--wacc", type=float, default=None)
    q.add_argument("--net-debt-ebitda", dest="net_debt_ebitda", type=float, default=None)
    q.add_argument("--odds", type=float, default=None, help="一致口径赔率（上行/下行）")
    q.add_argument("--odds-basis", choices=["rule-engine", "analyst"], default=None,
                   help="赔率口径：rule-engine=alpha_scenario 生成（可复算）／"
                        "analyst=人工 bottom-up 研判（不可复算）。两者禁止混排")
    q.add_argument("--weighted", type=float, default=None, help="概率加权价值")
    q.add_argument("--bear", type=float, default=None, help="Bear 情景价值")
    q.add_argument("--action", default=None,
                   help="Watch/Starter/Buy/StrongBuy/Core/Hold/Trim/Exit")
    q.add_argument("--price", type=float, default=None)
    q.add_argument("--valuation-pct", dest="valuation_pct", type=float, default=None)
    q.add_argument("--dossier", default=None)
    q.add_argument("--date", default=None)
    q.set_defaults(func=cmd_analysis)

    for name, fn, helptext in (("buy", cmd_buy, "记录买入（append-only）"),
                               ("sell", cmd_sell, "记录卖出（append-only）")):
        q = sub.add_parser(name, help=helptext)
        q.add_argument("--ticker", required=True)
        q.add_argument("--shares", type=float, required=True)
        q.add_argument("--price", type=float, required=True)
        q.add_argument("--date", default=None)
        q.add_argument("--fee", type=float, default=0)
        q.add_argument("--currency", default="USD")
        q.add_argument("--note", default="")
        q.set_defaults(func=fn)

    q = sub.add_parser("cash", help="设置现金余额")
    q.add_argument("--amount", type=float, required=True)
    q.set_defaults(func=cmd_cash)

    q = sub.add_parser("sync", help="[D-13] 从券商 API 拉取持仓")
    q.add_argument("--url", default=os.environ.get(
        "FUTU_API_URL", "https://futu.19831018.xyz/api/positions"))
    q.add_argument("--user", default=None)
    q.add_argument("--password", default=None)
    q.add_argument("--proxy", default=os.environ.get("ALPHA_PROXY") or None)
    q.add_argument("--dry-run", dest="dry_run", action="store_true",
                   help="只看字段，不写入交易流")
    q.add_argument("--as-of", dest="as_of", default=None, help="快照日期")
    q.add_argument("--full", action="store_true",
                   help="[D-73] 同时写含数量/成本的本地快照（⚠️ 已 gitignore，勿公开）")
    q.set_defaults(func=cmd_sync)

    q = sub.add_parser("holdings", help="当前持仓")
    q.set_defaults(func=cmd_holdings)

    q = sub.add_parser("board", help="组合雷达（分析 + 持仓 + 一致性）")
    q.set_defaults(func=cmd_board)

    q = sub.add_parser("check", help="只列持仓与分析的冲突")
    q.set_defaults(func=cmd_check)

    a = ap.parse_args()
    sys.exit(a.func(a))


if __name__ == "__main__":
    main()