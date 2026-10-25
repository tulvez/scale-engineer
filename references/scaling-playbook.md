# Scaling playbook

Order matters: change code and caching before buying capacity. For each step,
state which limit it moves and roughly by how much (rerun the calculator with
the changed profile).

## Contents

- Requests and invocations
- Bandwidth
- Function CPU, memory, duration
- Database
- Realtime
- Auth MAU
- Servers
- Moving off a free plan
- Protecting quotas

## Requests and invocations

1. Serve everything static from the CDN with long `Cache-Control` on hashed
   assets; make sure middleware does not match assets.
2. Cache dynamic responses that are the same for many users
   (`s-maxage` + `stale-while-revalidate`, ISR, Workers Cache API). Lowers
   `dynamic_ratio`.
3. Replace polling with realtime push or longer intervals with backoff when
   the tab is hidden. Lowers `requests_per_user_day`.
4. Batch API calls on page load into one request.

## Bandwidth

1. Compress (brotli/gzip) JSON and HTML; paginate lists.
2. Images: modern formats and correct sizes; consider the image optimiser's own
   quota before turning it on.
3. Large files: object storage with free egress (Cloudflare R2) instead of
   serving through functions.

## Function CPU, memory, duration

1. Profile the slowest endpoints; move heavy work (exports, AI, image work) to
   a queue or background job with its own limits.
2. Lower memory size when the function does not need it (memory GB-hours scale
   with it).
3. On Cloudflare Free, 10 ms CPU per request is a hard wall: move heavy routes
   to the paid plan or another runtime.

## Database

1. Index the columns used in `WHERE`, `JOIN`, `ORDER BY` of hot queries; check
   with `EXPLAIN`. Usually the largest single gain.
2. Fix N+1 queries; select only needed columns.
3. Use the transaction pooler (Supavisor, PgBouncer, Neon pooled URL) from
   serverless functions; never a direct connection per invocation.
4. Cache read-heavy data (KV, Redis, CDN) with a short TTL.
5. Then scale: larger compute (Supabase compute size, Neon CU), read replicas,
   and only then sharding (D1: one database per tenant).
6. Storage: archive or delete old rows; move blobs out of the database.

## Realtime

1. Subscribe only on screens that need it; unsubscribe on hidden tabs.
2. Use one multiplexed channel per user instead of one per widget.
3. Broadcast diffs, throttle presence updates.
4. Past a few thousand concurrent connections, check the plan's hard ceiling
   (Supabase Pro: 10,000 with the spend cap off) and plan a dedicated service.

## Auth MAU

MAU is billed per user who signs in in a month. Anonymous/guest sessions often
count too — check the provider. Clean up test accounts and bots.

## Servers

1. Measure requests per second per instance with a load test, keep peak CPU
   under ~70 %.
2. Scale horizontally (more instances behind the load balancer) once the app is
   stateless; vertical scaling first if it is not.
3. Put a CDN in front; keep sessions out of process memory.

## Moving off a free plan

Upgrade when **any** of these is true, whichever comes first:

- A hard limit is above ~70 % at normal traffic (a spike will cross it).
- The plan forbids commercial use and the app makes money (Vercel Hobby).
- The platform pauses or sleeps the service and users notice (Supabase Free
  pausing, Render Free spin-down, Neon cold starts on the critical path).
- A per-request limit fails (timeout, payload, CPU per request).

When moving to a paid plan, set a budget or spend cap and alerts on day one.

## Protecting quotas

- Rate-limit anonymous endpoints; add bot protection (Turnstile, WAF rules).
- Cache 404s and error responses briefly so scrapers do not hit the database.
- Alert at 50 % and 80 % of every monthly quota.
