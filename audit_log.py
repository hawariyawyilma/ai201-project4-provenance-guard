"""
audit_log.py — Structured, append-only audit logging.

Every classification decision and every appeal resolution gets logged as a
single JSON line. This is what lets a platform answer "why did you label
my content this way" months later, and what lets Provenance Guard itself
be audited for bias or drift.

Privacy note: we log a hash of the submitted text, never the raw text
itself. The audit trail should prove *what the system did*, not become a
second copy of everyone's content sitting in a log file.
"""

import json
import time
import hashlib
import logging
import os

LOG_PATH = os.environ.get("PROVENANCE_GUARD_LOG_PATH", "audit_log.jsonl")

_logger = logging.getLogger("provenance_guard.audit")
_logger.setLevel(logging.INFO)
if not _logger.handlers:
    handler = logging.FileHandler(LOG_PATH)
    handler.setFormatter(logging.Formatter("%(message)s"))
    _logger.addHandler(handler)
    # Also echo to stdout so it shows up in console/dev logs.
    stream_handler = logging.StreamHandler()
    stream_handler.setFormatter(logging.Formatter("%(message)s"))
    _logger.addHandler(stream_handler)


def _hash_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]


def log_classification(submission_id: str, client_id: str, text: str,
                        signals: list, raw_score: float, confidence: float,
                        label: dict) -> None:
    entry = {
        "event": "classification",
        "timestamp": time.time(),
        "submission_id": submission_id,
        "client_id": client_id,
        "text_hash": _hash_text(text),
        "text_length": len(text),
        "signals": [
            {"signal": s["signal"], "ai_score": s["ai_score"], "weight": s["weight"]}
            for s in signals
        ],
        "raw_score": raw_score,
        "confidence": confidence,
        "label": label["label"],
    }
    _logger.info(json.dumps(entry))


def log_appeal_filed(appeal_id: str, submission_id: str, client_id: str) -> None:
    entry = {
        "event": "appeal_filed",
        "timestamp": time.time(),
        "appeal_id": appeal_id,
        "submission_id": submission_id,
        "client_id": client_id,
    }
    _logger.info(json.dumps(entry))


def log_appeal_resolved(appeal_id: str, outcome: str, reviewer_notes: str) -> None:
    entry = {
        "event": "appeal_resolved",
        "timestamp": time.time(),
        "appeal_id": appeal_id,
        "outcome": outcome,
        "reviewer_notes": reviewer_notes,
    }
    _logger.info(json.dumps(entry))


def log_rate_limit_block(client_id: str) -> None:
    entry = {
        "event": "rate_limit_blocked",
        "timestamp": time.time(),
        "client_id": client_id,
    }
    _logger.info(json.dumps(entry))
