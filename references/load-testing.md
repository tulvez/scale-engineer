# Calibrating with a load test

The calculator uses assumptions. A short load test replaces the three that
matter most: `avg_function_ms`, `avg_cpu_ms` and the real throughput of a server.

## Rules

- **Never load-test production on a free or capped plan**: the test itself
  uses up the daily or monthly quota and can pause the project. Use a preview
  deployment or a staging project.
- Never test a system you do not own or are not allowed to test.
- Tell the user what the test will consume (requests, bandwidth) before
  running it.

## Steps

1. Pick the two or three hottest endpoints (home feed, search, the main API).
2. Run `assets/k6-smoke.js` against staging:

   ```bash
   k6 run -e BASE_URL=https://staging.example.com -e PATHS=/api/feed,/api/search assets/k6-smoke.js
   ```

   It ramps virtual users up in stages and reports latency percentiles and
   errors. Stop when p95 latency doubles or errors exceed 1 %.
3. Read the results:
   - `http_req_duration` average → `avg_function_ms`.
   - The request rate at which p95 doubles → real capacity of a server
     (compare with the calculator's CPU capacity row; use the lower one).
   - Platform dashboards (Vercel Observability, Cloudflare analytics, Supabase
     reports) → CPU per request, rows read, connections.
4. Update the profile and rerun the calculator. Report both the estimate and
   the measured number.

## Without k6

`autocannon` (Node), `hey` or `oha` work for a single endpoint:

```bash
npx autocannon -c 50 -d 30 https://staging.example.com/api/feed
```
