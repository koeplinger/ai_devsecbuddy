# frontend/

The **AI DevSecBuddy** web UI: a Vite + React + TypeScript single-page app. It
provides the three operator-facing surfaces of the product — a **tiles grid**
(pick which AI-application incarnation to test), a **run console** (launch a
DevSecBuddy run and watch probes execute against the selected tile in the three
phases: passive learning, active probing, actionable reporting), and a **ledger
viewer** (browse findings recorded in the vulnerability ledger, with severity,
repro detail, and tailored mitigation guidance).

The frontend talks only to the FastAPI service in [`../backend/`](../backend/),
which in turn drives the [`devsecbuddy`](../devsecbuddy/) library. It holds no
security logic of its own — it is a thin presentation and control layer over the
backend run/report API.

## Status — roadmap M3 implemented ✅

The single-page app is implemented and builds clean (`tsc --noEmit` + `vite build`).
It renders the three surfaces over the M2 run/report API and holds no security or
engine logic. The run console animates the three phases while a (currently
synchronous) run is in flight; true progress streaming is future polish.

### Structure

| Path | Role |
| --- | --- |
| `src/api.ts` | Typed client for the backend (`/health`, `/tiles`, `/engines`, `/runs`, `/findings`). Base URL from `VITE_API_BASE` (default `http://localhost:8000`). |
| `src/types.ts` | TypeScript shapes mirroring the backend payloads. |
| `src/App.tsx` | App shell: boots health/tiles/engines, tab switching, the run flow, the finding drawer. |
| `src/components/TilesGrid.tsx` | The tiles grid + engine selector + per-tile run buttons. |
| `src/components/RunConsole.tsx` | Run progress, summary stats, and the run's findings. |
| `src/components/LedgerViewer.tsx` | Filterable findings table over `GET /findings`. |
| `src/components/FindingDetail.tsx` | Drawer with full repro / evidence / tailored mitigation. |
| `src/components/{FindingsTable,Badge}.tsx` | Shared findings table + severity/category badges. |

### Run it

```bash
# 1) start the backend (from the repo root):
uvicorn backend.main:app             # http://localhost:8000

# 2) start the frontend dev server:
npm --prefix frontend install
npm --prefix frontend run dev        # http://localhost:5173

# production build / preview:
npm --prefix frontend run build
npm --prefix frontend run preview
```

Set `VITE_API_BASE` (see [`.env.example`](.env.example)) if the backend is not on
`http://localhost:8000`. Then pick a tile, click **Run assessment**, and watch the
findings appear in the run console and the vulnerability ledger.
