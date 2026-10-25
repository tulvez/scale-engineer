# Methodology

## Contents

- Model
- Formulas
- Profile format
- Defaults
- How a limit becomes "max DAU"
- Cost
- Limits of the model

## Model

Everything is expressed per **daily active user (DAU)**. Each quota is a
resource the app consumes at some rate per user, plus a fixed part that does
not grow with users (a base database size, a database that stays awake). For
every limit:

```
usage(DAU) = fixed + slope × DAU
max DAU    = (limit − fixed) / slope
```

The limit with the smallest max DAU among **hard** limits is the bottleneck.
Limits of kind **included** are not ceilings: past them the plan bills
overage (unless a spend cap is on, then they act as hard limits).

Periods: `day` quotas are compared with one day of usage, `month` quotas with
30.4 days, `peak` limits with the busiest second, `total` with stock values
such as database size.

## Formulas

Traffic arrives during `active_hours` per day, and the busiest second is
`peak_factor` times the average over those hours.

```
requests/day          = DAU × requests_per_user_day
invocations/day       = requests/day × dynamic_ratio
peak RPS              = requests/day / (active_hours × 3600) × peak_factor
peak dynamic RPS      = peak RPS × dynamic_ratio
peak concurrency      = peak dynamic RPS × avg_function_ms / 1000          (Little's law)
peak concurrent users = DAU × active_minutes_per_user / (active_hours × 60) × peak_factor
MAU                   = DAU × mau_to_dau
egress GB/day (web)   = requests/day × avg_response_kb / 10^6
DB queries/s at peak  = peak dynamic RPS × db_queries_per_request
DB busy connections   = DB queries/s × avg_query_ms / 1000
DB rows read/day      = invocations/day × db_rows_read_per_request
DB egress GB/day      = rows read/day × avg_row_kb / 10^6
DB size GB            = base_storage_gb + registered_users × storage_mb_per_user / 1000
active CPU hours/day  = invocations/day × avg_cpu_ms / 3.6×10^6
memory GB-hours/day   = invocations/day × avg_function_ms/1000 × function_memory_gb / 3600
realtime connections  = peak concurrent users × realtime_conns_per_user
realtime messages/day = DAU × active_minutes_per_user × realtime_conns_per_user × realtime_msgs_per_conn_min
```

Serverless functions open one database client per concurrent execution, so
`db_pool_clients` = peak concurrency. Long-running servers use a fixed pool
(`app_pool_size`, default 20).

**Servers** (Railway, Fly, Render, VPS) have no request quota; capacity is CPU:

```
capacity RPS = instances × vCPU × 1000 / avg_cpu_ms × 0.70
```

0.70 is the target utilisation at peak (headroom for spikes and GC). This is
an upper bound for CPU-bound handlers; I/O-bound handlers are usually limited
by the database first. Calibrate it with a load test.

**Cloudflare D1** runs each database single-threaded: about
`1000 / avg_query_ms` queries per second per database.

## Profile format

```json
{
  "name": "free text",
  "stack": [
    {"use": "vercel:hobby",  "serves": ["web", "functions"]},
    {"use": "supabase:free", "serves": ["database", "auth", "realtime"]},
    {"use": "railway:hobby", "serves": ["web", "functions"], "instances": 2, "vcpu": 1, "ram_gb": 1},
    {"use": "fly:payg", "serves": ["functions"], "instances": 2, "machine": "shared-cpu-1x-1gb"},
    {"use": "vps:custom", "serves": ["web", "functions"], "vcpu": 4, "usd_month": 12},
    {"use": "supabase:pro", "serves": ["database"], "spend_cap": false}
  ],
  "profile": { "dau": 5000, "requests_per_user_day": 40 }
}
```

- `use` is `platform:plan` as printed by `--list`.
- `serves` decides which limits apply: a Supabase project used only as a
  database is not checked against its Auth MAU quota.
- Component options: `instances`, `vcpu`, `ram_gb` (servers), `machine`
  (Fly), `usd_month` (VPS or any server with a fixed price), `spend_cap`
  (override the plan default).
- `profile` overrides any default below. `registered_users` overrides the
  MAU-based estimate for database size (use it for apps with a long history).

