# Feasibility Hypotheses

**Feasibility** is whether the idea can be realistically and effectively executed
— the technical and operational capability to deliver it, given infrastructure,
resources, expertise, and implementation constraints. These hypotheses test
whether AI DevSecBuddy's core technical bets actually hold.

Each hypothesis tests exactly one thing: its **We are right if** clause is a
single pass/fail threshold. See the framework and template in [README](README.md).

---

## F1

**One contract runs the same probe suite across structurally different apps.**

> **We believe that** a single `AppAdapter` contract lets the existing probe
> suite run, unchanged, against structurally different NLP/LLM backends across the
> bank — not only the resume scorer.
> **To verify that, we will** wrap at least three distinct internal AI
> applications (for example a document summarizer, a customer-support chatbot, and
> the resume scorer) as `AppAdapter`s and run the existing `AdversarialProber`
> against each, recording any change required to shared code.
> **And measure** the number of changes required to the prober and core library
> per new application (and, as supporting evidence, the share of enabled vectors
> that execute unmodified).
> **We are right if** each new application integrates with **zero** changes to the
> prober and core library.

*One tested thing:* whether the shared-contract abstraction generalizes beyond the
demo (zero core changes per new app). *Horizon:* one integration sprint (~2–3
weeks).

---

## F2

**Findings transfer from the deterministic mock to real models.**

> **We believe that** real production models swapped in behind the pluggable
> `AIEngine` interface (`AnthropicEngine`/Claude, then `VertexEngine`) exhibit the
> same vulnerability *classes* the deterministic `MockEngine` is designed to
> surface, so findings transfer from the offline mock to live models.
> **To verify that, we will** wire `AnthropicEngine` behind `tile-unguarded` —
> changing no code outside the engine adapter — and run the existing injection,
> exfiltration, and bias suite against it over 30 runs, comparing the finding
> categories to the `MockEngine` baseline.
> **And measure** the share of mock-predicted vulnerability classes that also
> appear on the live model.
> **We are right if** ≥80% of the mock-predicted vulnerability classes reproduce
> on the live model.

*One tested thing:* whether the deterministic mock is a faithful enough proxy that
its predicted vulnerability classes transfer to real models. (The "no code outside
the adapter" constraint is part of the method, not the success bar.) *Horizon:*
after M6 engine wiring (~1–2 weeks of testing). *Depends on:* an Anthropic
account/key.

---

## F3

**A passively-learned baseline is usable for probing.**

> **We believe that** the `BaselineProfiler` can learn, from passively-observed
> real UAT traffic (without changes to the target application), a behavioral
> baseline stable enough to drive valid Phase-2 findings.
> **To verify that, we will** passively capture one week of UAT request/response
> traffic from a target AI application, build a baseline from it, run a Phase-2
> probing pass against that baseline, and compare the result to a baseline built
> from a controlled clean corpus.
> **And measure** whether the passively-learned baseline reproduces the same
> injection and bias findings, at their documented severities, that the
> controlled-corpus baseline produces.
> **We are right if** the passively-learned baseline reproduces those findings at
> their documented severities (i.e. it is usable for probing).

*One tested thing:* whether a baseline learned from passive real traffic is
representative/stable enough to measure deviations against. Non-disruptive capture
(read-only, no target-app code change) is the *manner* of the experiment, not a
separate success metric. *Horizon:* the M7 baseline milestone (~1 week capture +
analysis).
