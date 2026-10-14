#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Local browser entry point for the Alpha Radar preparation workflow.

Only binds to loopback. The public GitHub Pages site remains read-only.
"""
import argparse
import datetime as dt
import json
import os
import re
import subprocess
import sys
import threading
import uuid
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import unquote, urlparse

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
WEB = os.path.join(ROOT, "web", "alpha_workbench.html")
RUNS = os.path.join(ROOT, "data", "runs")
TICKER_RE = re.compile(r"^[A-Z][A-Z0-9.\-]{0,9}$")
JOBS = {}
LOCK = threading.Lock()


def utc_now():
    return dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")


def public_job(job):
    return {k: v for k, v in job.items() if k != "process"}


def run_job(job_id, ticker, options):
    command = [sys.executable, "scripts/alpha_one.py", ticker]
    for flag in ("--force", "--offline", "--no-cross", "--no-report", "--no-draft"):
        if options.get(flag[2:]):
            command.append(flag)
    proc = subprocess.Popen(command, cwd=ROOT, stdout=subprocess.PIPE,
                            stderr=subprocess.STDOUT, text=True, encoding="utf-8",
                            errors="replace")
    with LOCK:
        JOBS[job_id]["command"] = command
        JOBS[job_id]["status"] = "running"
        JOBS[job_id]["started_at"] = utc_now()
        JOBS[job_id]["process"] = proc
    output, _ = proc.communicate()
    with LOCK:
        job = JOBS[job_id]
        job["output"] = output[-12000:]
        job["returncode"] = proc.returncode
        job["status"] = "completed" if proc.returncode == 0 else "failed"
        job["finished_at"] = utc_now()
        job.pop("process", None)


class Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):
        return

    def send_json(self, status, payload):
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        path = urlparse(self.path).path
        if path == "/":
            try:
                body = open(WEB, "rb").read()
            except OSError:
                self.send_error(404, "workbench page missing")
                return
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        if path.startswith("/api/jobs/"):
            job_id = unquote(path.rsplit("/", 1)[-1])
            with LOCK:
                job = JOBS.get(job_id)
                payload = public_job(job) if job else None
            self.send_json(200 if payload else 404, payload or {"error": "任务不存在"})
            return
        if path == "/api/runs":
            rows = []
            if os.path.isdir(RUNS):
                for name in sorted(os.listdir(RUNS), reverse=True):
                    if name.endswith(".json"):
                        rows.append(name)
                    if len(rows) >= 12:
                        break
            self.send_json(200, {"runs": rows})
            return
        self.send_error(404)

    def do_POST(self):
        if urlparse(self.path).path != "/api/jobs":
            self.send_error(404)
            return
        try:
            length = int(self.headers.get("Content-Length", "0"))
            payload = json.loads(self.rfile.read(length) or b"{}")
        except (ValueError, json.JSONDecodeError):
            self.send_json(400, {"error": "请求格式无效"})
            return
        ticker = str(payload.get("ticker", "")).strip().upper()
        if not TICKER_RE.fullmatch(ticker):
            self.send_json(400, {"error": "ticker 格式无效"})
            return
        options = {key: bool(payload.get(key, False))
                   for key in ("force", "offline", "no-cross", "no-report", "no-draft")}
        job_id = uuid.uuid4().hex[:12]
        with LOCK:
            JOBS[job_id] = {"id": job_id, "ticker": ticker, "status": "queued",
                            "created_at": utc_now(), "options": options,
                            "output": "", "returncode": None}
        threading.Thread(target=run_job, args=(job_id, ticker, options), daemon=True).start()
        self.send_json(202, public_job(JOBS[job_id]))


def main():
    ap = argparse.ArgumentParser(description="Alpha Radar 本地网页入口")
    ap.add_argument("--host", default="127.0.0.1", help="监听地址，默认仅本机")
    ap.add_argument("--port", type=int, default=8765)
    ap.add_argument("--no-open", action="store_true", help="不自动打开浏览器")
    args = ap.parse_args()
    server = ThreadingHTTPServer((args.host, args.port), Handler)
    url = "http://%s:%d/" % (args.host, args.port)
    print("Alpha Radar 本地工作台：%s" % url)
    print("仅监听本机；按 Ctrl+C 停止")
    if not args.no_open:
        threading.Timer(0.5, lambda: webbrowser.open(url)).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n已停止")
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
