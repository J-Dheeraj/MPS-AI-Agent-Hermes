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
