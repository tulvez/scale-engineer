#!/usr/bin/env python3
"""Capacity and cost calculator for the scale-engineer skill.

Reads a stack + traffic profile (JSON), checks it against the verified
platform limits in assets/platforms.json and prints, for every limit, how many
daily active users (DAU) the stack can carry before that limit is hit, which
limit is the bottleneck, and the monthly cost at the target DAU.

Usage:
    python scripts/capacity.py PROFILE.json            # report at profile.dau
    python scripts/capacity.py PROFILE.json --dau 50000
    python scripts/capacity.py PROFILE.json --json     # machine-readable
    python scripts/capacity.py --list                  # platforms and plans

Only the Python standard library is used (Python 3.8+).
"""
from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
PLATFORMS_FILE = HERE.parent / "assets" / "platforms.json"

DAYS_PER_MONTH = 30.4          # average month; daily quotas x this = monthly
WARN_AT = 0.70                 # usage share that is reported as "near the limit"
SERVER_TARGET_UTIL = 0.70      # plan servers for 70 % CPU at peak, not 100 %

# Defaults are deliberately conservative and every one is printed in the
# report as an assumption, so the user can correct it.
DEFAULTS = {
    "dau": 1000,
    "mau_to_dau": 3.0,             # MAU / DAU (stickiness ~33 %)
    "active_hours": 16,            # hours per day carrying almost all traffic
    "peak_factor": 3.0,            # busiest second vs. average over active hours
    "active_minutes_per_user": 15, # minutes a user is active per day
    "requests_per_user_day": 60,   # all HTTP requests (pages, assets not on a CDN, API)
    "dynamic_ratio": 0.4,          # share of requests that run server code
    "avg_function_ms": 150,        # wall time of a dynamic request
    "avg_cpu_ms": 20,              # CPU time of a dynamic request
    "function_memory_gb": 1.0,
    "avg_response_kb": 50,         # average bytes per request sent to the user
    "max_payload_mb": 1,
    "max_duration_s": 5,
    "subrequests_per_request": 2,
    "db_queries_per_request": 2,
    "db_rows_read_per_request": 20,
    "avg_row_kb": 0.5,
    "avg_query_ms": 5,
    "db_writes_per_user_day": 10,
    "storage_mb_per_user": 0.2,     # database bytes per registered user
    "base_storage_gb": 0.05,
    "db_cu": 0.25,                 # serverless Postgres compute size while awake
    "realtime_conns_per_user": 0,
    "realtime_msgs_per_conn_min": 0,
    "kv_reads_per_request": 0,
    "kv_writes_per_user_day": 0,
    "redis_cmds_per_request": 0,
    "commercial": True,
}

ROLE_METRICS = {
    "web": {"requests", "egress_gb", "credits"},
    "functions": {"invocations", "fn_concurrency", "cpu_ms", "active_cpu_hours",
                  "memory_gb_hours", "gb_seconds", "credits"},
    "database": {"db_qps", "db_backend_conns", "db_pool_clients", "db_rows_read",
                 "db_rows_written", "db_storage_gb", "db_awake_cu_hours", "egress_gb"},
    "realtime": {"realtime_conns", "realtime_msgs_per_s", "realtime_msgs"},
    "auth": {"auth_mau"},
    "kv": {"kv_reads", "kv_writes"},
    "redis": {"redis_commands", "redis_cmds_per_s"},
}
CHECK_ROLE = {"duration_s": "functions", "cpu_ms": "functions", "payload_mb": "functions",
              "subrequests": "functions", "db_queries_per_request": "database"}
CHECK_PROFILE = {"duration_s": "max_duration_s", "cpu_ms": "avg_cpu_ms",
                 "payload_mb": "max_payload_mb", "subrequests": "subrequests_per_request",
                 "db_queries_per_request": "db_queries_per_request"}


class InputError(Exception):
    pass


def load_platforms() -> dict:
    try:
        return json.loads(PLATFORMS_FILE.read_text(encoding="utf-8"))
    except FileNotFoundError:
        raise InputError(f"platform data not found: {PLATFORMS_FILE}")


# ── traffic model ─────────────────────────────────────────────────────────

