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

## Status — roadmap M1 implemented ✅

The core library is implemented and tested (the contract, the deterministic
offline `MockEngine`, and the SQLite ledger), built verbatim against the Design
Bible in [`../docs/`](../docs/). `AnthropicEngine` and `VertexEngine` are present
but intentionally **unwired** (they raise `NotImplementedError`); they get
connected in roadmap **M6** once accounts exist. The backend (M2) and frontend
(M3) are not part of this milestone.

### Module map

| Module | Responsibility |
| --- | --- |
| `models.py` | All data models + shared vocabularies (`CATEGORIES`, `SEVERITIES`, `STATUSES`, `CATEGORY_OWASP`). |
| `engines/` | `AIEngine` protocol + `get_engine`; `mock.py` (the default, rigged, deterministic); `cloud.py` (Anthropic/Vertex stubs). |
| `adapters.py` | The `AppAdapter` protocol — the single shared tile contract. |
| `attack_library.py` | `load_vectors()` — loads + validates `attack-library/vectors/*.yaml`. |
| `profiler.py` | Phase 1 — `BaselineProfiler`. |
| `prober.py` | Phase 2 — `AdversarialProber` (the four `success_criteria` evaluators + bias counterfactuals). |
| `ledger.py` | Phase 3 — `Ledger` (5-table SQLite schema, findings, dedup, query). |
| `runner.py` | `run_assessment()` — the `open_run → … → close_run` orchestration. |
| `demo.py` | Reference resume-scorer tiles (the four-tile ladder) + a clean corpus. |
| `cli.py` | `python -m devsecbuddy` demo runner. |

### Quickstart

```bash
pip install -e .                  # or: pip install pyyaml pytest
python -m pytest -q               # 19 tests, incl. the tiles.md divergence table
python -m devsecbuddy --tile all  # run the full loop on all four tiles (MockEngine)
```

The demo writes findings to `data/ledger.db` (gitignored). The same probe suite
empties the ledger as you climb the tile ladder — `tile-unguarded` raises three
findings, `tile-hardened` raises none — which is the shift-left payoff the demo
exists to show. See [`../docs/tiles.md`](../docs/tiles.md).
