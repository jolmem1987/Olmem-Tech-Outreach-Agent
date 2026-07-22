"""Admin-editable scoring criteria and operational knobs.

The agent's behaviour is tuned by two kinds of values:

* the **fit-score gate** — the minimum total score and per-component minimums a
  prospect must clear before an email is allowed;
* **operational knobs** — daily send limit, contact cooldown, autonomous-send
  on/off, whether named (non role-based) emails are allowed, and the discovery
  regions;
* the **rubric weights** — the maximum points each scoring dimension may
  contribute (problem evidence, offer alignment, customer fit, contact quality,
  timing signal).

Defaults come from the environment/`Settings`. The admin panel can override any
of them; overrides are stored as a single JSON row in `outreach_settings` and
merged on top of the defaults by :func:`get_criteria`. Nothing here sends email
or calls an LLM — it only resolves configuration.
"""
from __future__ import annotations

from typing import Any

from outreach.config import get_settings
from outreach.db import connection, json_dumps

# Component maxima that reproduce the original hardcoded rubric.
DEFAULT_WEIGHTS: dict[str, int] = {
    "problem_evidence": 35,
    "offer_alignment": 30,
    "customer_fit": 15,
    "contact_quality": 10,
    "timing_signal": 10,
}
WEIGHT_KEYS = list(DEFAULT_WEIGHTS.keys())

# Per-component minimums that were previously hardcoded in FitScorer.validate.
DEFAULT_GATE_MINIMUMS = {
    "min_problem_evidence": 20,
    "min_offer_alignment": 20,
    "min_contact_quality": 8,
}

BOOL_KEYS = ("autonomous_send", "allow_named_public_emails")
INT_KEYS = (
    "min_fit_score",
    "min_problem_evidence",
    "min_offer_alignment",
    "min_contact_quality",
    "daily_send_limit",
    "contact_cooldown_days",
)


def default_criteria() -> dict[str, Any]:
    """The effective criteria when nothing has been overridden."""
    s = get_settings()
    return {
        "min_fit_score": int(s.min_fit_score),
        "min_problem_evidence": DEFAULT_GATE_MINIMUMS["min_problem_evidence"],
        "min_offer_alignment": DEFAULT_GATE_MINIMUMS["min_offer_alignment"],
        "min_contact_quality": DEFAULT_GATE_MINIMUMS["min_contact_quality"],
        "daily_send_limit": int(s.daily_send_limit),
        "contact_cooldown_days": int(s.contact_cooldown_days),
        "autonomous_send": bool(s.autonomous_send),
        "allow_named_public_emails": bool(s.allow_named_public_emails),
        "discovery_regions": s.discovery_regions,
        "weights": dict(DEFAULT_WEIGHTS),
    }


def _as_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in {"1", "true", "on", "yes"}


def _as_int(value: Any, low: int, high: int, fallback: int) -> int:
    try:
        n = int(float(value))
    except (TypeError, ValueError):
        return fallback
    return max(low, min(high, n))