## Defaults

| Field | Default | Meaning |
|---|---|---|
| `dau` | 1000 | daily active users at the target |
| `mau_to_dau` | 3.0 | MAU / DAU; 3 ≈ 33 % stickiness; social apps ~2, tools ~4–5 |
| `active_hours` | 16 | hours per day with almost all traffic; one-country apps 14–16, global 24 |
| `peak_factor` | 3.0 | busiest second / average; 5–10 for launches, TV, push notifications |
| `active_minutes_per_user` | 15 | minutes per user per day |
| `requests_per_user_day` | 60 | all HTTP requests not served from a CDN cache |
| `dynamic_ratio` | 0.4 | share that runs server code |
| `avg_function_ms` | 150 | wall time of a dynamic request (includes waiting on the DB) |
| `avg_cpu_ms` | 20 | CPU time of a dynamic request |
| `function_memory_gb` | 1.0 | memory size of the function |
| `avg_response_kb` | 50 | average bytes sent per request |
| `max_payload_mb` | 1 | largest request or response body |
| `max_duration_s` | 5 | slowest request (exports, AI calls) |
| `subrequests_per_request` | 2 | outgoing fetches per request (Workers) |
| `db_queries_per_request` | 2 | |
| `db_rows_read_per_request` | 20 | rows *scanned*, not returned: a missing index makes this huge |
| `avg_row_kb` | 0.5 | |
| `avg_query_ms` | 5 | |
| `db_writes_per_user_day` | 10 | rows written per user per day |
| `storage_mb_per_user` | 0.2 | database bytes per registered user |
| `base_storage_gb` | 0.05 | schema, seed data, indexes |
| `db_cu` | 0.25 | Neon compute size while awake |
| `realtime_conns_per_user` | 0 | open realtime channels per online user |
| `realtime_msgs_per_conn_min` | 0 | messages per connection per minute |
| `kv_reads_per_request` | 0 | |
| `kv_writes_per_user_day` | 0 | |
| `redis_cmds_per_request` | 0 | |
| `commercial` | true | false only for hobby/personal projects |

## How a limit becomes "max DAU"

A limit at 70 % or more of its value is reported as `near`. Past 100 %:
`OVER` for hard limits (the service stops or errors), `bill` for included
quotas (overage is charged). Per-request checks (timeout, payload, CPU per
request) do not scale with users: if one fails, the app cannot run on that
plan at any size and max DAU is 0.

## Cost

```
monthly = base price + Σ max(0, usage − included) / per × overage price − usage credit
```

Vercel Pro's $20 credit is subtracted from usage charges. Supabase's $10 credit
covers compute only and is already reflected in the base price of the Micro
size. Servers: Railway bills vCPU, RAM and egress against the included usage;
Fly bills per machine plus egress; a VPS uses `usd_month`. When a price is not
published in the data (`overage_usd: null`), the total is marked INCOMPLETE:
look it up from the `source` URL.

## Limits of the model

- **Averages hide tails.** One slow endpoint (report export, AI call) can
  exhaust concurrency long before the average says so. Model it separately.
- **Database work is the usual real bottleneck.** Quotas assume queries are
  fast. A missing index turns 20 rows read into 200,000. Check `EXPLAIN` on
  the hot queries before trusting the result.
- **Hot keys and hot objects.** KV allows one write per second per key;
  Durable Objects handle ~1000 req/s per object; one D1 database is one thread;
  one Postgres row updated by everyone (a counter) serialises writes.
- **Cold starts and pausing.** Render Free sleeps after 15 min (~1 min to wake);
  Neon scales to zero after 5 min; Supabase Free pauses after a week without
  activity. These hurt latency and availability, not capacity.
- **Storage grows over time.** Database size depends on everyone who ever
  signed up, not on today's DAU. Project it for 6 and 12 months.
- **Third-party limits.** Email providers, payment APIs and AI APIs have their
  own rate limits and costs, often lower than the hosting limits.
- **Bots and abuse.** Crawlers and attacks consume the same quotas. A free plan
  without bot protection can be emptied by one scraper.
- **Prices change.** Re-check sources when `verified` is older than 90 days.
