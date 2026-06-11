"""Tests for promote_approved.py — including V3-C4 production mode enforcement."""

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

    # Neither var set
    env = {"HERMES_ENV": "production", "REVIEWER_REGISTRY": "", "POLICY_SIGNING_KEY": ""}
    with pytest.raises(RuntimeError, match="REVIEWER_REGISTRY"):
        with patch.dict(os.environ, env, clear=False):
            promote(tmp_path, active)

    # Only registry set, signing key missing
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

    # Empty HERMES_ENV -> dev mode -> no enforcement error
    env = {"HERMES_ENV": "", "REVIEWER_REGISTRY": "", "POLICY_SIGNING_KEY": ""}
    with patch.dict(os.environ, env, clear=False):
        result = promote(tmp_path, active)
    assert result == 0  # nothing to promote in empty approved dir


def test_production_reviewer_identity_must_match_file_owner(tmp_path, monkeypatch):
    """V4-C5: in production, a decision claiming another reviewer's identity
    is rejected because the sidecar file is not owned by that OS account."""
    import getpass
    import hashlib
    import json as _json
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
    from promote_approved import promote

    me = getpass.getuser()
    approved = tmp_path / "review" / "approved"
    approved.mkdir(parents=True)
    proposal = {
        "schema_version": 1, "id": "hdb_owner_rule", "agency": "HDB",
        "before": None, "after": "Statement.",
        "source": {"title": "HDB", "url": "https://www.hdb.gov.sg/x",
                   "effective_date": "2026-01-01"},
    }
    raw = (_json.dumps(proposal, indent=2, sort_keys=True) + "\n").encode()
    (approved / "hdb_owner_rule.json").write_bytes(raw)

    key = Ed25519PrivateKey.generate()
    key_path = tmp_path / "key.pem"
    key_path.write_bytes(key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption()))
    registry = tmp_path / "registry.json"

    monkeypatch.setenv("HERMES_ENV", "production")
    monkeypatch.setenv("REVIEWER_REGISTRY", str(registry))
    monkeypatch.setenv("POLICY_SIGNING_KEY", str(key_path))

    def write_decision(reviewer_id):
        (approved / "hdb_owner_rule.json.decision.json").write_text(_json.dumps({
            "schema_version": 1, "decision": "approved",
            "reviewer_id": reviewer_id, "reviewer_note": None,
            "proposal_sha256": hashlib.sha256(raw).hexdigest(),
            "decided_at_unix": 1781049600,
        }), encoding="utf-8")

    # Claiming someone else's identity: rejected on ownership.
    registry.write_text(_json.dumps([me, "someone-else"]))
    write_decision("someone-else")
    with pytest.raises(ValueError, match="owned by OS user"):
        promote(tmp_path / "review", tmp_path / "active")

    # Claiming own identity: ownership check passes.
    write_decision(me)
    assert promote(tmp_path / "review", tmp_path / "active") == 1
