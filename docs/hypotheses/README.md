# Validation Hypotheses

This folder holds the **core assumptions** behind AI DevSecBuddy, written as
testable hypotheses so they can be validated through experimentation and
observation **before** the bank commits fully to the idea. This is the
design-thinking discipline: surface the riskiest assumptions early, design cheap
experiments to test them, and let evidence — not opinion — decide what to build.

## The desirability / feasibility / viability framework

The three lenses together cover what an idea needs to succeed:

| Lens | Question it answers | File |
| --- | --- | --- |
| **Desirability** | Do the end-users find the solution attractive and valuable? | [desirability.md](desirability.md) |
| **Feasibility** | Can we realistically and effectively build and operate it (technically and operationally)? | [feasibility.md](feasibility.md) |
| **Viability** | Is it economically sustainable — does the value it creates exceed its cost over the long term? | [viability.md](viability.md) |

## What makes a good hypothesis

Every hypothesis below is written to be:

- **Testable** — it can be shown true or false from evidence.
- **Precise** — it states the *what*, the *who*, and the *when*.
- **Discrete** — it tests exactly one thing.

## Template

Each hypothesis follows one structure:

> **We believe that** … **To verify that, we will** … **And measure** … **We are right if** …

## Index

| ID | Lens | Hypothesis (short form) |
| --- | --- | --- |
| [D1](desirability.md#d1) | Desirability | Findings delivered into the UAT workflow + ledger get remediated |
| [D2](desirability.md#d2) | Desirability | The complete repro + mitigation package (not the label) drives the fix |
| [D3](desirability.md#d3) | Desirability | Bias/fairness probes valued at least as highly as injection probes |
| [F1](feasibility.md#f1) | Feasibility | One `AppAdapter` contract covers structurally different AI apps |
| [F2](feasibility.md#f2) | Feasibility | Real models reproduce the vulnerability classes the mock predicts |
| [F3](feasibility.md#f3) | Feasibility | A usable baseline can be learned passively from real UAT traffic |
| [V1](viability.md#v1) | Viability | Automation cuts security-engineer effort vs. manual review |
| [V2](viability.md#v2) | Viability | Shift-left detection avoids more than it costs (late remediation) |
| [V3](viability.md#v3) | Viability | The ledger compounds; marginal cost per onboarded app falls |

> **Status: unvalidated.** These are assumptions to be tested, not established
> facts. Each will be marked validated / invalidated / inconclusive as its
> experiment completes. They describe the *target product* (the full
> [roadmap](../roadmap.md)), not only the milestone shipped so far.

See the project [README](../../README.md) and the [architecture](../architecture.md),
[tiles](../tiles.md), and [bias-and-fairness](../bias-and-fairness.md) docs for the
concept these hypotheses test.