def derive(p: dict, dau: float, serverless: bool) -> dict:
    """Usage of every metric at the given DAU. Per-day values are per day,
    peak values are instantaneous, storage is a total."""
    active_s = p["active_hours"] * 3600
    requests_day = dau * p["requests_per_user_day"]
    invocations_day = requests_day * p["dynamic_ratio"]
    peak_rps = requests_day / active_s * p["peak_factor"]
    peak_dyn_rps = peak_rps * p["dynamic_ratio"]
    fn_conc = peak_dyn_rps * p["avg_function_ms"] / 1000          # Little's law
    peak_users = dau * p["active_minutes_per_user"] / (p["active_hours"] * 60) * p["peak_factor"]
    db_qps = peak_dyn_rps * p["db_queries_per_request"]
    rt_conns = peak_users * p["realtime_conns_per_user"]
    mau = dau * p["mau_to_dau"]
    users_total = p.get("registered_users") or mau
    db_rows_read_day = invocations_day * p["db_rows_read_per_request"]
    return {
        "requests": requests_day,
        "invocations": invocations_day,
        "fn_concurrency": fn_conc,
        "cpu_ms": invocations_day * p["avg_cpu_ms"],
        "active_cpu_hours": invocations_day * p["avg_cpu_ms"] / 3.6e6,
        "memory_gb_hours": invocations_day * p["avg_function_ms"] / 1000 * p["function_memory_gb"] / 3600,
        "gb_seconds": invocations_day * p["avg_function_ms"] / 1000 * p["function_memory_gb"],
        "egress_gb@web": requests_day * p["avg_response_kb"] / 1e6,
        "egress_gb@database": db_rows_read_day * p["avg_row_kb"] / 1e6,
        "peak_rps": peak_rps,
        "peak_dyn_rps": peak_dyn_rps,
        "peak_users": peak_users,
        "db_qps": db_qps,
        "db_backend_conns": db_qps * p["avg_query_ms"] / 1000,
        # serverless: every concurrent invocation holds its own client connection
        "db_pool_clients": fn_conc if serverless else p.get("app_pool_size", 20),
        "db_rows_read": db_rows_read_day,
        "db_rows_written": dau * p["db_writes_per_user_day"],
        "db_storage_gb": p["base_storage_gb"] + users_total * p["storage_mb_per_user"] / 1000,
        "realtime_conns": rt_conns,
        "realtime_msgs_per_s": rt_conns * p["realtime_msgs_per_conn_min"] / 60,
        "realtime_msgs": dau * p["active_minutes_per_user"] * p["realtime_conns_per_user"] * p["realtime_msgs_per_conn_min"],
        "auth_mau": mau,
        "kv_reads": invocations_day * p["kv_reads_per_request"],
        "kv_writes": dau * p["kv_writes_per_user_day"],
        "redis_commands": invocations_day * p["redis_cmds_per_request"],
        "redis_cmds_per_s": peak_dyn_rps * p["redis_cmds_per_request"],
    }


def usage_of(metric: str, period: str, roles: set, u: dict, p: dict, plat_key: str, platforms: dict) -> float:
    if metric == "db_awake_cu_hours":
        awake_h = min(24.0, p["active_hours"] + 1) * DAYS_PER_MONTH  # +1 h: scale-to-zero delay
        return awake_h * p["db_cu"]
    if metric == "egress_gb":
        base = u["egress_gb@web"] if "web" in roles else u["egress_gb@database"]
    elif metric == "credits":
        cc = platforms["platforms"][plat_key]["credit_costs"]
        base = 0.0
        if "web" in roles:
            base += u["requests"] / 1e4 * cc["requests_per_10k"] + u["egress_gb@web"] * cc["egress_gb"]
        if "functions" in roles:
            base += u["memory_gb_hours"] * cc["compute_gb_hour"]
    else:
        base = u[metric]
    if metric in ("db_storage_gb",):
        return base                                   # stock, not a flow
    if period == "month" and metric not in ("auth_mau",):
        return base * DAYS_PER_MONTH
    return base


def limit_value(lim: dict, p: dict) -> float:
    if lim.get("formula") == "single_thread":
        return 1000.0 / max(p["avg_query_ms"], 0.1)
    return float(lim["value"])


# ── evaluation ────────────────────────────────────────────────────────────

