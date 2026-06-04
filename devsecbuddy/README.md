# devsecbuddy/

**This folder is THE PRODUCT.** `devsecbuddy` is the shared Python library that
implements AI DevSecBuddy's automated adversarial AI-security testing. Every
other part of the repo — the backend, the tiles, the frontend — exists to host,
drive, or visualize what lives here.

The library implements the **three phases** of the tool and the **single shared
contract** reused across every tile:

- **Phase 1 — Passive learning:** `BaselineProfiler` observes normal
  request/response traffic for a target AI application and learns its behavioral
  `Baseline` without disrupting dev workflows.
- **Phase 2 — Active probing:** `AdversarialProber` uses the baseline plus the
  continuously-updated [attack library](../attack-library/) to probe the AI with
  adversarial requests (prompt injection, modal jailbreaking, data exfiltration,
  bias probes) and emit `ProbeResult`s.
- **Phase 3 — Actionable reporting:** `Ledger` records every confirmed
  vulnerability as a `Finding` — with replicable repro detail, severity, OWASP
  mapping, and tailored mitigation guidance — to the SQLite vulnerability ledger.

The library is provider-pluggable via the `AIEngine` interface
(**MockEngine**, **AnthropicEngine**, **VertexEngine**) and target-pluggable via
the `AppAdapter` protocol that every tile implements. See
[`../docs/ai-engines.md`](../docs/ai-engines.md) and
[`../docs/phases.md`](../docs/phases.md).

> Status: **docs-first prototype.** This folder is a placeholder in the current
> deliverable; there is no runtime library code yet. The public contract, data
> models, and phase responsibilities are fixed verbatim by the Design Bible and
> the docs under [`../docs/`](../docs/).
