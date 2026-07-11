"""
labels.py — User-facing transparency labels.

A non-technical creator on a creative platform should never see a raw
float. They should see a short label plus one sentence explaining what it
means and what they can do about it. This module is the ONLY place that
translates numbers into words, so tone and honesty stay consistent.

Design rule: confidence gates everything. A high raw_score with low
confidence must NEVER produce a confident-sounding label like "AI-Generated."
It's better to say "Uncertain" and route to human review than to hand a
creator a label they can't dispute meaningfully.
"""

# Confidence below this -> we refuse to make a directional claim at all.
CONFIDENCE_FLOOR = 0.35

# Raw-score thresholds, only consulted once confidence clears the floor.
HIGH_AI_THRESHOLD = 0.70
LOW_AI_THRESHOLD = 0.30


def generate_label(raw_score: float, confidence: float) -> dict:
    """
    Returns:
        {
            "label": short string shown as a badge,
            "explanation": one sentence, plain language,
            "recommended_action": what the platform/creator should do,
            "appealable": bool,
        }
    """
    if confidence < CONFIDENCE_FLOOR:
        return {
            "label": "Uncertain — Needs Human Review",
            "explanation": (
                "Our system couldn't confidently determine whether this "
                "content was written by a human or AI. This can happen with "
                "short submissions or writing that doesn't clearly match "
                "either pattern."
            ),
            "recommended_action": "route_to_human_review",
            "appealable": True,
        }

    if raw_score >= HIGH_AI_THRESHOLD:
        return {
            "label": "Likely AI-Generated",
            "explanation": (
                "This content shows patterns commonly associated with "
                "AI-generated writing, such as uniform sentence structure "
                "or repeated phrasing."
            ),
            "recommended_action": "apply_ai_label",
            "appealable": True,
        }

    if raw_score <= LOW_AI_THRESHOLD:
        return {
            "label": "Likely Human-Written",
            "explanation": (
                "This content shows patterns more typical of human writing, "
                "such as varied sentence rhythm and idiosyncratic word choice."
            ),
            "recommended_action": "apply_human_label",
            "appealable": True,
        }

    # Raw score sits in the ambiguous middle band even though confidence
    # itself was okay — the signals themselves disagreed enough to not
    # commit to a direction.
    return {
        "label": "Mixed Signals — Uncertain",
        "explanation": (
            "This content has a mix of characteristics — some typical of "
            "human writing and some typical of AI writing. We're not "
            "confident enough to apply a definitive label."
        ),
        "recommended_action": "route_to_human_review",
        "appealable": True,
    }
