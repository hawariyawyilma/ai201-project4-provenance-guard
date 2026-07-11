"""
detectors.py — Multi-signal AI-content detection pipeline.

Design principle: no single signal is trustworthy on its own. Each detector
below captures ONE distinct, independent property of the text. We deliberately
avoid signals that are just re-measurements of the same underlying property
(e.g. two flavors of "word frequency") because that would inflate confidence
without adding real information.

Every detector returns a dict:
    {
        "signal": str,          # name of the signal
        "ai_score": float,      # 0.0 (looks human) -> 1.0 (looks AI-generated)
        "weight": float,        # how much this signal counts in the ensemble
        "detail": str,          # human-readable explanation (for transparency)
    }

None of these signals are forensically certain — they are heuristic proxies
for patterns that correlate with AI-generated text. That's the whole reason
the system needs a confidence layer on top (see confidence.py) rather than
just trusting the raw score.
"""

import re
import statistics
from collections import Counter

# Common AI "tell" phrases — connector/hedge words that show up disproportionately
# often in LLM output relative to typical human writing.
_AI_MARKER_PHRASES = [
    "furthermore", "moreover", "in conclusion", "it is important to note",
    "it's important to note", "overall,", "in summary", "additionally,",
    "on the other hand", "as an ai", "i cannot", "i don't have personal",
    "delve into", "in today's world", "plays a crucial role", "a testament to",
    "it is worth noting", "in essence", "navigating the", "the realm of",
    "underscores the", "boasts a", "rich tapestry",
]

MIN_TEXT_LENGTH_FOR_RELIABLE_SIGNAL = 200  # characters


def _sentences(text: str):
    # Simple sentence splitter — good enough for heuristic signals.
    parts = re.split(r'(?<=[.!?])\s+', text.strip())
    return [p for p in parts if p]


def _words(text: str):
    return re.findall(r"[A-Za-z']+", text.lower())


def analyze_sentence_burstiness(text: str) -> dict:
    """
    Property measured: variance in sentence length ("burstiness").
    Human writing tends to mix short punchy sentences with long winding ones.
    AI-generated text often has more uniform sentence lengths.
    """
    sents = _sentences(text)
    lengths = [len(_words(s)) for s in sents if _words(s)]

    if len(lengths) < 4:
        return {
            "signal": "sentence_burstiness",
            "ai_score": 0.5,
            "weight": 0.1,  # low weight — not enough sentences to trust this
            "detail": "Too few sentences to measure rhythm reliably.",
        }

    mean_len = statistics.mean(lengths)
    stdev_len = statistics.pstdev(lengths)
    # Coefficient of variation: low CoV -> uniform -> more AI-like
    cov = stdev_len / mean_len if mean_len else 0

    # Empirically, human text often has CoV > 0.5; heavily uniform AI text < 0.3
    if cov < 0.3:
        ai_score = 0.8
    elif cov < 0.5:
        ai_score = 0.55
    else:
        ai_score = 0.25

    return {
        "signal": "sentence_burstiness",
        "ai_score": ai_score,
        "weight": 0.25,
        "detail": f"Sentence length variation (CoV={cov:.2f}); "
                  f"{'uniform, AI-like rhythm' if cov < 0.3 else 'varied, human-like rhythm' if cov > 0.5 else 'moderate variation'}.",
    }


def analyze_vocabulary_diversity(text: str) -> dict:
    """
    Property measured: lexical diversity (type-token ratio, length-normalized).
    Human writers tend to introduce more idiosyncratic/varied vocabulary,
    including rarer words and personal quirks. AI text often has smoother,
    more "average" vocabulary distribution.
    """
    words = _words(text)
    if len(words) < 40:
        return {
            "signal": "vocabulary_diversity",
            "ai_score": 0.5,
            "weight": 0.1,
            "detail": "Too little text to measure vocabulary diversity reliably.",
        }

    unique_ratio = len(set(words)) / len(words)

    # Very rough calibration: extremely high or extremely low uniqueness
    # both look unusual; typical human casual writing lands ~0.4-0.6 for
    # this length range.
    if unique_ratio < 0.35:
        ai_score = 0.7
    elif unique_ratio < 0.45:
        ai_score = 0.55
    else:
        ai_score = 0.3

    return {
        "signal": "vocabulary_diversity",
        "ai_score": ai_score,
        "weight": 0.2,
        "detail": f"Unique-word ratio={unique_ratio:.2f} over {len(words)} words.",
    }


