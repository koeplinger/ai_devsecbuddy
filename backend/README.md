# backend/

The **AI DevSecBuddy** service: a FastAPI application with two
responsibilities. First, it **hosts the AI-application tiles** — the mock resume
scorer in four progressively hardened incarnations — each behind the single
shared `AppAdapter` contract so the identical probe suite runs unchanged against
every tile. Second, it exposes the **DevSecBuddy run/report API**: endpoints to
list tiles, start a run (passive learning -> active probing -> actionable
reporting), stream progress, and read the vulnerability ledger.

The backend is the integration point of the system. It imports the
[`devsecbuddy`](../devsecbuddy/) library (the product) to perform baseline
profiling, adversarial probing, and ledger writes; it serves the
[`../frontend/`](../frontend/) SPA; it loads attack vectors from
[`../attack-library/`](../attack-library/); and it persists findings to the
SQLite ledger in [`../data/`](../data/).

> Status: **docs-first prototype.** This folder is a placeholder in the current
> deliverable; there is no runtime service code yet. Endpoint shapes, tile
> registration, and engine selection (MockEngine by default; AnthropicEngine and
> VertexEngine designed but not yet wired) are fixed by the Design Bible and the
> docs under [`../docs/`](../docs/).
