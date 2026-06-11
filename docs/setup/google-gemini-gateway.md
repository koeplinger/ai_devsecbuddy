# Google Gemini via an API gateway — setup

This wires DevSecBuddy's `GeminiProxyEngine` (engine name **`gemini`**, roadmap **M6**) to
run the probe suite against **Gemini through a URL-based API gateway**: plain HTTPS with an
**API key in a header**, instead of Vertex's gcloud / Application-Default-Credentials login.
It uses no vendor SDK — just the standard-library `urllib` — so it's the right path when your
organisation fronts Google's models behind an internal gateway and hands you a **base URL +
key** rather than a GCP project.

This is the **third Google-model access path**, alongside:

| Engine | Provider path | Auth |
| --- | --- | --- |
| `vertex` | Gemini on **GCP Vertex AI** (`google-genai` SDK) | gcloud ADC (no key) |
| `gemini` | Gemini via an **API gateway** (`urllib`) | **API key in a header** |
| `anthropic` | **Claude** on the Anthropic API | API key |

> The gateway's base URL is **deployment-internal**, so it has **no default** and is never
> committed to this (public) repo — you supply it via the environment.

## What the gateway looks like

The engine speaks the shape of a gateway that exposes two routes under a base URL:

- **`POST {GEMINI_PROMPT_URL}`** — the scoring call. Body:
  `{"prompt": "...", "model_name": "...", "location": "...", "cost_tag": "..."}`
  (`cost_tag` is included only when configured). The reply is parsed for the model's text
  (the standard Gemini `candidates[].content.parts[].text` envelope, common flat fields like
  `text`/`response`, or the raw body as a fallback).
- **`POST {GEMINI_CUSTOM_COST_TAG_URL}`** — optional one-time cost-tag registration. Body:
  `{"cost_tag": "..."}`. Registered once per process; an "already exists" response is ignored.

## Configure it

Set these in `.env` (see [`.env.sample`](../../.env.sample)). Required:

```bash
DEVSECBUDDY_ENGINE=gemini           # make it the default engine (or pick "gemini" per run)
GEMINI_BASE_URL=https://…           # your gateway base URL (deployment-internal — no default)
GEMINI_API_KEY=…                    # your gateway key (blank by default)
```

Standard, with sensible defaults — override only if your gateway differs:

| Variable | Default | Meaning |
| --- | --- | --- |
| `GEMINI_API_KEY_HEADER` | `x-api-key` | header the API key is sent in |
| `GEMINI_MODEL_NAME` | `gemini-2.5-flash` | default model (selectable per run in the UI) |
| `GEMINI_LOCATION` | `us-central1` | location sent with each prompt |
| `GEMINI_PROMPT_URL` | `/api/v1/gemini/prompt` | path (or full URL) for the scoring call |
| `GEMINI_TIMEOUT_SECONDS` | `60` | per-request timeout |

Gateway-specific extras — **optional**, prefixed `GEMINI_CUSTOM_` because they are not part of
the general Gemini-over-HTTP shape. Leave the cost tag blank to disable cost attribution
entirely (nothing is registered and none is sent with the prompt):

| Variable | Default | Meaning |
| --- | --- | --- |
| `GEMINI_CUSTOM_COST_TAG` | _(blank → disabled)_ | cost-attribution tag sent with each prompt |
| `GEMINI_CUSTOM_COST_TAG_URL` | `/api/v1/tag` | where the cost tag is registered |

## Notes

- The gateway takes a **single prompt** (no separate system field), so the scoring rubric is
  folded into the top of the prompt.
- A model selected in the UI is validated against the offered Gemini catalog
  (`devsecbuddy/defaults/models.json` — the 2.5 and 3.x series); if your gateway names models
  differently, edit that file (the `gemini` entry) or set `GEMINI_MODEL_NAME` and run without
  a per-request override.
- A `429` from the gateway is retried by the rate-limit wrapper (escalating backoff), the same
  as the other cloud engines.
- Real models are non-deterministic — findings vary run-to-run; the ledger captures per-run
  evidence. The learning phase re-asks on a malformed/0 score (up to 3 retries).
