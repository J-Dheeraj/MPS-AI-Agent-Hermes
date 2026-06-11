"""Promotion signs the manifest and enforces the reviewer registry (V-C1)."""

import base64
import hashlib
import json

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

import policy_keys
from promote_approved import promote


def _build_approved_tree(tmp_path):
    """A minimal review root with one approved proposal + decision sidecar."""
    review_root = tmp_path / "review"
    approved = review_root / "approved"
    approved.mkdir(parents=True)
    proposal = {
        "schema_version": 1,
        "id": "hdb_signed_rule",
        "agency": "HDB",
        "before": None,
        "after": "Reviewed HDB statement.",
        "source": {
            "title": "HDB policy",
            "url": "https://www.hdb.gov.sg/policy",
            "effective_date": "2026-01-01",
        },
    }
    proposal_bytes = (json.dumps(proposal, indent=2, sort_keys=True) + "\n").encode()
    proposal_path = approved / "hdb_signed_rule.json"
    proposal_path.write_bytes(proposal_bytes)
    decision = {
        "schema_version": 1,
        "decision": "approved",
        "reviewer_id": "reviewer-1",
        "reviewer_note": None,
        "proposal_sha256": hashlib.sha256(proposal_bytes).hexdigest(),
        "decided_at_unix": 1781049600,
    }
    (approved / "hdb_signed_rule.json.decision.json").write_text(
        json.dumps(decision), encoding="utf-8"
    )
    return review_root


def _write_key(tmp_path):
    key = Ed25519PrivateKey.generate()
    pem = key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    )
    path = tmp_path / "key.pem"
    path.write_bytes(pem)
    return key, path


def test_promote_signs_manifest(tmp_path, monkeypatch):
    review_root = _build_approved_tree(tmp_path)
    key, key_path = _write_key(tmp_path)
    monkeypatch.setenv("POLICY_SIGNING_KEY", str(key_path))
    active = tmp_path / "active"
    assert promote(review_root, active) == 1

    manifest_bytes = (active / "manifest.json").read_bytes()
    sidecar = json.loads((active / "manifest.json.sig").read_text(encoding="utf-8"))
    assert sidecar["algorithm"] == "ed25519"
    assert sidecar["key_id"] == policy_keys.key_id(key.public_key())
    # The signature must verify over the exact manifest bytes.
    key.public_key().verify(base64.b64decode(sidecar["signature"]), manifest_bytes)


def test_reviewer_registry_rejects_unknown_reviewer(tmp_path, monkeypatch):
    review_root = _build_approved_tree(tmp_path)
    registry = tmp_path / "reviewers.json"
    registry.write_text(json.dumps({"reviewers": ["someone-else"]}), encoding="utf-8")
    monkeypatch.setenv("REVIEWER_REGISTRY", str(registry))
    with pytest.raises(ValueError, match="not in the approved registry"):
        promote(review_root, tmp_path / "active")


def test_reviewer_registry_accepts_known_reviewer(tmp_path, monkeypatch):
    review_root = _build_approved_tree(tmp_path)
    registry = tmp_path / "reviewers.json"
    registry.write_text(json.dumps({"reviewers": ["reviewer-1"]}), encoding="utf-8")
    monkeypatch.setenv("REVIEWER_REGISTRY", str(registry))
    assert promote(review_root, tmp_path / "active") == 1
