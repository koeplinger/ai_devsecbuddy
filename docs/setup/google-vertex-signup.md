# Google Vertex AI — signup & setup

This wires DevSecBuddy's `VertexEngine` to run the probe suite against **Claude on
Google Vertex AI** (roadmap **M6**). We run **Claude Haiku via Vertex** by default
(same model as the Anthropic path, different provider) so the demo proves DevSecBuddy
works across providers; running Google's own **Gemini** instead is a future option.

> Do **Anthropic first** ([anthropic-signup.md](anthropic-signup.md)) — it's guaranteed
> to work with your prepaid card. Vertex is heavier and your card may not pass Google's
> billing check (see the ⚠️ below). If it doesn't, you still have a live demo via Anthropic.

## ⚠️ The prepaid-card catch

Google requires a valid card **for identity verification even though the trial is free**,
and GCP is **stricter than Anthropic about prepaid / virtual cards** — they are frequently
declined ([GCP signup FAQs](https://cloud.google.com/signup-faqs)). New accounts get
**$300 in free credit valid for 90 days** ([GCP Free](https://cloud.google.com/free)),
which more than covers Vertex testing — but only if the card passes at signup. If it's
declined, skip Vertex for now and revisit with a different card.

## Steps

1. **Create a Google Cloud account** at **[console.cloud.google.com](https://console.cloud.google.com)**
   → start the **Free Trial** (add card → $300 credit).
2. **Create a project** → note the **project ID** (e.g. `my-devsecbuddy-proj`).
3. **Enable the Vertex AI API** for that project (APIs & Services → Enable APIs).
4. **Enable Claude in Model Garden** — in Vertex AI → Model Garden, find **Anthropic's
   Claude** models and **Enable** them (accept terms). Claude on Vertex is only available
   in **specific regions** (e.g. `us-east5`) — pick one and note it.
5. **Authenticate** (pick one):
   - **Local dev (simplest):** `gcloud auth application-default login` — sets up
     Application Default Credentials (ADC); no key file.
   - **Server:** create a **service account** with the **Vertex AI User** role, download
     its **JSON key**, and `export GOOGLE_APPLICATION_CREDENTIALS=/path/key.json`.
6. **Set a Budget alert** (Billing → Budgets & alerts) so nothing surprises you after the
   free trial.

## Wire it into DevSecBuddy

`VertexEngine` uses the Anthropic SDK's Vertex client (`anthropic[vertex]`), so it speaks
the same Messages API as the direct Anthropic engine — only the auth and model id differ:

```bash
gcloud auth application-default login          # or set GOOGLE_APPLICATION_CREDENTIALS
export DEVSECBUDDY_ENGINE=vertex               # or pick "Vertex" in the UI engine selector
export DEVSECBUDDY_VERTEX_PROJECT="my-devsecbuddy-proj"
export DEVSECBUDDY_VERTEX_REGION="us-east5"    # a region where Claude is enabled
export DEVSECBUDDY_VERTEX_MODEL="claude-haiku-4-5@20251001"   # Vertex model ids may need an @version suffix
uvicorn backend.main:app
```

> **Vertex model ids** sometimes use an `@<version>` suffix (e.g. `claude-haiku-4-5@20251001`)
> rather than the bare alias — check the exact id shown in Model Garden and set
> `DEVSECBUDDY_VERTEX_MODEL` accordingly. This is the one bit that needs a live smoke test.

## Cost

Claude on Vertex bills like the direct Anthropic API (Haiku ≈ $1/$5 per 1M tokens), and
the $300 trial covers far more than this prototype needs. Real models are
**non-deterministic**, so findings vary run-to-run; the ledger captures per-run evidence.

When the card goes through, bring back: the **project ID**, a **region** (where Claude is
enabled), and either a **service-account JSON** or confirmation you've run
`gcloud auth application-default login`. See also [anthropic-signup.md](anthropic-signup.md)
and [ai-engines.md](../ai-engines.md).
