# attack-library/

The **continuously-updated adversarial attack-vector library** that powers
AI DevSecBuddy's active-probing phase. Vectors are plain **YAML data** (not
code), one logical attack per record, kept under [`vectors/`](vectors/). The
[`devsecbuddy`](../devsecbuddy/) library loads them, and the `AdversarialProber`
runs the enabled vectors against whichever tile is under test.

Vectors are grouped by **category** — prompt injection, modal jailbreaking, data
exfiltration, and bias/fairness probes — and each is tagged with an OWASP LLM
Top 10 reference, a severity, machine-checkable `success_criteria`, and tailored
`mitigation` guidance. Because the library is data, it can be extended and
versioned independently of the engine; new vectors flow into every tile's next
run automatically. The exact YAML schema is fixed by the Design Bible and
documented in [`../docs/attack-library.md`](../docs/attack-library.md).

> Status: **docs-first prototype.** The files under [`vectors/`](vectors/) are
> **inert illustrative samples** that demonstrate the schema; they are not
> executed by any runtime in this deliverable. The full, curated vector set is
> populated in a later step of the roadmap.
