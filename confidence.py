"""
confidence.py — Calibrated confidence scoring.

The hardest design problem in Provenance Guard isn't "is this AI-generated,"
it's "how sure are we, and should we even be answering with a label at all."

Two texts can produce the exact same raw AI-likelihood score (say, 0.62) for
very different reasons:
    - Text A: every signal independently lands around 0.6 -> signals AGREE.
      We should be reasonably confident the true answer is "probably AI,
      leaning uncertain."
    - Text B: signals are split — two say 0.95, two say 0.25 -> signals
      DISAGREE. The average is also ~0.6, but we have much weaker grounds
      to trust it.

So confidence is modeled as a function of:
    1. Signal agreement (inverse of weighted variance across signals)
    2. Input length (short text starves every signal of data)
    3. Distance of the raw score from the 0.5 "coin flip" point
       (a score of 0.95 sitting on top of agreeing signals is more
       trustworthy than a score of 0.55 sitting on agreeing signals,
       even though both indicate agreement)

We deliberately do NOT force a binary output. A low-confidence result is a
valid, honest output — the system should say "we don't know" rather than
manufacture false certainty.
"""

import statistics


def compute_weighted_score(signals: list) -> float:
    """Weighted average of ai_score across all signals."""
    total_weight = sum(s["weight"] for s in signals)
    if total_weight == 0:
        return 0.5
    weighted_sum = sum(s["ai_score"] * s["weight"] for s in signals)
    return weighted_sum / total_weight


def compute_signal_agreement(signals: list) -> float:
    """
    Returns 0.0 (total disagreement) to 1.0 (perfect agreement) based on
    the spread of ai_score values across signals, weighted by trust in
    each signal (a signal that flagged itself as low-weight because the
    text was too short doesn't get to tank agreement).
    """
    # Only consider signals that had enough data to speak with real weight.
    trustworthy = [s for s in signals if s["weight"] >= 0.15]
    if len(trustworthy) < 2:
        return 0.3  # not enough independent signals to call it agreement

    scores = [s["ai_score"] for s in trustworthy]
    stdev = statistics.pstdev(scores)
    # stdev of 0 -> perfect agreement -> 1.0
    # stdev of ~0.4+ -> signals are all over the place -> near 0
    agreement = max(0.0, 1.0 - (stdev / 0.4))
    return min(agreement, 1.0)


def compute_length_factor(text: str) -> float:
    """
    Short submissions starve every signal. Returns a 0-1 multiplier that
    penalizes confidence for very short text, independent of what the
    signals say.
    """
    length = len(text.strip())
    if length < 100:
        return 0.3
    if length < 250:
        return 0.6
    if length < 600:
        return 0.85
    return 1.0


def compute_decisiveness(raw_score: float) -> float:
    """
    How far the raw score sits from the 0.5 coin-flip midpoint, rescaled
    to 0-1. A score of 0.5 contributes 0 decisiveness; a score of 0.0 or
    1.0 contributes full decisiveness.
    """
    return abs(raw_score - 0.5) * 2


def compute_confidence(text: str, signals: list, raw_score: float) -> dict:
    """
    Combines agreement, length, and decisiveness into a single confidence
    score in [0, 1], plus a breakdown for transparency/audit purposes.
    """
    agreement = compute_signal_agreement(signals)
    length_factor = compute_length_factor(text)
    decisiveness = compute_decisiveness(raw_score)

    # Agreement and length are gating factors (multiplicative) — if either
    # is bad, overall confidence should be capped low, not just averaged
    # down. Decisiveness then modulates within that ceiling.
    ceiling = agreement * length_factor
    confidence = ceiling * (0.5 + 0.5 * decisiveness)

    return {
        "confidence": round(confidence, 3),
        "components": {
            "signal_agreement": round(agreement, 3),
            "length_factor": round(length_factor, 3),
            "decisiveness": round(decisiveness, 3),
        },
    }
