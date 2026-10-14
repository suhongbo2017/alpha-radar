#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Offline regression tests for alpha_one orchestration."""
import importlib.util
import json
import os
import tempfile
import unittest
from unittest.mock import patch

SPEC = importlib.util.spec_from_file_location(
    "alpha_one", os.path.join(os.path.dirname(__file__), "alpha_one.py"))
alpha_one = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(alpha_one)


class Proc:
    def __init__(self, args, **kwargs):
        self.returncode = 0
        self.stdout = ""
        if any("alpha_metrics.py" in str(part) for part in args):
            self.stdout = '{"ticker":"XYZ","ttm_period":"2025-12-31","ttm_revenue":100,"ttm_fcf":null}'
        elif any("alpha_scenario.py" in str(part) for part in args):
            self.stdout = '{"ticker":"XYZ","note":"rule output"}'


class AlphaOneTests(unittest.TestCase):
    def invoke(self, argv):
        with tempfile.TemporaryDirectory() as tmp:
            old_root, old_runs = alpha_one.ROOT, alpha_one.RUNS
            alpha_one.ROOT = tmp
            alpha_one.RUNS = os.path.join(tmp, "data", "runs")
            try:
                with patch("sys.argv", ["alpha_one.py"] + argv), \
                     patch.object(alpha_one.subprocess, "run", side_effect=Proc), \
                     patch("builtins.print"):
                    rc = alpha_one.main()
                files = os.listdir(alpha_one.RUNS)
                json_file = next(os.path.join(alpha_one.RUNS, f) for f in files if f.endswith(".json"))
                with open(json_file, encoding="utf-8") as f:
                    data = json.load(f)
                md_files = [os.path.join(alpha_one.RUNS, f) for f in files if f.endswith(".md")]
                report = ""
                if md_files:
                    with open(md_files[0], encoding="utf-8") as f:
                        report = f.read()
                return rc, data, report
            finally:
                alpha_one.ROOT, alpha_one.RUNS = old_root, old_runs

    def test_success_outputs_manual_prompts_and_gaps(self):
        rc, data, report = self.invoke(["XYZ"])
        self.assertEqual(rc, 0)
        self.assertEqual(data["status"], "rule-screened")
        self.assertFalse(data["qualification"]["formal_predictions"])
        self.assertIn("TTM 自由现金流", data["data_gaps"])
        self.assertTrue(data["manual_prompts"])
        self.assertIn("需要人工完成的研究判断", report)
        self.assertIn("规则情景", report)
        self.assertIn("不得直接照抄规则情景", report)

    def test_offline_skips_sec_fetch(self):
        rc, data, _ = self.invoke(["XYZ", "--offline", "--no-report"])
        self.assertEqual(rc, 0)
        self.assertTrue(data["stages"][0]["skipped"])
        self.assertEqual(len(data["stages"]), 5)

    def test_ticker_validation(self):
        with patch("sys.argv", ["alpha_one.py", "bad ticker"]), \
             self.assertRaises(SystemExit):
            alpha_one.main()


if __name__ == "__main__":
    unittest.main()
