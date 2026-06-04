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

> Status: **docs-first prototype.** This folder is a placeholder in the current
> deliverable; there is no runtime UI code yet. The component breakdown, screens,
> and API contract are fixed by the canonical Design Bible and the docs under
> [`../docs/`](../docs/). Code is wired up in a later step of the roadmap.
