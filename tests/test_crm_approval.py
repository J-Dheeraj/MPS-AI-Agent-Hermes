import importlib.util
import json
import os
from pathlib import Path

from crm_approval import mint_token


def load_crm_module():
    path = Path(__file__).resolve().parents[1] / "mcp-crm-server.py"
    spec = importlib.util.spec_from_file_location("mps_crm_server", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_approval_token_is_bound_to_exact_payload(monkeypatch, tmp_path):
    secret = "approval-secret-with-at-least-thirty-two-characters"
    monkeypatch.setenv("CRM_APPROVAL_SECRET", secret)
    monkeypatch.setenv("CRM_WRITE_MODE", "approval_required")
    monkeypatch.setenv("CRM_DATA_DIR", str(tmp_path))
    module = load_crm_module()
    payload = {
        "case_id": 1,
        "status": "closed",
        "notes": "Resolved",
        "reply_received": True,
    }
    token = mint_token("update_case_status", payload, "supervisor-1", 300)
    assert module._approval_error("update_case_status", payload, token) is None
    changed = dict(payload, status="escalated")
    assert module._approval_error("update_case_status", changed, token)["error"]


def test_approval_token_cannot_be_replayed(monkeypatch, tmp_path):
    """V-H11: a token is consumed on first successful use."""
    secret = "approval-secret-with-at-least-thirty-two-characters"
    monkeypatch.setenv("CRM_APPROVAL_SECRET", secret)
    monkeypatch.setenv("CRM_WRITE_MODE", "approval_required")
    monkeypatch.setenv("CRM_DATA_DIR", str(tmp_path))
    module = load_crm_module()
    payload = {"case_id": 2, "status": "closed", "notes": "x", "reply_received": True}
    token = mint_token("update_case_status", payload, "supervisor-1", 300)
    assert module._approval_error("update_case_status", payload, token) is None
    replay = module._approval_error("update_case_status", payload, token)
    assert replay is not None and "error" in replay


def test_token_without_jti_rejected(monkeypatch, tmp_path):
    """V-H11: legacy tokens lacking a one-time identifier are rejected."""
    import base64, hashlib, hmac, json, time
    secret = "approval-secret-with-at-least-thirty-two-characters"
    monkeypatch.setenv("CRM_APPROVAL_SECRET", secret)
    monkeypatch.setenv("CRM_WRITE_MODE", "approval_required")
    monkeypatch.setenv("CRM_DATA_DIR", str(tmp_path))
    module = load_crm_module()
    payload = {"case_id": 3, "status": "closed", "notes": "x", "reply_received": True}
    claims = {
        "action": "update_case_status",
        "payload_sha256": hashlib.sha256(
            json.dumps(payload, sort_keys=True, separators=(",", ":"),
                       ensure_ascii=True).encode()).hexdigest(),
        "approved_by": "supervisor-1",
        "exp": int(time.time()) + 300,
    }
    raw = json.dumps(claims, sort_keys=True, separators=(",", ":"),
                     ensure_ascii=True).encode()
    encoded = base64.urlsafe_b64encode(raw).decode().rstrip("=")
    sig = hmac.new(secret.encode(), raw, hashlib.sha256).hexdigest()
    out = module._approval_error("update_case_status", payload, f"{encoded}.{sig}")
    assert out is not None and "error" in out


def test_replay_rejected_across_restart(monkeypatch, tmp_path):
    """V4-C4: consumption must survive process restart (module reload)."""
    secret = "approval-secret-with-at-least-thirty-two-characters"
    monkeypatch.setenv("CRM_APPROVAL_SECRET", secret)
    monkeypatch.setenv("CRM_WRITE_MODE", "approval_required")
    monkeypatch.setenv("CRM_DATA_DIR", str(tmp_path))
    module = load_crm_module()
    payload = {"case_id": 4, "status": "closed", "notes": "x", "reply_received": True}
    token = mint_token("update_case_status", payload, "supervisor-1", 300)
    assert module._approval_error("update_case_status", payload, token) is None
    # Simulate a restart: fresh module, same data directory.
    module2 = load_crm_module()
    replay = module2._approval_error("update_case_status", payload, token)
    assert replay is not None and "error" in replay
