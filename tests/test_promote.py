"""Tests for promote_approved.py — V3-C4 production enforcement + C2 signed
reviewer decisions (cross-platform; replaces the Unix pwd-owner test)."""

import os
import pytest
from pathlib import Path
from unittest.mock import patch


# ── V3-C4: production mode enforcement ────────────────────────────────────────

def test_production_mode_requires_both_vars(tmp_path):
    """HERMES_ENV=production without REVIEWER_REGISTRY + POLICY_SIGNING_KEY must raise."""
    from promote_approved import promote

    (tmp_path / "approved").mkdir()
    active = tmp_path / "active"

    env = {"HERMES_ENV": "production", "REVIEWER_REGISTRY": "", "POLICY_SIGNING_KEY": ""}
    with pytest.raises(RuntimeError, match="REVIEWER_REGISTRY"):
        with patch.dict(os.environ, env, clear=False):
            promote(tmp_path, active)

    env2 = {
        "HERMES_ENV": "production",
        "REVIEWER_REGISTRY": str(tmp_path / "registry.json"),
        "POLICY_SIGNING_KEY": "",
    }
    with pytest.raises(RuntimeError, match="POLICY_SIGNING_KEY"):
        with patch.dict(os.environ, env2, clear=False):
            promote(tmp_path, active)


def test_dev_mode_does_not_enforce(tmp_path):
    """Without HERMES_ENV=production, promotion proceeds without raising on missing vars."""
    from promote_approved import promote

    (tmp_path / "approved").mkdir()
    active = tmp_path / "active"

    env = {"HERMES_ENV": "", "REVIEWER_REGISTRY": "", "POLICY_SIGNING_KEY": ""}
    with patch.dict(os.environ, env, clear=False):
        result = promote(tmp_path, active)
    assert result == 0


# ── C2: cross-platform signed reviewer decisions ──────────────────────────────

def _gen_key(path):
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
    key = Ed25519PrivateKey.generate()
    path.write_bytes(key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption()))
    pub_pem = key.public_key().public_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PublicFormat.SubjectPublicKeyInfo).decode()
    return key, pub_pem


def _setup_signed(tmp_path, monkeypatch):
    """Build a review tree with one proposal; return (promote, sign_decision,
    write_decision, paths). reviewer keypair registered; signing key set."""
    import hashlib
    import json as _json
    from promote_approved import promote, decision_signing_payload
    import policy_keys

    approved = tmp_path / "review" / "approved"
    approved.mkdir(parents=True)
    proposal = {
        "schema_version": 1, "id": "hdb_signed_rule", "agency": "HDB",
        "before": None, "after": "Statement.",
        "source": {"title": "HDB", "url": "https://www.hdb.gov.sg/x",
                   "effective_date": "2026-01-01"},
    }
    raw = (_json.dumps(proposal, indent=2, sort_keys=True) + "\n").encode()
    (approved / "hdb_signed_rule.json").write_bytes(raw)

    # Reviewer keypair (signs decisions) + release signing key (signs manifest).
    reviewer_key, reviewer_pub_pem = _gen_key(tmp_path / "reviewer.pem")
    _gen_key(tmp_path / "release.pem")

    registry = tmp_path / "registry.json"
    registry.write_text(_json.dumps({"reviewer-1": reviewer_pub_pem}))

    monkeypatch.setenv("HERMES_ENV", "production")
    monkeypatch.setenv("REVIEWER_REGISTRY", str(registry))
    monkeypatch.setenv("POLICY_SIGNING_KEY", str(tmp_path / "release.pem"))

    def write_decision(reviewer_id="reviewer-1", sign_with=reviewer_key,
                       tamper=None, signed=True):
        decision = {
            "schema_version": 1, "decision": "approved",
            "reviewer_id": reviewer_id, "reviewer_note": None,
            "proposal_sha256": hashlib.sha256(raw).hexdigest(),
            "decided_at_unix": 1781049600,
        }
        if signed:
            decision["signature"] = policy_keys.sign(
                sign_with, decision_signing_payload(decision))
        if tamper:
            decision.update(tamper)
        (approved / "hdb_signed_rule.json.decision.json").write_text(
            _json.dumps(decision), encoding="utf-8")

    return promote, write_decision, reviewer_key


def test_production_valid_signature_promotes(tmp_path, monkeypatch):
    promote, write_decision, _ = _setup_signed(tmp_path, monkeypatch)
    write_decision()
    assert promote(tmp_path / "review", tmp_path / "active") == 1


def test_production_unsigned_decision_rejected(tmp_path, monkeypatch):
    promote, write_decision, _ = _setup_signed(tmp_path, monkeypatch)
    write_decision(signed=False)
    with pytest.raises(ValueError, match="not signed"):
        promote(tmp_path / "review", tmp_path / "active")


def test_production_tampered_decision_rejected(tmp_path, monkeypatch):
    promote, write_decision, _ = _setup_signed(tmp_path, monkeypatch)
    # Sign, then change a signed field so the signature no longer matches.
    write_decision(tamper={"decided_at_unix": 1781049999})
    with pytest.raises(ValueError, match="signature .* is invalid"):
        promote(tmp_path / "review", tmp_path / "active")


def test_production_wrong_key_rejected(tmp_path, monkeypatch):
    promote, write_decision, _ = _setup_signed(tmp_path, monkeypatch)
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
    write_decision(sign_with=Ed25519PrivateKey.generate())  # not the registered key
    with pytest.raises(ValueError, match="signature .* is invalid"):
        promote(tmp_path / "review", tmp_path / "active")
