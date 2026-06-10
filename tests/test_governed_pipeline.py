import hashlib
import json

from hermes import generate
from promote_approved import promote


def test_feedback_to_review_to_manifested_policy(tmp_path):
    batch = {
        "schema_version": 1,
        "batch_id": "batch-1",
        "entries": [
            {
                "feedback_id": "feedback-1",
                "agency": "HDB",
                "incorrect_claim": "Old threshold",
                "correct_answer": "Reviewed threshold statement",
                "source": {
                    "title": "HDB policy",
                    "url": "https://www.hdb.gov.sg/policy",
                    "effective_date": "2026-01-01",
                },
                "validated_by": "vetter-2",
                "validated_at": "2026-06-10T00:00:00+00:00",
            }
        ],
    }
    batch_path = tmp_path / "batch.json"
    batch_path.write_text(json.dumps(batch), encoding="utf-8")
    review_root = tmp_path / "review"
    assert generate(batch_path, review_root) == 1

    proposal_path = next((review_root / "pending").glob("*.json"))
    proposal_bytes = proposal_path.read_bytes()
    approved_path = review_root / "approved" / proposal_path.name
    approved_path.parent.mkdir(exist_ok=True)
    proposal_path.replace(approved_path)
    decision = {
        "schema_version": 1,
        "decision": "approved",
        "reviewer_id": "reviewer-1",
        "reviewer_note": None,
        "proposal_sha256": hashlib.sha256(proposal_bytes).hexdigest(),
        "decided_at_unix": 1781049600,
    }
    (review_root / "approved" / f"{proposal_path.name}.decision.json").write_text(
        json.dumps(decision), encoding="utf-8"
    )

    active = tmp_path / "active"
    assert promote(review_root, active) == 1
    manifest = json.loads((active / "manifest.json").read_text(encoding="utf-8"))
    assert len(manifest["rules"]) == 1
