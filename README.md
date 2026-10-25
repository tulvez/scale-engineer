# scale-engineer

An [Agent Skill](https://agentskills.io) that answers **"how many users can this app handle?"** with numbers:
maximum daily active users and peak concurrent users on the current hosting stack and plan, the limit that
breaks first, what happens when it does (blocked, paused or billed), the monthly cost at a target size, and a
scaling plan.

It knows the free and paid plans of Vercel, Netlify, Cloudflare Workers / D1 / KV, Supabase, Firebase, Neon,
AWS Lambda, Upstash Redis, Railway, Fly.io, Render and self-managed servers. Every limit in
[`assets/platforms.json`](assets/platforms.json) has a source link and a verification date.

## Install

Copy the folder into your agent's skills directory, for example:

| Agent | Location |
|---|---|
| Tulvez Code | `.tulvez/skills/scale-engineer/` |
| Claude Code | `.claude/skills/scale-engineer/` or `~/.claude/skills/scale-engineer/` |
| Other Agent Skills clients | their skills folder |

```bash
git clone https://github.com/tulvez/scale-engineer .claude/skills/scale-engineer
```

Then ask: *"How many concurrent users can this app handle on the free plans?"*

## Use the calculator directly

Python 3.8+, no dependencies.

```bash
python scripts/capacity.py assets/examples/nextjs-vercel-supabase.json
python scripts/capacity.py assets/examples/nextjs-vercel-supabase.json --dau 10000
python scripts/capacity.py --list
```

```
RESULT: max ≈ 750 DAU ≈ 35.2 peak concurrent users
        bottleneck: Supabase · free — Database size (https://supabase.com/pricing)
```

Profile format, formulas and defaults: [`references/methodology.md`](references/methodology.md).

## Accuracy

The output is an estimate built from averages. It is good for "will the free tier last until launch?" and
"what does 10x cost?"; for anything with money or a deadline on it, calibrate with a load test
([`references/load-testing.md`](references/load-testing.md)). Prices and quotas change: if
`verified` in `platforms.json` is older than 90 days the skill re-checks the sources. Corrections are welcome
as pull requests — include the source link.

## Tests

```bash
python -m unittest discover -s tests
```

## License

MIT

---

## Türkçe

**scale-engineer**, "bu uygulama kaç kullanıcı kaldırır?" sorusunu sayılarla yanıtlayan bir yapay zekâ
becerisidir (Agent Skill). Depodaki yapılandırmadan kullanılan altyapıyı (Vercel, Cloudflare, Supabase,
Firebase, Neon…) bulur, planın ücretsiz mi ücretli mi olduğunu sorar ve şunları hesaplar:

- günlük aktif kullanıcı ve aynı anda çevrimiçi kullanıcı sınırı,
- ilk dolan kota ve dolunca ne olduğu (istekler durur, proje uyur ya da ücret yazılır),
- hedef kullanıcı sayısında aylık maliyet,
- en ucuzdan pahalıya ölçekleme adımları.

Bütün sınırlar kaynak bağlantısı ve doğrulama tarihiyle `assets/platforms.json` içindedir. Yanıtlar
kullanıcının yazdığı dilde verilir. Kurulum ve kullanım yukarıdaki İngilizce bölümle aynıdır.
