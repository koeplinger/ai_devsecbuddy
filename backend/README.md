# backend/

The **AI DevSecBuddy** service: a FastAPI application with two
responsibilities. First, it **hosts the AI-application tiles** — the mock resume
scorer in four progressively hardened incarnations — each behind the single
shared `AppAdapter` contract so the identical probe suite runs unchanged against
every tile. Second, it exposes the **DevSecBuddy run/report API**: endpoints to
list tiles, start a run (passive learning -> active probing -> actionable
reporting), and read the vulnerability ledger. (Live run-progress streaming
arrives with the frontend slice in M3.)

The backend is the integration point of the system. It imports the
[`devsecbuddy`](../devsecbuddy/) library (the product) to perform baseline
profiling, adversarial probing, and ledger writes; it serves the
[`../frontend/`](../frontend/) SPA; it loads attack vectors from
[`../attack-library/`](../attack-library/); and it persists findings to the
SQLite ledger in [`../data/`](../data/).

## Status — roadmap M2 implemented ✅

The FastAPI service is implemented and tested (34 API tests). It hosts the four
reference tiles (from `devsecbuddy.demo`) behind the `AppAdapter` contract and
exposes the run/report API; it imports `devsecbuddy` and never reimplements
product logic. Engine selection is env-driven — `MockEngine` is the default; the cloud
engines `AnthropicEngine`, `VertexEngine`, and `GeminiProxyEngine` are implemented and
raise `EngineNotConfigured` (→ **503**) when their SDK or credentials are missing. Runs
complete synchronously (fast on the offline mock); live run-progress streaming is
deferred to the M3 frontend slice.

### Modules

| Module | Responsibility |
| --- | --- |
| `config.py` | `Settings` from env: `DEVSECBUDDY_ENGINE`, `DEVSECBUDDY_DB`, `DEVSECBUDDY_CORS_ORIGINS`. |
| `service.py` | `AssessmentService` — tile registry, engine selection, drives `run_assessment`, serves ledger reports. |
| `main.py` | The FastAPI app (`create_app`) and routes; `app` is the ASGI entrypoint. |

### API

| Method & path | Purpose |
| --- | --- |
| `GET /health`, `GET /` | Liveness and service info. |
| `GET /tiles` | List hosted tiles (id, name, guardrails, I/O schema). |
| `GET /engines` | List engines with their `implemented` and `configured` status (all four report `implemented: true`; `configured` reflects whether each engine's SDK/credentials are present). |
| `POST /runs` | Run the full three-phase assessment against a tile → summary + findings. Body: `{"tile_id": "...", "engine_name": "mock"}` (`engine_name` optional; unknown name → 400, cloud engine missing SDK/credentials → 503). |
| `GET /runs`, `GET /runs/{run_id}` | List runs / fetch one run with its findings. |
| `GET /findings` | Query the ledger (filters: `tile_id`, `category`, `severity`, `status`, `owasp_ref`, `vector_id`). |
| `GET /findings/{finding_id}` | One finding with full repro + evidence. |

### Run it

```bash
pip install -e ".[backend,dev]"      # fastapi + uvicorn + httpx (or use backend/requirements.txt)
uvicorn backend.main:app --reload    # http://127.0.0.1:8000  (OpenAPI docs at /docs)

# from another shell:
curl -X POST localhost:8000/runs -H 'content-type: application/json' -d '{"tile_id":"tile-unguarded"}'
```

`DEVSECBUDDY_ENGINE` selects the engine (default `mock`); `DEVSECBUDDY_DB` sets the
ledger path (default `data/ledger.db`, gitignored). Tests:
`pytest tests/test_backend_api.py`.
