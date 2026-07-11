"""
appeals.py — Appeals workflow for contested automated decisions.

Any creator who receives a label they disagree with can file an appeal
referencing the original submission_id. This module is intentionally
storage-agnostic in spirit (swap the dict for a real DB in production)
but ships with a simple in-memory store so the API is runnable/testable
without external infrastructure.

An appeal always starts as "pending" and must be resolved by a human
reviewer via resolve_appeal(). We never auto-resolve appeals — the whole
point of an appeals path is a human check on the automated system.
"""

import uuid
import time
from threading import Lock

_lock = Lock()
_appeals = {}   # appeal_id -> appeal record
_submissions = {}  # submission_id -> original decision record (set by app.py)


def register_submission(submission_id: str, decision: dict):
    """Called by app.py right after a classification, so an appeal can
    later reference exactly what was decided and why."""
    with _lock:
        _submissions[submission_id] = decision


def get_submission(submission_id: str):
    return _submissions.get(submission_id)


def file_appeal(submission_id: str, reason: str, contact: str = None) -> dict:
    if submission_id not in _submissions:
        raise KeyError(f"No submission found with id {submission_id}")

    appeal_id = str(uuid.uuid4())
    record = {
        "appeal_id": appeal_id,
        "submission_id": submission_id,
        "reason": reason,
        "contact": contact,
        "status": "pending",
        "filed_at": time.time(),
        "resolved_at": None,
        "reviewer_notes": None,
        "original_decision": _submissions[submission_id],
    }
    with _lock:
        _appeals[appeal_id] = record
    return record


def get_appeal(appeal_id: str):
    return _appeals.get(appeal_id)


def resolve_appeal(appeal_id: str, outcome: str, reviewer_notes: str) -> dict:
    """
    outcome: one of "upheld" (original label stands) or "overturned"
    (label was wrong, decision reversed).
    """
    if outcome not in ("upheld", "overturned"):
        raise ValueError("outcome must be 'upheld' or 'overturned'")
    with _lock:
        appeal = _appeals.get(appeal_id)
        if appeal is None:
            raise KeyError(f"No appeal found with id {appeal_id}")
        appeal["status"] = outcome
        appeal["resolved_at"] = time.time()
        appeal["reviewer_notes"] = reviewer_notes
    return appeal


def list_pending_appeals() -> list:
    return [a for a in _appeals.values() if a["status"] == "pending"]
