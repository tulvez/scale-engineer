# Capacity report — {app name}

_Limits verified {platforms.json verified date}. Estimate; calibrate with a load test before relying on it._

## Answer

On the current plans the app handles about **{max DAU} daily active users**
(≈ **{peak concurrent}** online at the busiest moment).
The first limit is **{bottleneck}** on **{component}**. When it is reached,
**{what happens: requests fail with … / project pauses / overage is billed at …}**.

At the target of **{target DAU} DAU**: {fits / does not fit}; monthly cost **${cost}**.

## Stack

| Role | Service · plan | Free / paid |
|---|---|---|
| … | … | … |

## Limits (closest first)

| Limit | Usage at target | Max DAU | When exceeded |
|---|---|---|---|
| … | …% | … | blocked / billed $… |

Per-request checks: {all pass / which fails}.

## Cost at {target DAU} DAU

| Service | Monthly |
|---|---|
| … | $… |
| **Total** | **$…** |

## Assumptions

{traffic numbers that were assumed, and which ones matter most for the answer}

## Not covered by the numbers

{slow queries, hot keys, cold starts, third-party limits, storage growth — only those that apply}

## Scaling plan

1. **{cheapest, biggest step}** — moves {limit} from {a} to {b} DAU.
2. …
3. **Upgrade trigger:** move to {plan} when {condition}; cost then ≈ ${…}/month.
