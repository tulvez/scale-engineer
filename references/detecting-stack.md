# Detecting the stack

Search the repository root and app folders. Read file **names** and config
keys; for `.env*` files read only the variable **names**, never the values.

| Signal | Platform | Typical roles |
|---|---|---|
| `vercel.json`, `.vercel/`, `@vercel/*` packages, `next.config.*` with no other host | `vercel` | web, functions |
| `netlify.toml`, `netlify/functions/`, `@netlify/*` | `netlify` | web, functions |
| `wrangler.toml` / `wrangler.json[c]` | `cloudflare-workers` | web, functions |
| ↳ `[[d1_databases]]` / `d1_databases` | `cloudflare-d1` | database |
| ↳ `[[kv_namespaces]]` / `kv_namespaces` | `cloudflare-kv` | kv |
| ↳ `durable_objects`, `r2_buckets`, `queues` | Durable Objects, R2, Queues — not in the data file; reason by hand | |
| `supabase/` folder, `@supabase/supabase-js`, `SUPABASE_URL` | `supabase` | database; add auth if `supabase.auth` is used, realtime if `.channel(` / `.on('postgres_changes'` is used, functions if `supabase/functions/` exists |
| `firebase.json`, `.firebaserc`, `firebase` / `firebase-admin` | `firebase` | database (Firestore/RTDB), auth, web (Hosting), functions |
| `NEON_*` vars, `@neondatabase/serverless`, `*.neon.tech` in a connection-string *name or example* | `neon` | database |
| `serverless.yml`, `template.yaml` (SAM), `cdk.json`, `aws-lambda` handlers | `aws-lambda` | functions |
| `UPSTASH_REDIS_*`, `@upstash/redis` | `upstash-redis` | redis |
| `railway.json` / `railway.toml` | `railway` | server |
| `fly.toml` | `fly` | server |
| `render.yaml` | `render` | server |
| `Dockerfile` / `docker-compose.yml` with no managed host config | `vps` | server; ask for vCPU, RAM and monthly price |

Rules:

- The same platform can serve several roles; list it once with every role in
  `serves`.
- A framework is not a host. Next.js can run on Vercel, Netlify, Cloudflare or a
  server — look for the deploy config, CI deploy step (`.github/workflows/*`
  with `vercel deploy`, `wrangler deploy`, `flyctl deploy`…) or ask.
- Count what the app really calls. A Supabase project used only for Postgres
  must not be checked against Auth or Realtime quotas.
- Plans cannot be read from the repo (except Vercel/Netlify team hints). Ask.
- Also note services outside the data file (Clerk, Auth0, MongoDB Atlas,
  PlanetScale, Resend, Stripe, OpenAI…). Their limits go in the report
  as separate rows, looked up from the vendor's current pricing page.

## Reading traffic numbers from code

- **requests_per_user_day**: open the main screens; count `fetch`/API calls on
  load and per interaction, multiply by typical sessions per day. Polling
  (`setInterval` + fetch) is often the largest term: one call every 5 s for
  15 minutes = 180 requests.
- **dynamic_ratio**: SSR pages, API routes, server actions and middleware run
  code; static pages and hashed assets behind a CDN do not. Next.js
  middleware runs on *every* matched request, including assets if the matcher
  is broad.
- **db_queries_per_request**: count queries in the hot handlers; loops that
  query per item (N+1) multiply this by list length.
- **db_rows_read_per_request**: rows the database scans. Filters on columns
  without an index scan the whole table. On D1 and Firestore this is billed
  directly.
- **realtime**: each `subscribe()` / `channel()` / `onSnapshot()` held open is
  a connection or listener per open tab.
