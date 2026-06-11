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