def normalize_criteria(raw: Any, base: dict[str, Any] | None = None) -> dict[str, Any]:
    """Merge a partial/untrusted override map onto the defaults, coercing types
    and clamping every value into a safe range."""
    result = base if base is not None else default_criteria()
    result = {**result, "weights": dict(result["weights"])}
    if not isinstance(raw, dict):
        return result

    result["min_fit_score"] = _as_int(raw.get("min_fit_score", result["min_fit_score"]), 0, 500, result["min_fit_score"])
    result["min_problem_evidence"] = _as_int(raw.get("min_problem_evidence", result["min_problem_evidence"]), 0, 100, result["min_problem_evidence"])
    result["min_offer_alignment"] = _as_int(raw.get("min_offer_alignment", result["min_offer_alignment"]), 0, 100, result["min_offer_alignment"])
    result["min_contact_quality"] = _as_int(raw.get("min_contact_quality", result["min_contact_quality"]), 0, 100, result["min_contact_quality"])
    result["daily_send_limit"] = _as_int(raw.get("daily_send_limit", result["daily_send_limit"]), 1, 500, result["daily_send_limit"])
    result["contact_cooldown_days"] = _as_int(raw.get("contact_cooldown_days", result["contact_cooldown_days"]), 0, 3650, result["contact_cooldown_days"])

    if "autonomous_send" in raw:
        result["autonomous_send"] = _as_bool(raw["autonomous_send"])
    if "allow_named_public_emails" in raw:
        result["allow_named_public_emails"] = _as_bool(raw["allow_named_public_emails"])
    if "discovery_regions" in raw and isinstance(raw["discovery_regions"], str):
        cleaned = ",".join(part.strip() for part in raw["discovery_regions"].split(",") if part.strip())
        if cleaned:
            result["discovery_regions"] = cleaned

    weights_in = raw.get("weights")
    if isinstance(weights_in, dict):
        for key in WEIGHT_KEYS:
            if key in weights_in:
                result["weights"][key] = _as_int(weights_in[key], 0, 100, result["weights"][key])
    return result


def _read_overrides() -> dict[str, Any]:
    try:
        with connection() as conn:
            row = conn.execute("SELECT criteria_json FROM outreach_settings WHERE id = 1").fetchone()
    except Exception:
        return {}
    if not row:
        return {}
    data = row["criteria_json"]
    return data if isinstance(data, dict) else {}


def get_criteria() -> dict[str, Any]:
    """Effective criteria: defaults with any stored overrides applied."""
    return normalize_criteria(_read_overrides())


def save_criteria(payload: Any) -> dict[str, Any]:
    """Validate and persist criteria overrides; returns the effective criteria."""
    effective = normalize_criteria(payload)
    with connection() as conn:
        conn.execute(
            """
            INSERT INTO outreach_settings (id, criteria_json, updated_at)
            VALUES (1, %s::jsonb, NOW())
            ON CONFLICT (id) DO UPDATE SET criteria_json = EXCLUDED.criteria_json, updated_at = NOW()
            """,
            (json_dumps(effective),),
        )
        conn.commit()
    return effective


def reset_criteria() -> dict[str, Any]:
    """Clear all overrides so the configured defaults apply again."""
    with connection() as conn:
        conn.execute(
            """
            INSERT INTO outreach_settings (id, criteria_json, updated_at)
            VALUES (1, '{}'::jsonb, NOW())
            ON CONFLICT (id) DO UPDATE SET criteria_json = '{}'::jsonb, updated_at = NOW()
            """
        )
        conn.commit()
    return default_criteria()


def total_possible(criteria: dict[str, Any]) -> int:
    return sum(int(criteria["weights"][key]) for key in WEIGHT_KEYS)


def score_instructions(criteria: dict[str, Any]) -> str:
    """Build the LLM scoring rubric text using the configured component maxima."""
    w = criteria["weights"]
    total = total_possible(criteria)
    gate = criteria["min_fit_score"]
    return f"""
Evaluate whether one current company offer is a strong, evidence-based match for this
business. The number is a fit score, not a probability. Select at most one offer.

Use this exact {total}-point rubric:
- problem_evidence, 0-{w['problem_evidence']}: concrete website evidence of a real problem the offer solves;
- offer_alignment, 0-{w['offer_alignment']}: direct alignment between that problem and an explicit offer;
- customer_fit, 0-{w['customer_fit']}: explicit target-customer or operational fit;
- contact_quality, 0-{w['contact_quality']}: a publicly posted appropriate business email and source URL;
- timing_signal, 0-{w['timing_signal']}: current evidence such as growth, hiring, launch, expansion, or a
  recently described problem. Do not invent timing.

A business should normally remain below {gate} unless there is concrete problem evidence,
a direct offer match, at least two independent evidence facts, and a valid public business
email. Industry alone is insufficient. Return contradictions for any no-solicitation text,
closed business, existing strong solution that removes the need, unsupported contact,
or mismatch. Do not select an offer that is absent from the provided catalog.
""".strip()
