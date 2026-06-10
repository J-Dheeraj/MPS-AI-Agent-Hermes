"""Mint a short-lived CRM write approval token for an exact JSON payload.

Run this outside the agent process. The private approval secret must be
available only to the human-operated approval environment.
"""

import argparse
import base64
import hashlib
import hmac
import json
import os
import time


def canonical_payload(payload: dict) -> str:
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def mint_token(action: str, payload: dict, approved_by: str, ttl_seconds: int) -> str:
    secret = os.getenv("CRM_APPROVAL_SECRET", "")
    if len(secret) < 32:
        raise SystemExit("CRM_APPROVAL_SECRET must contain at least 32 characters")
    if ttl_seconds < 30 or ttl_seconds > 900:
        raise SystemExit("TTL must be between 30 and 900 seconds")
    if not approved_by.strip():
        raise SystemExit("approved_by is required")

    claims = {
        "action": action,
        "payload_sha256": hashlib.sha256(
            canonical_payload(payload).encode("utf-8")
        ).hexdigest(),
        "approved_by": approved_by.strip(),
        "exp": int(time.time()) + ttl_seconds,
    }
    raw = json.dumps(
        claims, sort_keys=True, separators=(",", ":"), ensure_ascii=True
    ).encode("utf-8")
    encoded = base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")
    signature = hmac.new(secret.encode("utf-8"), raw, hashlib.sha256).hexdigest()
    return f"{encoded}.{signature}"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--action",
        required=True,
        choices=["create_case", "attach_letter", "update_case_status"],
    )
    parser.add_argument("--payload-json", required=True)
    parser.add_argument("--approved-by", required=True)
    parser.add_argument("--ttl", type=int, default=300)
    args = parser.parse_args()

    try:
        payload = json.loads(args.payload_json)
    except json.JSONDecodeError as exc:
        raise SystemExit(f"Invalid --payload-json: {exc}") from exc
    if not isinstance(payload, dict):
        raise SystemExit("--payload-json must be a JSON object")

    print(mint_token(args.action, payload, args.approved_by, args.ttl))


if __name__ == "__main__":
    main()
