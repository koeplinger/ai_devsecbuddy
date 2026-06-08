# Anthropic (Claude) API — signup & setup

This gets you an `ANTHROPIC_API_KEY` so DevSecBuddy's `AnthropicEngine` can run the
probe suite against a real Claude model (roadmap **M6**). It is the simplest and
cheapest of the two providers, and your prepaid card will work here.

> **It is not a subscription.** The Claude API is **prepaid pay-as-you-go**: you buy
> usage credits (minimum **$5**) and the API draws down per request. No monthly fee.
> (*Claude.ai Pro* is a separate consumer chat plan — you do **not** need it.)
> Source: [How API billing works](https://support.anthropic.com/en/articles/8977456-how-do-i-pay-for-my-api-usage).

## Cost reality — $45 is far more than enough

Our prompts are tiny (a résumé + a short probe, a one-line score back). Current
pricing ([Anthropic pricing](https://platform.claude.com/docs/en/about-claude/pricing)):

| Model | Input / output ($/1M tokens) | ≈ cost per full 4-tile run |
| --- | --- | --- |
| **Claude Haiku 4.5** (`claude-haiku-4-5`) — recommended | $1 / $5 | ~$0.06 |
| Claude Sonnet 4.6 (`claude-sonnet-4-6`) | $3 / $15 | ~$0.17 |
| Claude Opus 4.8 (`claude-opus-4-8`) | $5 / $25 | ~$0.30 |

A full run is ~70 small calls. On Haiku, **$45 ≈ 700+ runs** — you only need to load
**$5–10** to start (credits are non-refundable and expire one year after purchase).

## Steps (≈5 minutes)

1. **Create an account** at **[console.anthropic.com](https://console.anthropic.com)**.
2. **Billing → Add payment method** (your prepaid card) → **Buy credits** (≥ $5).
   The $5 minimum also lifts you from the free tier to Tier 1 (50 requests/minute).
3. **API keys → Create key** → copy it now (it is shown **once**).
4. **Store it as an environment variable** — never commit it:
   ```bash
   # in a gitignored frontend/.env.local or your shell profile / secrets manager
   export ANTHROPIC_API_KEY="sk-ant-..."
   ```
5. *(Optional, recommended)* set a low balance and **disable aggressive auto-reload**
   as a cost guardrail.

## Wire it into DevSecBuddy

The backend selects the engine from the environment (docs/ai-engines.md):

```bash
export ANTHROPIC_API_KEY="sk-ant-..."
export DEVSECBUDDY_ENGINE=anthropic            # or pick "Anthropic" in the UI engine selector
export DEVSECBUDDY_ANTHROPIC_MODEL=claude-haiku-4-5   # default; switchable to sonnet/opus anytime
uvicorn backend.main:app
```

Then a `POST /runs` (or the **Run assessment** button in the UI) runs the probe suite
against Claude instead of the offline mock.

> **One honest caveat:** real models are **non-deterministic**, so unlike the mock the
> findings will vary run-to-run. The ledger captures the exact request/response evidence
> per run — which is exactly the point of testing a real model.

When you have the key, hand it to me (or set it as above) and I'll do a live smoke test.
See also the [Vertex setup](google-vertex-signup.md) and [ai-engines.md](../ai-engines.md).