def evaluate(doc: dict, platforms: dict, dau_override=None) -> dict:
    p = dict(DEFAULTS)
    assumed = [k for k in DEFAULTS if k not in doc.get("profile", {})]
    p.update(doc.get("profile", {}))
    if dau_override is not None:
        p["dau"] = dau_override
    dau = float(p["dau"])
    if dau <= 0:
        raise InputError("profile.dau must be > 0")
    stack = doc.get("stack") or []
    if not stack:
        raise InputError("stack is empty: add at least one component, e.g. {\"use\": \"vercel:hobby\", \"serves\": [\"web\", \"functions\"]}")

    serverless = any(
        "functions" in c.get("serves", []) and platforms["platforms"].get(c["use"].split(":")[0], {}).get("kind") != "server"
        for c in stack if ":" in c.get("use", ""))
    zero = derive(p, 0.0, serverless)   # usage that does not grow with users
    unit = derive(p, 1.0, serverless)
    target = derive(p, dau, serverless)

    rows, checks, warnings, cost_lines = [], [], [], []
    cost_incomplete = False
    total_cost = 0.0

    for comp in stack:
        use = comp.get("use", "")
        if ":" not in use:
            raise InputError(f"component 'use' must be platform:plan, got {use!r}")
        plat_key, plan_key = use.split(":", 1)
        plat = platforms["platforms"].get(plat_key)
        if not plat:
            raise InputError(f"unknown platform {plat_key!r}; run --list")
        plan = plat["plans"].get(plan_key)
        if not plan:
            raise InputError(f"unknown plan {plan_key!r} for {plat_key}; plans: {', '.join(plat['plans'])}")
        roles = set(comp.get("serves", []))
        bad = roles - set(ROLE_METRICS) - {"server"}
        if bad:
            raise InputError(f"unknown role(s) {sorted(bad)}; use {sorted(ROLE_METRICS) + ['server']}")
        name = f"{plat['name']} · {plan_key}"

        if p.get("commercial") and plan.get("commercial_use") is False:
            warnings.append(f"{name}: plan is for non-commercial use only.")
        for n in plan.get("notes", []):
            warnings.append(f"{name}: {n}")

        if plat.get("kind") == "server":
            r, c, inc = evaluate_server(comp, plat_key, plat, plan, p, unit, target, roles)
            rows.extend(r)
            total_cost += c
            cost_lines.append((name, c))
            cost_incomplete |= inc
            continue

        allowed = set().union(*(ROLE_METRICS[r] for r in roles if r in ROLE_METRICS))
        # with a spend cap on, included quotas stop the service instead of billing
        capped = bool(comp.get("spend_cap", plan.get("spend_cap_default", False)))
        if capped:
            warnings.append(f"{name}: spend cap on — included quotas are treated as hard limits "
                            "(set \"spend_cap\": false on the component to model billing instead).")
        comp_cost = float(plan.get("base_usd", 0))
        usage_charges = 0.0
        for lim in plan.get("limits", []):
            m = lim["metric"]
            if m not in allowed:
                continue
            kind = "hard" if capped and lim["kind"] == "included" and lim.get("value") else lim["kind"]
            lv = limit_value(lim, p)
            # every metric is affine in DAU: usage = fixed + slope * DAU
            fixed = usage_of(m, lim["period"], roles, zero, p, plat_key, platforms)
            slope = usage_of(m, lim["period"], roles, unit, p, plat_key, platforms) - fixed
            at_target = usage_of(m, lim["period"], roles, target, p, plat_key, platforms)
            if fixed > lv:
                max_dau = 0.0
            elif slope <= 0:
                max_dau = math.inf
            else:
                max_dau = (lv - fixed) / slope
            row = {
                "component": name, "limit": lim["label"], "metric": m, "period": lim["period"],
                "kind": kind, "limit_value": lv, "usage_at_target": at_target,
                "share": (at_target / lv) if lv > 0 else (math.inf if at_target > 0 else 0.0),
                "max_dau": max_dau, "source": lim.get("source"),
            }
            if kind == "included":
                over = max(0.0, at_target - lv)
                price = lim.get("overage_usd")
                if over > 0 and price is None:
                    cost_incomplete = True
                    row["overage_usd"] = None
                elif over > 0:
                    charge = over / lim.get("per", 1) * price
                    usage_charges += charge
                    row["overage_usd"] = charge
            rows.append(row)

        credit = float(plan.get("credit_usd", 0)) if plat_key in ("vercel",) else 0.0
        comp_cost += max(0.0, usage_charges - credit)
        total_cost += comp_cost
        cost_lines.append((name, comp_cost))

        for chk in plan.get("per_request", []):
            if CHECK_ROLE.get(chk["check"]) not in roles:
                continue
            val = p[CHECK_PROFILE[chk["check"]]]
            checks.append({"component": name, "check": chk["label"], "value": val, "max": chk["max"],
                           "ok": val <= chk["max"], "source": chk.get("source")})

    hard = [r for r in rows if r["kind"] == "hard"]
    bottleneck = min(hard, key=lambda r: r["max_dau"]) if hard else None
    failed_checks = [c for c in checks if not c["ok"]]
    max_dau = 0.0 if failed_checks else (bottleneck["max_dau"] if bottleneck else math.inf)
    return {
        "dau": dau, "profile": p, "assumed": assumed, "derived": {
            "peak_concurrent_users": target["peak_users"], "peak_rps": target["peak_rps"],
            "peak_dynamic_rps": target["peak_dyn_rps"], "peak_fn_concurrency": target["fn_concurrency"],
            "mau": target["auth_mau"], "requests_per_month": target["requests"] * DAYS_PER_MONTH,
        },
        "rows": rows, "checks": checks, "warnings": warnings,
        "bottleneck": bottleneck, "max_dau": max_dau,
        "max_peak_concurrent_users": (max_dau * unit["peak_users"]) if math.isfinite(max_dau) else math.inf,
        "monthly_cost_usd": total_cost, "cost_lines": cost_lines, "cost_incomplete": cost_incomplete,
    }


