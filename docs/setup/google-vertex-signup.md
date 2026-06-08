# Google Vertex AI (Gemini) — signup & setup

This wires DevSecBuddy's `VertexEngine` to run the probe suite against **Google's
Gemini models on GCP Vertex AI** (roadmap **M6**), using Google's own
[`google-genai`](https://pypi.org/project/google-genai/) SDK in Vertex mode. The
default model is **`gemini-2.5-flash`** (cheap + fast). This is the counterpart to
the Anthropic engine, which runs **Claude directly against the Anthropic API** — so
between the two you cover both major model families, each on its native provider.

> Authentication uses **Application Default Credentials (ADC)** — no API key. You run
> `gcloud auth application-default login` once and the SDK picks the credentials up.

## ⚠️ The prepaid-card catch

Google requires a valid card **for identity verification even though the trial is free**,
and GCP is **stricter than Anthropic about prepaid / virtual cards** — they are frequently
declined ([GCP signup FAQs](https://cloud.google.com/signup-faqs)). New accounts get
**$300 in free credit valid for 90 days** ([GCP Free](https://cloud.google.com/free)),
which more than covers Gemini testing — but only if the card passes at signup.

## Steps

1. **Create a Google Cloud account** at **[console.cloud.google.com](https://console.cloud.google.com)**
   → start the **Free Trial** (add card → $300 credit).
2. **Create a project** and note its **project ID** (e.g. `devsecbuddy`) and **number**.
3. **Enable the Vertex AI API** for that project
   ([Vertex AI API quickstart](https://cloud.google.com/vertex-ai/docs/start/cloud-environment)):
   `gcloud services enable aiplatform.googleapis.com --project <PROJECT_ID>` (or via the
   APIs & Services console).
4. **Grant your account** the **Vertex AI User** role (`roles/aiplatform.user`) on the
   project (Owner also works for a personal project).
5. **Authenticate** (pick one):
   - **Local dev (simplest):** `gcloud auth application-default login` — writes
     Application Default Credentials; no key file.
   - **Server:** create a **service account** with **Vertex AI User**, download its
     **JSON key**, and `export GOOGLE_APPLICATION_CREDENTIALS=/path/key.json`.
6. **Pick a region + model.** Gemini 2.5 Flash is served from several regions plus the
   `global` endpoint. If a run returns `NOT_FOUND` for the model in your region, switch
   `DEVSECBUDDY_VERTEX_REGION` to `us-central1` or `global`
   ([Gemini locations](https://cloud.google.com/vertex-ai/generative-ai/docs/learn/locations)).
7. **Set a Budget alert** (Billing → Budgets & alerts) so nothing surprises you after the
   free trial.

## Wire it into DevSecBuddy

`VertexEngine` uses the `google-genai` SDK's Vertex client
(`genai.Client(vertexai=True, project=…, location=…)`) and the **generate_content** API.
Set these in your gitignored **`.env`** (see [`.env.sample`](../../.env.sample)):

```bash
gcloud auth application-default login            # one-time ADC login
# .env
DEVSECBUDDY_ENGINE=vertex                         # or pick "vertex" in the UI engine selector
DEVSECBUDDY_VERTEX_PROJECT=devsecbuddy            # your GCP project ID
DEVSECBUDDY_VERTEX_REGION=us-east1                # a region serving Gemini 2.5 Flash
DEVSECBUDDY_VERTEX_MODEL=gemini-2.5-flash
```

Install the SDK if you're not using `deploy.sh` (which installs it for you):
`pip install -e ".[vertex]"` (= `google-genai`).

> Gemini 2.5 is a "thinking" model; for this bounded scoring task `VertexEngine`
> disables thinking (`thinking_budget=0`) so the token budget goes to the answer.

## Cost

Gemini 2.5 Flash is one of Google's cheaper models; a full probe run is a handful of
short requests, well within the $300 free trial. See the official
[Vertex AI generative pricing](https://cloud.google.com/vertex-ai/generative-ai/pricing)
for current per-token rates. Real models are **non-deterministic**, so findings vary
run-to-run; the ledger captures per-run evidence.

## Status

**Live-validated (2026-06-08):** `gemini-2.5-flash` in `us-east1` on project
`devsecbuddy`, authenticated with user ADC. The tile ladder holds on real Gemini —
`tile-unguarded` raises `data_exfiltration` findings (rubric / system-prompt leak)
while `tile-hardened` is clean. See also [anthropic-signup.md](anthropic-signup.md)
and [ai-engines.md](../ai-engines.md).
