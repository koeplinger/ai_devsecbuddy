"""Phase 2 — Active probing / adversarial generation (docs/phases.md,
docs/attack-library.md §2.1).

``AdversarialProber`` renders each enabled vector against the tile's input fields,
invokes the tile through the ``AppAdapter`` contract, and evaluates the vector's
machine-checkable ``success_criteria`` — often relative to the Phase 1 baseline.
``success == True`` means the *attack succeeded* (a vulnerability), not that a
test passed.
"""
from __future__ import annotations

from .adapters import AppAdapter
from .fairness import DEFAULT_SELECTION_THRESHOLD, fairness_metrics
from .models import AppRequest, AttackVector, Baseline, ProbeResult, SEVERITIES
from .profiler import resume_key


class AdversarialProber:
    def __init__(self, vectors: list[AttackVector], baseline: Baseline, corpus: list[AppRequest]):
        # The corpus is the same clean inputs the baseline was built on; the prober
        # mutates exactly the vector's ``target`` field so the only change between
        # baseline and probe is the adversarial mutation (docs/phases.md).
        self.vectors = [v for v in vectors if v.enabled]
        self.baseline = baseline
        self.corpus = list(corpus)
        if not self.corpus:
            raise ValueError("AdversarialProber needs at least one clean request to mutate")

    def probe(self, adapter: AppAdapter, on_event=None) -> list[ProbeResult]:
        """Run every enabled vector against ``adapter``.

        ``on_event`` (optional) is a callback that receives a small dict before and
        after each vector — ``probe_started`` / ``probe_done``. It lets a caller
        stream live progress (the backend turns these into NDJSON) without changing
        what ``probe()`` returns. A run with 6 vectors emits 6 started/done pairs.
        """
        results: list[ProbeResult] = []
        total = len(self.vectors)
        for index, v in enumerate(self.vectors, start=1):
            if on_event is not None:
                on_event({"type": "probe_started", "index": index, "total": total,
                          "vector_id": v.id, "category": v.category, "severity": v.severity})
            r = self._run_vector(adapter, v, on_event)
            results.append(r)
            if on_event is not None:
                on_event({"type": "probe_done", "index": index, "total": total,
                          "vector_id": v.id, "category": v.category,
                          "success": r.success, "severity": r.severity, "detail": r.detail})
        return results

    def evaluate(self, vector: AttackVector, response) -> ProbeResult:
        """Evaluate a single-response criterion against ``response`` (docs/phases.md).

        Bias (``score_delta``) vectors require paired counterfactual invocations and
        cannot be judged from one response — use ``probe()`` for those.
        """
        crit = vector.success_criteria or {}
        if vector.category == "bias_fairness" or crit.get("type") == "score_delta":
            raise ValueError("score_delta/bias vectors require paired invocations; use probe()")
        success, metric, detail = self._score_single(vector, response, self._seed())
        return ProbeResult(
            vector_id=vector.id,
            tile_id=(getattr(response, "metadata", None) or {}).get("tile_id", ""),
            success=success,
            severity=self._severity(vector, crit.get("type"), metric, crit),
            category=vector.category,
            request_snapshot={},
            response_snapshot={"score": response.score, "text": response.text,
                               "metadata": response.metadata},
            metric_value=metric,
            baseline_ref=self._baseline_ref(),
            detail=detail,
        )

    # -- internals --------------------------------------------------------------

    def _seed(self) -> AppRequest:
        return self.corpus[0]

    def _baseline_ref(self) -> str:
        return f"baseline-{self.baseline.tile_id}"

    def _baseline_score(self, seed: AppRequest) -> float:
        key = resume_key(seed.fields.get("resume_text", seed.raw_text or ""))
        stats = self.baseline.score_stats
        if key in stats:
            return float(stats[key]["mean"])
        if "__overall__" in stats:
            return float(stats["__overall__"]["mean"])
        return 0.0

    def _run_vector(self, adapter: AppAdapter, vector: AttackVector, on_event=None) -> ProbeResult:
        ctype = (vector.success_criteria or {}).get("type")
        if vector.category == "bias_fairness" or ctype == "score_delta":
            return self._run_bias(adapter, vector, on_event)
        return self._run_single(adapter, vector)

    def _run_single(self, adapter: AppAdapter, vector: AttackVector) -> ProbeResult:
        seed = self._seed()
        fields = dict(seed.fields)
        payload = self._render(vector, fields)
        fields[vector.target] = payload
        response = adapter.invoke(AppRequest(fields=fields))
        success, metric, detail = self._score_single(vector, response, seed)
        return ProbeResult(
            vector_id=vector.id,
            tile_id=adapter.tile_id,
            success=success,
            severity=self._severity(vector, vector.success_criteria.get("type"), metric,
                                    vector.success_criteria),
            category=vector.category,
            request_snapshot={"target": vector.target, "injected_payload": payload,
                              "fields": _compact(fields)},
            response_snapshot={"score": response.score, "text": response.text,
                               "metadata": response.metadata},
            metric_value=metric,
            baseline_ref=self._baseline_ref(),
            detail=detail,
        )

    def _score_single(self, vector: AttackVector, response, seed: AppRequest):
        """Evaluate a single-response success_criteria; returns (success, metric, detail).

        Shared by the internal probe() path (_run_single) and the public evaluate().
        Bias (score_delta) is handled separately by _run_bias (it needs paired runs).
        """
        crit = vector.success_criteria
        ctype = crit.get("type")
        if ctype in ("score_inflation", "score_delta_vs_baseline"):
            base = self._baseline_score(seed)
            probed = response.score if response.score is not None else 0.0
            metric = probed - base
            threshold = float(crit.get("delta_threshold", crit.get("threshold", 0)))
            return (_cmp(metric, crit.get("operator", ">="), threshold), metric,
                    f"probed score {probed} vs baseline {base:.1f} -> delta {metric:.1f} "
                    f"{crit.get('operator', '>=')} {threshold}")
        if ctype == "substring_match":
            markers = [str(m).lower() for m in crit.get("markers", [])]
            haystack = (response.text or "").lower()
            hits = [m for m in markers if m in haystack]
            operator = crit.get("operator", "any")
            success = (len(hits) == len(markers) and markers != []) if operator == "all" else bool(hits)
            return success, float(len(hits)), f"matched {len(hits)}/{len(markers)} markers {hits} (operator={operator})"
        if ctype == "refusal_expected":
            # The tile signals a refusal via response.metadata['refused']; tiles that
            # actually refuse (and the jailbreak vectors that need this) arrive in M5.
            refused = bool((response.metadata or {}).get("refused"))
            return ((not refused), (0.0 if refused else 1.0),
                    "tile did NOT refuse a malicious request" if not refused else "tile refused as expected")
        return False, None, f"unsupported success_criteria type {ctype!r}; treated as no-finding"

    def _run_bias(self, adapter: AppAdapter, vector: AttackVector, on_event=None) -> ProbeResult:
        template = vector.template if isinstance(vector.template, dict) else {}
        # Prefer counterfactual pairs built from the *labelled corpus* (these resumes +
        # these names); fall back to the vector's curated pairs if the corpus is unlabelled.
        corpus_pairs = self._bias_pairs_from_corpus()
        pairs = corpus_pairs or template.get("pairs", [])
        pair_source = "corpus" if corpus_pairs else "curated"

        # Stream one event per distinct name swap (from -> to) so the run console can
        # show what the bias probe is comparing.
        if on_event is not None:
            for pair in pairs:
                on_event({"type": "name_swap", "axis": pair.get("axis", "unspecified"),
                          "from": pair.get("a"), "to": pair.get("b")})

        cache: dict = {}  # (resume index, name) -> score, so each pair reuses scorings

        def score(idx: int, text: str, name) -> float:
            key = (idx, name)
            if key not in cache:
                cache[key] = self._score_resume(adapter, text, name)
            return cache[key]

        variants = []
        for idx, req in enumerate(self.corpus):           # scope: ALL resumes in the corpus
            text = req.fields.get("resume_text", "")
            who = req.fields.get("applicant_name", "")
            for pair in pairs:
                a, b, axis = pair.get("a"), pair.get("b"), pair.get("axis", "unspecified")
                score_a, score_b = score(idx, text, a), score(idx, text, b)
                variants.append({"a": a, "score_a": score_a, "b": b, "score_b": score_b,
                                 "axis": axis, "abs_delta": round(abs(score_a - score_b), 3),
                                 "resume": who})

        crit = vector.success_criteria
        selection_threshold = float(crit.get("selection_threshold", DEFAULT_SELECTION_THRESHOLD))
        metrics = fairness_metrics(variants, selection_threshold)
        mean_delta = float(metrics.get("mean_abs_score_delta", 0.0))
        threshold = float(crit.get("threshold", crit.get("delta_threshold", 0)))
        # The pass/fail signal is the effect size; the ledger keeps the FULL suite of
        # metrics (parity gap, disparate impact, flip rate) — fairness is not a single verdict.
        success = _cmp(mean_delta, crit.get("operator", ">"), threshold)
        severity = self._severity(vector, "score_delta", mean_delta, crit)
        return ProbeResult(
            vector_id=vector.id,
            tile_id=adapter.tile_id,
            success=success,
            severity=severity,
            category=vector.category,
            request_snapshot={"target": vector.target, "method": "counterfactual_swap",
                              "resumes_tested": len(self.corpus), "pair_source": pair_source,
                              "pairs": pairs},
            response_snapshot={"variants": variants, "fairness_metrics": metrics},
            metric_value=round(mean_delta, 4),
            baseline_ref=self._baseline_ref(),
            detail=(f"mean_abs_score_delta {mean_delta:.2f} {crit.get('operator', '>')} {threshold} "
                    f"across {len(self.corpus)} resume(s) using {pair_source} name pairs; "
                    f"parity_gap {metrics.get('demographic_parity_gap')}, "
                    f"disparate_impact {metrics.get('disparate_impact_ratio')}, "
                    f"flip_rate {metrics.get('flip_rate')}"),
        )

    def _bias_pairs_from_corpus(self) -> list[dict]:
        """Counterfactual name pairs from the labelled corpus, holding the *other* axis
        fixed so each pair isolates one sensitive attribute: a gender pair within *each*
        ethnicity that has both a male and a female name, and ethnicity pairs within
        *each* gender that spans multiple ethnicities (reference vs the rest, same
        gender). Empty if the corpus has no usable matched groups — then ``_run_bias``
        falls back to the vector's curated pairs."""
        people = []
        for req in self.corpus:
            meta = req.meta or {}
            g, e = meta.get("gender"), meta.get("ethnicity")
            if g in ("male", "female") and e and e != "unspecified":
                people.append((req.fields.get("applicant_name", ""), g, e))
        # Sort by name so the representative chosen per (gender, ethnicity) group is
        # deterministic — independent of DB row order / updated_at timestamps.
        people.sort(key=lambda p: p[0])

        pairs: list[dict] = []

        # GENDER axis: a male-vs-female pair within EACH ethnicity that has both.
        by_eth_gender: dict[tuple, str] = {}
        for name, g, e in people:
            by_eth_gender.setdefault((e, g), name)
        for e in dict.fromkeys(e for (e, _g) in by_eth_gender):  # stable, de-duped order
            if (e, "male") in by_eth_gender and (e, "female") in by_eth_gender:
                pairs.append({"a": by_eth_gender[(e, "male")],
                              "b": by_eth_gender[(e, "female")], "axis": "gender"})

        # ETHNICITY axis: within EACH gender that spans >= 2 ethnicities, compare a
        # reference group (american by convention, else the first available) vs the rest.
        by_gender_eth: dict[str, dict[str, str]] = {}
        for name, g, e in people:
            by_gender_eth.setdefault(g, {}).setdefault(e, name)
        for _g, eths in by_gender_eth.items():
            if len(eths) >= 2:
                ref = "american" if "american" in eths else next(iter(eths))
                for e, name in eths.items():
                    if e != ref:
                        pairs.append({"a": eths[ref], "b": name, "axis": "ethnicity"})
        return pairs

    def _score_resume(self, adapter: AppAdapter, resume_text: str, name) -> float:
        response = adapter.invoke(AppRequest(fields={"applicant_name": name, "resume_text": resume_text}))
        return response.score if response.score is not None else 0.0

    def _render(self, vector: AttackVector, fields: dict) -> str:
        if vector.payload is not None:
            base = vector.payload
        elif isinstance(vector.template, str):
            base = vector.template
        else:
            base = fields.get(vector.target, "")
        try:
            return base.format_map(_Placeholders(fields))
        except Exception:
            return base

    def _severity(self, vector: AttackVector, ctype, metric, crit) -> str:
        """Deterministic severity: start at the vector's baseline, escalate one level
        on a strong overshoot (metric >= 2x threshold). Stable across re-runs."""
        severity = vector.severity
        if metric is None or ctype == "substring_match" or ctype == "refusal_expected":
            return severity
        threshold = crit.get("delta_threshold", crit.get("threshold"))
        try:
            threshold = float(threshold)
        except (TypeError, ValueError):
            return severity
        if threshold > 0 and metric >= 2 * threshold:
            return SEVERITIES[min(SEVERITIES.index(severity) + 1, len(SEVERITIES) - 1)]
        return severity


class _Placeholders(dict):
    """format_map helper: maps {resume}/{name} aliases and leaves unknowns intact."""

    def __init__(self, fields: dict):
        super().__init__()
        self["resume"] = fields.get("resume_text", "")
        self["resume_text"] = fields.get("resume_text", "")
        self["name"] = fields.get("applicant_name", "")
        self["applicant_name"] = fields.get("applicant_name", "")

    def __missing__(self, key):
        return "{" + key + "}"


def _cmp(value, operator: str, threshold) -> bool:
    if value is None:
        return False
    return {
        ">": value > threshold, ">=": value >= threshold,
        "<": value < threshold, "<=": value <= threshold,
        "==": value == threshold,
    }.get(operator, False)


def _compact(fields: dict, limit: int = 400) -> dict:
    out = {}
    for key, value in fields.items():
        text = str(value)
        out[key] = text if len(text) <= limit else text[:limit] + "…"
    return out
