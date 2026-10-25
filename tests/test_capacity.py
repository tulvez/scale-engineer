"""Run: python -m unittest discover -s tests"""
import json
import math
import subprocess
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
import capacity  # noqa: E402

PLATFORMS = capacity.load_platforms()


def run(doc, dau=None):
    return capacity.evaluate(doc, PLATFORMS, dau)


class PlatformData(unittest.TestCase):
    def test_every_limit_is_well_formed(self):
        for pk, plat in PLATFORMS["platforms"].items():
            for name, plan in plat["plans"].items():
                for lim in plan.get("limits", []):
                    where = f"{pk}:{name}:{lim.get('metric')}"
                    self.assertIn(lim["metric"], PLATFORMS["metrics"], where)
                    self.assertIn(lim["period"], {"peak", "day", "month", "total"}, where)
                    self.assertIn(lim["kind"], {"hard", "included"}, where)
                    self.assertTrue("value" in lim or "formula" in lim, where)
                    self.assertTrue(lim.get("source", "").startswith("https://"), where)


class Model(unittest.TestCase):
    def test_littles_law(self):
        doc = {"stack": [{"use": "aws-lambda:default", "serves": ["functions"]}],
               "profile": {"dau": 86400, "requests_per_user_day": 1, "active_hours": 24,
                           "peak_factor": 1, "dynamic_ratio": 1, "avg_function_ms": 1000}}
        d = run(doc)["derived"]
        self.assertAlmostEqual(d["peak_rps"], 1.0)
        self.assertAlmostEqual(d["peak_fn_concurrency"], 1.0)

    def test_max_dau_scales_inversely_with_requests(self):
        base = {"stack": [{"use": "cloudflare-workers:free", "serves": ["functions"]}],
                "profile": {"dynamic_ratio": 1, "requests_per_user_day": 10, "avg_cpu_ms": 5}}
        a = run(base)["max_dau"]
        base["profile"]["requests_per_user_day"] = 20
        self.assertAlmostEqual(run(base)["max_dau"], a / 2)
        self.assertAlmostEqual(a, 100000 / 10)

    def test_fixed_usage_is_not_counted_per_user(self):
        doc = {"stack": [{"use": "supabase:free", "serves": ["database"]}],
               "profile": {"base_storage_gb": 0.1, "storage_mb_per_user": 1, "mau_to_dau": 1}}
        row = next(r for r in run(doc)["rows"] if r["metric"] == "db_storage_gb")
        self.assertAlmostEqual(row["max_dau"], (0.5 - 0.1) / 0.001)

    def test_failed_per_request_check_means_zero(self):
        doc = {"stack": [{"use": "cloudflare-workers:free", "serves": ["functions"]}],
               "profile": {"avg_cpu_ms": 50}}
        self.assertEqual(run(doc)["max_dau"], 0)

    def test_spend_cap_turns_included_into_hard(self):
        doc = {"stack": [{"use": "supabase:pro", "serves": ["auth"]}], "profile": {"dau": 1000}}
        capped = next(r for r in run(doc)["rows"] if r["metric"] == "auth_mau")
        self.assertEqual(capped["kind"], "hard")
        doc["stack"][0]["spend_cap"] = False
        billed = next(r for r in run(doc)["rows"] if r["metric"] == "auth_mau")
        self.assertEqual(billed["kind"], "included")

    def test_paid_overage_cost(self):
        doc = {"stack": [{"use": "cloudflare-workers:paid", "serves": ["functions"]}],
               "profile": {"dau": 1, "requests_per_user_day": 1, "dynamic_ratio": 1, "avg_cpu_ms": 1}}
        # 20M requests a month: 10M included, 10M x $0.30/M = $3 + $5 base
        res = run(doc, 20e6 / capacity.DAYS_PER_MONTH)
        self.assertAlmostEqual(res["monthly_cost_usd"], 8.0, places=2)

    def test_server_capacity(self):
        doc = {"stack": [{"use": "vps:custom", "serves": ["functions"], "vcpu": 2, "usd_month": 10}],
               "profile": {"avg_cpu_ms": 10}}
        row = run(doc)["rows"][0]
        self.assertAlmostEqual(row["limit_value"], 2 * 100 * 0.7)

    def test_unknown_input_is_rejected(self):
        for doc in ({"stack": []}, {"stack": [{"use": "nope:free", "serves": ["web"]}]},
                    {"stack": [{"use": "vercel:hobby", "serves": ["nope"]}]}):
            with self.assertRaises(capacity.InputError):
                run(doc)


class Examples(unittest.TestCase):
    def test_examples_run(self):
        for f in sorted((ROOT / "assets" / "examples").glob("*.json")):
            res = run(json.loads(f.read_text(encoding="utf-8")))
            self.assertTrue(res["max_dau"] >= 0 and (math.isfinite(res["max_dau"]) or res["bottleneck"] is None), f.name)

    def test_cli(self):
        out = subprocess.run([sys.executable, str(ROOT / "scripts" / "capacity.py"), "--list"],
                             capture_output=True, text=True)
        self.assertEqual(out.returncode, 0)
        self.assertIn("vercel:hobby", out.stdout)


if __name__ == "__main__":
    unittest.main()
