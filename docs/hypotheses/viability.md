# Viability Hypotheses

**Viability** is whether the idea is economically sustainable — whether the value
it creates exceeds its cost over the long term. AI DevSecBuddy is an **internal
platform capability**, so "financial value" is measured as **cost avoidance, risk
reduction, and efficiency** rather than external revenue: reduced security-review
effort, avoided late-stage remediation and incident exposure, and a knowledge base
that lowers the cost of securing each additional AI application.

Each hypothesis tests exactly one thing: its **We are right if** clause is a
single pass/fail threshold. See the framework and template in [README](README.md).

---

## V1

**Automation cuts the cost of pre-production AI security review.**

> **We believe that** DevSecBuddy lowers the cost of pre-production AI security
> review by automating adversarial testing that is today performed manually or
> skipped.
> **To verify that, we will**, over one quarter, review five AI applications both
> ways — manual red-team review and automated DevSecBuddy runs — tracking effort
> and findings, and holding a guardrail that the automated runs surface at least as
> many valid high/critical findings as the manual review (so effort is not traded
> for detection quality).
> **And measure** the security-engineer hours spent per application under each
> approach.
> **We are right if** DevSecBuddy reduces security-engineer hours per application
> by ≥50%.

*One tested thing:* the efficiency gain (hours per app). Detection non-inferiority
is an explicit guardrail in the method, not a second success metric. *Horizon:*
one quarter.

---

## V2

**Shift-left detection avoids more than it costs.**

> **We believe that** catching AI-specific vulnerabilities in UAT is materially
> cheaper for the bank than remediating them in production or absorbing an incident
> (for example a publicized hiring-bias or data-exfiltration event).
> **To verify that, we will**, over two quarters, record the vulnerabilities
> DevSecBuddy catches pre-production and cost each one using the bank's existing
> incident- and remediation-cost model, comparing against the historical cost of
> equivalent issues found late.
> **And measure** the estimated avoided remediation-and-exposure cost attributable
> to pre-production detection, set against the tool's total build-and-run cost.
> **We are right if** the estimated avoided cost exceeds the tool's total cost by
> at least **3:1** within two quarters.

*One tested thing:* whether early detection produces a positive, defensible return
(≥3:1). *Horizon:* two quarters.

---

## V3

**The knowledge base compounds; marginal cost per app falls.**

> **We believe that** the central vulnerability ledger acts as a reusable internal
> knowledge base whose value compounds as more AI applications are onboarded,
> lowering the marginal cost of securing each additional application.
> **To verify that, we will** onboard AI applications onto DevSecBuddy sequentially
> over two quarters and track, per application, the onboarding-plus-assessment cost
> and the share of findings resolved using mitigation guidance already present in
> the ledger (the reuse mechanism that would explain a falling cost curve).
> **And measure** the marginal cost per newly onboarded application (and, as the
> explanatory mechanism, the reuse rate of existing guidance).
> **We are right if** the marginal cost per application falls by ≥30% between the
> first and the tenth onboarded application.

*One tested thing:* whether the cost of securing each additional app declines as
the portfolio grows (the reuse rate is measured as the explanatory mechanism, not
a second pass/fail). *Horizon:* two quarters (≥10 apps onboarded).