def evaluate_server(comp, plat_key, plat, plan, p, unit, target, roles):
    """Long-running servers: capacity comes from CPU, not from quotas."""
    name = f"{plat['name']} · {comp['use'].split(':', 1)[1]}"
    instances = int(comp.get("instances", 1))
    vcpu = float(comp.get("vcpu", plan.get("max_vcpu", 1)))
    ram = float(comp.get("ram_gb", 1))
    rows, incomplete = [], False
    if "max_vcpu" in plan and vcpu > plan["max_vcpu"]:
        raise InputError(f"{name}: {vcpu} vCPU exceeds the plan maximum of {plan['max_vcpu']} per service")
    if "max_replicas" in plan and instances > plan["max_replicas"]:
        raise InputError(f"{name}: {instances} instances exceeds the plan maximum of {plan['max_replicas']} replicas")
    rps_metric = "peak_rps" if "web" in roles else "peak_dyn_rps"
    cpu_ms = max(p["avg_cpu_ms"], 0.1)
    cap = instances * vcpu * 1000 / cpu_ms * SERVER_TARGET_UTIL
    rows.append({
        "component": name, "limit": f"CPU capacity ({instances} × {vcpu:g} vCPU at {int(SERVER_TARGET_UTIL*100)} % target)",
        "metric": rps_metric, "period": "peak", "kind": "hard", "limit_value": cap,
        "usage_at_target": target[rps_metric], "share": target[rps_metric] / cap,
        "max_dau": cap / unit[rps_metric] if unit[rps_metric] else math.inf,
        "source": "derived: requests/s per vCPU = 1000 / avg_cpu_ms (calibrate with a load test)",
    })
    if plat_key == "railway":
        u = plat["usage"]
        compute = instances * (vcpu * u["vcpu_month_usd"] + ram * u["ram_gb_month_usd"])
        egress = target["egress_gb@web"] * DAYS_PER_MONTH * u["egress_gb_usd"] if "web" in roles else 0
        cost = plan["base_usd"] + max(0.0, compute + egress - plan.get("credit_usd", 0))
    elif plat_key == "fly":
        prices = plan["machine_prices_usd_month"]
        machine = comp.get("machine", "shared-cpu-1x-512mb")
        if machine not in prices:
            raise InputError(f"{name}: machine must be one of {sorted(prices)} (or price it as vps)")
        egress = target["egress_gb@web"] * DAYS_PER_MONTH * plat["usage"]["egress_gb_usd"] if "web" in roles else 0
        cost = instances * prices[machine] + egress
    elif "usd_month" in comp:
        cost = float(comp["usd_month"])
    elif plat_key != "vps" and plan.get("base_usd") is not None:
        cost = float(plan["base_usd"])
    else:
        cost, incomplete = 0.0, True
    return rows, cost, incomplete


# ── output ────────────────────────────────────────────────────────────────

def fmt(x: float) -> str:
    if x is None:
        return "?"
    if math.isinf(x):
        return "∞"
    if abs(x) >= 1e9:
        return f"{x/1e9:.2f}B"
    if abs(x) >= 1e6:
        return f"{x/1e6:.2f}M"
    if abs(x) >= 1e4:
        return f"{x/1e3:.1f}k"
    if abs(x) >= 100:
        return f"{x:.0f}"
    if abs(x) >= 1:
        return f"{x:.1f}"
    return f"{x:.3g}"


