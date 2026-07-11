"""
test_provenance_guard.py — Automated tests for Provenance Guard.

Run with:
    pip install pytest
    pytest test_provenance_guard.py -v
"""

import pytest
import app as flask_app


@pytest.fixture
def client():
    flask_app.app.config["TESTING"] = True
    return flask_app.app.test_client()


def test_health(client):
    r = client.get("/health")
    assert r.status_code == 200
    assert r.get_json()["status"] == "ok"


def test_classify_rejects_short_text(client):
    r = client.post("/api/v1/classify", json={"text": "too short"})
    assert r.status_code == 400
    assert r.get_json()["error"] == "invalid_input"


def test_classify_rejects_missing_text(client):
    r = client.post("/api/v1/classify", json={})
    assert r.status_code == 400


def test_classify_returns_full_decision_shape(client):
    text = "This is a reasonably long piece of writing about home repair topics, long enough to pass the minimum length check for this API endpoint."
    r = client.post("/api/v1/classify", json={"text": text})
    assert r.status_code == 200
    body = r.get_json()
    for key in ["submission_id", "label", "explanation", "confidence",
                "raw_ai_likelihood_score", "signals", "appealable"]:
        assert key in body
    assert 0.0 <= body["confidence"] <= 1.0
    assert 0.0 <= body["raw_ai_likelihood_score"] <= 1.0
    assert len(body["signals"]) == 5


def test_short_text_yields_low_confidence(client):
    # Text just over the minimum length should have low confidence because
    # of the length_factor penalty, regardless of what the signals say.
    text = "The sink is broken and it drips a lot every single day now."
    r = client.post("/api/v1/classify", json={"text": text})
    body = r.get_json()
    assert body["confidence_breakdown"]["length_factor"] < 0.7


def test_appeal_workflow_end_to_end(client):
    text = "A" * 30 + " this is filler text to pass the minimum length requirement for classification purposes today."
    classify_resp = client.post("/api/v1/classify", json={"text": text})
    submission_id = classify_resp.get_json()["submission_id"]

    appeal_resp = client.post("/api/v1/appeals", json={
        "submission_id": submission_id,
        "reason": "I wrote this myself.",
    })
    assert appeal_resp.status_code == 201
    appeal_id = appeal_resp.get_json()["appeal_id"]

    status_resp = client.get(f"/api/v1/appeals/{appeal_id}")
    assert status_resp.status_code == 200
    assert status_resp.get_json()["status"] == "pending"

    resolve_resp = client.post(f"/api/v1/appeals/{appeal_id}/resolve", json={
        "outcome": "overturned",
        "reviewer_notes": "Verified with the original author.",
    })
    assert resolve_resp.status_code == 200
    assert resolve_resp.get_json()["status"] == "overturned"


def test_appeal_against_unknown_submission_404s(client):
    r = client.post("/api/v1/appeals", json={
        "submission_id": "does-not-exist",
        "reason": "test",
    })
    assert r.status_code == 404


def test_rate_limiting_blocks_excess_requests(client):
    text = "This text is long enough to pass validation for the rate limit test scenario here."
    statuses = []
    for _ in range(35):
        r = client.post("/api/v1/classify", json={"text": text})
        statuses.append(r.status_code)
    assert 429 in statuses
    # The 429 response should include a Retry-After header.
    last = client.post("/api/v1/classify", json={"text": text})
    if last.status_code == 429:
        assert "Retry-After" in last.headers
