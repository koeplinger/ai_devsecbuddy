# Desirability Hypotheses

**Desirability** is the degree to which the solution is attractive and valuable to
its users. For AI DevSecBuddy the users are the bank's **AI-application
development teams**, **platform engineers**, and **security / compliance**
stakeholders. These hypotheses test whether those people actually want what the
tool offers — not whether we can build it.

Each hypothesis tests exactly one thing: its **We are right if** clause is a
single pass/fail threshold. See the framework and template in [README](README.md).

---

## D1

**Findings delivered into the workflow get remediated.**

> **We believe that** bank AI-application development teams will remediate
> AI-specific vulnerability findings when those findings are delivered into their
> existing UAT workflow and the central vulnerability ledger.
> **To verify that, we will** run a 4-week pilot in which 3–5 development teams
> connect a UAT application to DevSecBuddy and receive the full findings (repro +
> mitigation) in the ledger.
> **And measure** the share of high- and critical-severity findings that teams
> remediate within one sprint of detection.
> **We are right if** ≥60% of high/critical findings are remediated within one
> sprint.

*One tested thing:* whether in-workflow delivery produces remediation behavior.
*Note:* post-pilot satisfaction is observed as a secondary signal, not the pass
criterion (that attitudinal facet is out of scope for this hypothesis). To avoid
confounding, the action-rate is measured on the standard complete-view findings;
the view A/B in [D2](#d2) runs as a separate experiment. *Horizon:* 4 weeks.

---

## D2

**The complete finding package — not the label — drives the fix.**

> **We believe that** developers remediate a finding because it ships as a
> complete package — replicable repro *plus* tailored mitigation — rather than
> because it is merely labelled a vulnerability.
> **To verify that, we will** give the pilot teams two ledger views of the *same*
> findings — one complete (repro + mitigation), one showing only category and
> severity — and observe which findings get fixed.
> **And measure** the median time-to-first-fix for each view.
> **We are right if** findings shown as the complete package are remediated at
> least twice as fast as the label-only findings.

*One tested thing:* whether the repro+mitigation package (tested as a package)
speeds remediation versus a bare label. Isolating repro from mitigation would need
a third arm and is deliberately out of scope here. *Horizon:* within the same
4-week pilot, sequenced after D1's straight run.

---

## D3

**Fairness probes are valued at least as highly as injection probes.**

> **We believe that**, for hiring- and HR-adjacent AI applications, security and
> compliance stakeholders value the fairness/bias probes (the gender and ethnicity
> name-swap deltas) at least as highly as the prompt-injection probes.
> **To verify that, we will** demonstrate the four-tile ladder to at least 8
> stakeholders across security, compliance, and HR-technology and ask each to rank
> the four probe categories by perceived value.
> **And measure** the share of stakeholders who rank `bias_fairness` at or above
> `prompt_injection`.
> **We are right if** ≥70% of stakeholders rank `bias_fairness` at or above
> `prompt_injection`.

*One tested thing:* the relative demand for bias testing versus injection testing
for this use case (the success criterion is the same pairwise comparison the
belief makes). *Horizon:* one demo round (≤2 weeks).
