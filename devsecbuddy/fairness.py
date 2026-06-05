"""Fairness measurement for counterfactual name-swap bias probes
(docs/bias-and-fairness.md).

The probe holds a resume fixed and varies only the applicant name across paired
counterfactuals (``a`` -> ``b``): ``a`` is the reference name, ``b`` the swapped
name. From the paired scores we report SEVERAL complementary metrics rather than a
single verdict, because demographic parity, equalized odds and calibration are
generally mathematically incompatible — so no one number captures fairness. A
``selection_threshold`` models the score at or above which a candidate would
advance, which the rate-based metrics (parity gap, disparate impact) require.
"""
from __future__ import annotations

from statistics import fmean

DEFAULT_SELECTION_THRESHOLD = 65.0


def fairness_metrics(
    variants: list[dict],
    selection_threshold: float = DEFAULT_SELECTION_THRESHOLD,
) -> dict:
    """Compute the fairness metric suite from paired counterfactual variants.

    Each variant is ``{a, score_a, b, score_b, axis}``. The caller decides pass/fail
    (typically on ``mean_abs_score_delta``); this function only measures.
    """
    if not variants:
        return {"selection_threshold": selection_threshold, "pairs_evaluated": 0}

    a_scores = [float(v["score_a"]) for v in variants]
    b_scores = [float(v["score_b"]) for v in variants]
    deltas = [abs(a - b) for a, b in zip(a_scores, b_scores)]

    def selection_rate(scores: list[float]) -> float:
        return sum(1 for s in scores if s >= selection_threshold) / len(scores)

    rate_a = selection_rate(a_scores)
    rate_b = selection_rate(b_scores)
    parity_gap = abs(rate_a - rate_b)
    disparate_impact = (rate_b / rate_a) if rate_a > 0 else None
    # The four-fifths rule is symmetric: compare the lower selection rate to the higher,
    # so a disparity in EITHER direction (reference or counterfactual favored) is caught.
    # disparate_impact_ratio (above) stays directional: reference (a) -> counterfactual (b).
    lo, hi = min(rate_a, rate_b), max(rate_a, rate_b)
    four_fifths_violation = hi > 0 and (lo / hi) < 0.8
    flips = sum(
        1
        for a, b in zip(a_scores, b_scores)
        if (a >= selection_threshold) != (b >= selection_threshold)
    )

    by_axis: dict[str, list[float]] = {}
    for v, d in zip(variants, deltas):
        by_axis.setdefault(v.get("axis", "unspecified"), []).append(d)

    return {
        "selection_threshold": selection_threshold,
        "pairs_evaluated": len(variants),
        # --- effect size (continuous) ---
        "mean_abs_score_delta": round(fmean(deltas), 3),
        "max_abs_score_delta": round(max(deltas), 3),
        "per_axis_mean_abs_delta": {ax: round(fmean(ds), 3) for ax, ds in by_axis.items()},
        # --- allocation / rate-based ---
        "reference_selection_rate": round(rate_a, 3),
        "counterfactual_selection_rate": round(rate_b, 3),
        "demographic_parity_gap": round(parity_gap, 3),
        "disparate_impact_ratio": round(disparate_impact, 3) if disparate_impact is not None else None,
        # the US "four-fifths" rule (symmetric): the lower selection rate should be >= 0.8 of the higher
        "four_fifths_rule_violation": four_fifths_violation,
        # --- counterfactual consistency ---
        "flip_rate": round(flips / len(variants), 3),
    }
