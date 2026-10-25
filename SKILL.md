---
name: scale-engineer
description: Estimates how many users an app can serve on its current hosting stack and plan, which limit breaks first, and what it costs at a target size. Detects the stack (Vercel, Netlify, Cloudflare Workers/D1/KV, Supabase, Firebase, Neon, AWS Lambda, Upstash, Railway, Fly.io, Render, a VPS) from the repository, distinguishes free and paid plans, computes daily active users, peak concurrent users, requests per second and monthly cost from verified platform limits, and gives a concrete scaling plan. Use when the user asks how many users or concurrent users the app can handle, whether the free tier is enough, when to upgrade, what launch-day traffic will do, why the app hit a quota, or how much hosting will cost at N users.
license: MIT
compatibility: Needs Python 3.8+ (standard library only) to run scripts/capacity.py. Reads repository files; no network access is required, but checking stale limits needs web access.
metadata:
  author: tulvez
  version: "1.0.0"
  repository: https://github.com/tulvez/scale-engineer
---

# Scale Engineer

Turn "how many users can we handle?" into numbers the user can act on: the
maximum daily active users (DAU) and peak concurrent users the current stack
and plan can carry, the limit that breaks first, what happens when it breaks
(blocked, billed or slowed), the monthly cost at a target size, and the next
steps to scale.

Answer in the language the user writes in. Keep platform and metric names as
the vendors write them.

## Principles

- **Numbers from data, not memory.** Platform limits come from
  `assets/platforms.json` (each entry has a source URL and a `verified` date).
  Never quote a quota from memory when the file has it.
- **Never assume a paid plan.** If the plan is unknown, ask. If the user cannot
  say, compute the free plan and the paid plan and show both.
- **Every assumption is visible.** Traffic numbers the user did not give are
  defaults; list them in the report so the user can correct them.
- **Free vs paid changes the failure mode.** On a free or capped plan, a limit
  stops the service (errors, paused project). On a paid plan the same limit
  usually becomes a bill. Say which one applies.
- **Estimates, then measurement.** The model gives an order-of-magnitude answer.
  For anything that matters (launch, a contract, a sale), recommend a load test
  to calibrate it (`references/load-testing.md`).
- **Never read secret values.** Env var *names* reveal the stack; values are not
  needed and must not be printed.

## Workflow

Copy this checklist and work through it:

```
- [ ] 1. Detect the stack
- [ ] 2. Confirm plans (free / paid) and the target
- [ ] 3. Build the traffic profile
- [ ] 4. Check data freshness
- [ ] 5. Run the calculator
- [ ] 6. Check what the model does not cover
- [ ] 7. Write the report and the scaling plan
```

### 1. Detect the stack

Look at config files, dependencies and env var names to find which platform
serves each role: `web`, `functions`, `database`, `auth`, `realtime`, `kv`,
`redis`. Detection rules: `references/detecting-stack.md`.

If something is used that `scripts/capacity.py --list` does not know (for
example MongoDB Atlas, PlanetScale, Clerk), still include it in the report:
look up its current limits on the vendor's pricing page and reason about it
by hand with the formulas in `references/methodology.md`.

### 2. Confirm plans and the target

Ask, in one message, only what you could not find:

- Which plan is each service on (free/hobby or paid; for Supabase, the compute
  size; for servers, vCPU/RAM and instance count)?
- Is the app commercial? (Vercel Hobby forbids commercial use.)
- What is the target: expected DAU, a launch-day spike, or "how far can we go"?

If the user wants an answer right away, proceed with free plans and say so.

### 3. Build the traffic profile

Write a profile file (format: `references/methodology.md` → *Profile format*;
examples in `assets/examples/`). Derive what you can from the code:

- `requests_per_user_day`, `dynamic_ratio`: count API calls on the main screens;
  static assets on a CDN are not dynamic.
- `db_queries_per_request`, `db_rows_read_per_request`: read the main handlers.
  N+1 queries and missing pagination multiply these.
- `realtime_conns_per_user`: subscriptions/channels opened per tab.
- `avg_function_ms`, `avg_cpu_ms`: from logs or observability if available,
  otherwise keep the defaults and flag them.

Defaults are conservative and documented in `references/methodology.md`.

### 4. Check data freshness

Read `verified` at the top of `assets/platforms.json`. If it is more than 90
days old, or the user reports a number that differs, re-check the `source` URL
of every limit that ends up in the top three rows of the report, tell the user
what changed, and use the current value (edit a copy of the JSON if needed).

### 5. Run the calculator

```bash
python scripts/capacity.py profile.json              # at profile.dau
python scripts/capacity.py profile.json --dau 50000  # at another size
python scripts/capacity.py profile.json --json       # for further processing
python scripts/capacity.py --list                    # known platforms and plans
```

The script prints, for every limit: usage at the target, the DAU at which the
limit is reached, and whether it blocks (`OVER`) or bills (`bill`); per-request
checks (timeouts, payload, CPU per request); the bottleneck; maximum DAU and
peak concurrent users; and the monthly cost. Exit code 2 means the input is
wrong; read the message, fix the profile and run again.

To compare options (free vs paid, Vercel vs Cloudflare), write one profile per
option and run each.

### 6. Check what the model does not cover

Before reporting, go through `references/methodology.md` → *Limits of the
model*. The ones that most often matter:

- One slow query or a missing index can cap throughput far below any quota.
- Cold starts and scale-to-zero (Render Free, Neon, Supabase Free pausing).
- Burst limits on a single key or object (KV: 1 write/s per key; Durable
  Objects ~1000 req/s per object; one D1 database is single-threaded).
- Third-party APIs with their own rate limits (email, payments, AI).
- Storage grows with time, not with DAU: estimate it for 6 and 12 months.

### 7. Write the report

Use `assets/report-template.md`. Lead with the answer:

> On the current plans the app handles about **X DAU** (≈ **Y** users online at
> peak). The first limit is **Z**; at that point users get **(error / bill)**.

Then the limit table (top 5 rows), cost at the target, assumptions, and the
scaling plan. Pick scaling steps from `references/scaling-playbook.md`, cheapest
and most effective first: fix code before buying capacity, and say which step
moves which limit and by how much.

## Files

- `scripts/capacity.py` — the calculator (stdlib only).
- `assets/platforms.json` — verified limits and prices with sources.
- `assets/examples/*.json` — sample profiles for common stacks.
- `assets/report-template.md` — report layout.
- `assets/k6-smoke.js` — load-test starting point.
- `references/methodology.md` — formulas, defaults, profile format, model limits.
- `references/detecting-stack.md` — how to recognise each platform in a repo.
- `references/scaling-playbook.md` — what to do when each kind of limit is hit.
- `references/load-testing.md` — calibrating the model with a real test.
