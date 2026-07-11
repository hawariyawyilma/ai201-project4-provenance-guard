"""
app.py — Provenance Guard API.

Endpoints:
    GET  /health
    POST /api/v1/classify          — classify submitted text
    POST /api/v1/appeals           — file an appeal against a classification
    GET  /api/v1/appeals/<id>      — check appeal status
    POST /api/v1/appeals/<id>/resolve — (internal/reviewer) resolve an appeal
    GET  /api/v1/appeals           — (internal/reviewer) list pending appeals

Run with:
    pip install -r requirements.txt
    python app.py
"""

import uuid
from flask import Flask, request, jsonify

import detectors
import confidence as confidence_module
import labels as labels_module
import appeals
import audit_log
from rate_limiter import rate_limited, _get_client_id

app = Flask(__name__)

MIN_TEXT_LENGTH = 20
MAX_TEXT_LENGTH = 20_000


@app.route("/health", methods=["GET"])
def health():
    return jsonify({"status": "ok"})


@app.route("/api/v1/classify", methods=["POST"])
@rate_limited(limit=30, window_seconds=60)
def classify():
    data = request.get_json(silent=True) or {}
    text = data.get("text", "")

    if not isinstance(text, str) or len(text.strip()) < MIN_TEXT_LENGTH:
        return jsonify({
            "error": "invalid_input",
            "message": f"'text' must be a string of at least {MIN_TEXT_LENGTH} characters.",
        }), 400

    if len(text) > MAX_TEXT_LENGTH:
        return jsonify({
            "error": "invalid_input",
            "message": f"'text' exceeds max length of {MAX_TEXT_LENGTH} characters.",
        }), 400

    client_id = _get_client_id()
    submission_id = str(uuid.uuid4())

    # 1. Run the multi-signal detection pipeline.
    signals = detectors.run_all_signals(text)

    # 2. Aggregate into a raw AI-likelihood score.
    raw_score = confidence_module.compute_weighted_score(signals)

    # 3. Compute calibrated confidence in that score.
    conf_result = confidence_module.compute_confidence(text, signals, raw_score)

    # 4. Translate into a plain-language, user-facing label.
    label = labels_module.generate_label(raw_score, conf_result["confidence"])

    decision = {
        "submission_id": submission_id,
        "label": label["label"],
        "explanation": label["explanation"],
        "recommended_action": label["recommended_action"],
        "confidence": conf_result["confidence"],
        "raw_ai_likelihood_score": round(raw_score, 3),
        "confidence_breakdown": conf_result["components"],
        "signals": [
            {"signal": s["signal"], "ai_score": round(s["ai_score"], 3), "detail": s["detail"]}
            for s in signals
        ],
        "appealable": label["appealable"],
        "appeal_endpoint": "/api/v1/appeals",
    }

    # 5. Register submission so an appeal can later reference it.
    appeals.register_submission(submission_id, decision)

    # 6. Structured audit log entry — every decision, no exceptions.
    audit_log.log_classification(
        submission_id, client_id, text, signals, raw_score,
        conf_result["confidence"], label,
    )

    return jsonify(decision), 200


@app.route("/api/v1/appeals", methods=["POST"])
@rate_limited(limit=10, window_seconds=60)
def create_appeal():
    data = request.get_json(silent=True) or {}
    submission_id = data.get("submission_id")
    reason = data.get("reason", "").strip()
    contact = data.get("contact")

    if not submission_id:
        return jsonify({"error": "invalid_input", "message": "'submission_id' is required."}), 400
    if not reason:
        return jsonify({"error": "invalid_input", "message": "'reason' is required."}), 400

    try:
        record = appeals.file_appeal(submission_id, reason, contact)
    except KeyError as e:
        return jsonify({"error": "not_found", "message": str(e)}), 404

    client_id = _get_client_id()
    audit_log.log_appeal_filed(record["appeal_id"], submission_id, client_id)

    return jsonify({
        "appeal_id": record["appeal_id"],
        "submission_id": submission_id,
        "status": record["status"],
        "message": "Your appeal has been filed and will be reviewed by a human.",
        "status_endpoint": f"/api/v1/appeals/{record['appeal_id']}",
    }), 201


@app.route("/api/v1/appeals/<appeal_id>", methods=["GET"])
def get_appeal_status(appeal_id):
    record = appeals.get_appeal(appeal_id)
    if record is None:
        return jsonify({"error": "not_found", "message": "No appeal with that id."}), 404

    return jsonify({
        "appeal_id": record["appeal_id"],
        "submission_id": record["submission_id"],
        "status": record["status"],
        "filed_at": record["filed_at"],
        "resolved_at": record["resolved_at"],
        "reviewer_notes": record["reviewer_notes"],
        "original_label": record["original_decision"]["label"],
    })


@app.route("/api/v1/appeals", methods=["GET"])
def list_pending_appeals():
    # In production this would require reviewer auth. Left open here since
    # this is a class project, not a deployed system.
    pending = appeals.list_pending_appeals()
    return jsonify({
        "count": len(pending),
        "appeals": [
            {
                "appeal_id": a["appeal_id"],
                "submission_id": a["submission_id"],
                "reason": a["reason"],
                "filed_at": a["filed_at"],
                "original_label": a["original_decision"]["label"],
            }
            for a in pending
        ],
    })


@app.route("/api/v1/appeals/<appeal_id>/resolve", methods=["POST"])
def resolve_appeal(appeal_id):
    data = request.get_json(silent=True) or {}
    outcome = data.get("outcome")
    reviewer_notes = data.get("reviewer_notes", "")

    try:
        record = appeals.resolve_appeal(appeal_id, outcome, reviewer_notes)
    except KeyError as e:
        return jsonify({"error": "not_found", "message": str(e)}), 404
    except ValueError as e:
        return jsonify({"error": "invalid_input", "message": str(e)}), 400

    audit_log.log_appeal_resolved(appeal_id, outcome, reviewer_notes)

    return jsonify({
        "appeal_id": record["appeal_id"],
        "status": record["status"],
        "resolved_at": record["resolved_at"],
    })


if __name__ == "__main__":
    app.run(debug=True, port=5001)