def print_report(res: dict, platforms: dict) -> None:
    d = res["derived"]
    print(f"scale-engineer capacity report  (limits verified {platforms['verified']})")
    print("=" * 72)
    print(f"Target: {fmt(res['dau'])} DAU  ->  {fmt(d['mau'])} MAU, {fmt(d['peak_concurrent_users'])} peak concurrent users,")
    print(f"        {fmt(d['peak_rps'])} req/s peak ({fmt(d['peak_dynamic_rps'])} dynamic), "
          f"{fmt(d['peak_fn_concurrency'])} concurrent executions, {fmt(d['requests_per_month'])} req/month")
    print()
    print(f"{'component':<30} {'limit':<44} {'use':>6}  {'max DAU':>9}")
    print("-" * 94)
    for r in sorted(res["rows"], key=lambda r: r["max_dau"]):
        share = r["share"]
        flag = "OVER" if share > 1 and r["kind"] == "hard" else ("bill" if share > 1 else ("near" if share >= WARN_AT else ""))
        label = r["limit"] + ("" if r["kind"] == "hard" else " [billed]")
        use = "—" if r["limit_value"] == 0 else fmt(share * 100) + "%"
        print(f"{r['component'][:30]:<30} {label[:44]:<44} {use:>6}  {fmt(r['max_dau']) if r['kind']=='hard' else '—':>9} {flag}")
    if res["checks"]:
        print()
        for c in res["checks"]:
            print(f"{'ok ' if c['ok'] else 'FAIL'} {c['component']}: {c['check']} — app {fmt(c['value'])}, limit {fmt(c['max'])}")
    print()
    b = res["bottleneck"]
    failed = [c for c in res["checks"] if not c["ok"]]
    if failed:
        print("RESULT: the app cannot run on this stack at any size — a per-request limit fails:")
        for c in failed:
            print(f"        {c['component']}: {c['check']} (app {fmt(c['value'])} > limit {fmt(c['max'])})")
    elif res["max_dau"] == 0:
        print(f"RESULT: {b['component']} — {b['limit']} is exceeded by usage that does not depend on users")
        print(f"        (e.g. a database kept awake during active hours). Fix that first; source: {b['source']}")
    elif b:
        print(f"RESULT: max ≈ {fmt(res['max_dau'])} DAU ≈ {fmt(res['max_peak_concurrent_users'])} peak concurrent users")
        print(f"        bottleneck: {b['component']} — {b['limit']} ({b['source']})")
    else:
        print("RESULT: no hard limit applies (paid, usage-billed stack); capacity is bounded by cost and by app code.")
    print()
    print(f"Monthly cost at target: ${res['monthly_cost_usd']:.2f}" + ("  (INCOMPLETE: some prices unknown — see source)" if res["cost_incomplete"] else ""))
    for name, c in res["cost_lines"]:
        print(f"  {name:<40} ${c:,.2f}")
    if res["assumed"]:
        print()
        print("Assumed defaults (replace with real numbers): " + ", ".join(f"{k}={res['profile'][k]}" for k in res["assumed"]))
    if res["warnings"]:
        print()
        print("Notes:")
        for w in dict.fromkeys(res["warnings"]):
            print(f"  - {w}")


def list_platforms(platforms: dict) -> None:
    print(f"platforms (verified {platforms['verified']}):")
    for key, plat in platforms["platforms"].items():
        kind = " [server]" if plat.get("kind") == "server" else ""
        print(f"  {key:<20} {plat['name']}{kind}: " + ", ".join(f"{key}:{k}" for k in plat["plans"]))
    print("roles: " + ", ".join(sorted(ROLE_METRICS) + ["server"]))


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("profile", nargs="?", help="stack + traffic profile JSON file")
    ap.add_argument("--dau", type=float, help="override profile.dau")
    ap.add_argument("--json", action="store_true", help="print JSON instead of a table")
    ap.add_argument("--list", action="store_true", help="list known platforms and plans")
    a = ap.parse_args(argv)
    try:
        platforms = load_platforms()
        if a.list:
            list_platforms(platforms)
            return 0
        if not a.profile:
            ap.error("profile file is required (or use --list)")
        try:
            doc = json.loads(Path(a.profile).read_text(encoding="utf-8"))
        except FileNotFoundError:
            raise InputError(f"profile not found: {a.profile}")
        except json.JSONDecodeError as e:
            raise InputError(f"profile is not valid JSON: {e}")
        res = evaluate(doc, platforms, a.dau)
        if a.json:
            print(json.dumps(res, indent=2, default=lambda o: None, allow_nan=True))
        else:
            print_report(res, platforms)
        return 0
    except InputError as e:
        print(f"error: {e}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