def analyze_repetition(text: str) -> dict:
    """
    Property measured: repeated multi-word phrases (3-grams).
    AI text, especially longer generations, often repeats structural
    phrases ("In this article, we will...") more than human writing does.
    """
    words = _words(text)
    if len(words) < 30:
        return {
            "signal": "phrase_repetition",
            "ai_score": 0.5,
            "weight": 0.1,
            "detail": "Too little text to assess phrase repetition.",
        }

    trigrams = [" ".join(words[i:i + 3]) for i in range(len(words) - 2)]
    counts = Counter(trigrams)
    repeated = sum(c for c in counts.values() if c > 1)
    repetition_ratio = repeated / len(trigrams) if trigrams else 0

    ai_score = min(0.9, 0.3 + repetition_ratio * 3)

    return {
        "signal": "phrase_repetition",
        "ai_score": ai_score,
        "weight": 0.15,
        "detail": f"{repetition_ratio:.2%} of 3-word phrases repeat within the text.",
    }


def analyze_stylistic_markers(text: str) -> dict:
    """
    Property measured: presence of stock AI "connector" phrasing.
    This is the most direct signal but also the easiest to game
    (a human can write "furthermore" too), so it gets a moderate weight,
    not a dominant one.
    """
    lowered = text.lower()
    hits = [phrase for phrase in _AI_MARKER_PHRASES if phrase in lowered]
    word_count = max(len(_words(text)), 1)
    density = len(hits) / (word_count / 100)  # hits per 100 words

    ai_score = min(0.9, 0.2 + density * 0.3)

    return {
        "signal": "stylistic_markers",
        "ai_score": ai_score,
        "weight": 0.2,
        "detail": f"Found {len(hits)} common AI-style marker phrase(s)"
                  + (f" (e.g. '{hits[0]}')" if hits else "") + ".",
    }


def analyze_punctuation_patterns(text: str) -> dict:
    """
    Property measured: punctuation texture — em-dash usage, list-like
    colon structures, and exclamation scarcity. AI text (especially from
    instruction-tuned models) trends toward tidy, list-heavy, em-dash-heavy
    prose; human casual writing is messier.
    """
    em_dash_count = text.count("—") + text.count(" - ")
    colon_lists = len(re.findall(r":\s*\n?\s*[-*•]", text))
    exclamations = text.count("!")
    word_count = max(len(_words(text)), 1)

    em_dash_density = em_dash_count / (word_count / 200)
    ai_score = 0.3
    if em_dash_density > 1:
        ai_score += 0.25
    if colon_lists > 0:
        ai_score += 0.15
    if exclamations == 0 and word_count > 150:
        ai_score += 0.1
    ai_score = min(ai_score, 0.9)

    return {
        "signal": "punctuation_texture",
        "ai_score": ai_score,
        "weight": 0.1,
        "detail": f"Em-dash density={em_dash_density:.2f}/200w, "
                  f"{colon_lists} colon-led list(s), {exclamations} exclamation(s).",
    }


ALL_DETECTORS = [
    analyze_sentence_burstiness,
    analyze_vocabulary_diversity,
    analyze_repetition,
    analyze_stylistic_markers,
    analyze_punctuation_patterns,
]


def run_all_signals(text: str) -> list:
    """Run every detector and return the list of signal dicts."""
    return [detector(text) for detector in ALL_DETECTORS]
