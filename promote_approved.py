"""Promote verified Hermes decisions into NanoClaw's active policy store."""

import argparse
import hashlib
import json
import os
import re
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse


def sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def atomic_json_write(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.", suffix=".tmp", dir=path.parent
    )
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, indent=2, sort_keys=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary_name, path)
    except Exception:
        Path(temporary_name).unlink(missing_ok=True)
        raise


def validate_source(source: dict) -> None:
    parsed = urlparse(str(source.get("url", "")))
    host = (parsed.hostname or "").lower()
    if parsed.scheme != "https" or not (host == "gov.sg" or host.endswith(".gov.sg")):
        raise ValueError("Approved source must be an HTTPS gov.sg URL")
    datetime.fromisoformat(str(source.get("effective_date", "")))


def promote(review_root: Path, active_dir: Path) -> int:
    approved_dir = review_root / "approved"
    if not approved_dir.is_dir():
        raise ValueError("Review root does not contain an approved directory")
    active_dir.mkdir(parents=True, exist_ok=True)

    promoted = 0
    for proposal_path in sorted(approved_dir.glob("*.json")):
        if proposal_path.name.endswith(".decision.json"):
            continue
        decision_path = approved_dir / f"{proposal_path.name}.decision.json"
        if not decision_path.is_file():
            raise ValueError(f"Missing decision sidecar for {proposal_path.name}")

        proposal_bytes = proposal_path.read_bytes()
        proposal = json.loads(proposal_bytes)
        decision = json.loads(decision_path.read_text(encoding="utf-8"))
        if decision.get("decision") != "approved":
            raise ValueError(f"Non-approved decision beside {proposal_path.name}")
        if decision.get("proposal_sha256") != sha256_hex(proposal_bytes):
            raise ValueError(f"Proposal hash mismatch for {proposal_path.name}")
        if not str(decision.get("reviewer_id", "")).strip():
            raise ValueError(f"Missing reviewer identity for {proposal_path.name}")
        if proposal.get("schema_version") != 1:
            raise ValueError(f"Unsupported proposal schema for {proposal_path.name}")
        validate_source(proposal.get("source") or {})

        rule_id = str(proposal.get("id", ""))
        if not re.fullmatch(r"[a-z0-9_-]{3,100}", rule_id):
            raise ValueError(f"Unsafe rule id in {proposal_path.name}")
        rule = {
            "schema_version": 1,
            "rule_id": rule_id,
            "agency": proposal.get("agency"),
            "supersedes": proposal.get("before"),
            "statement": proposal.get("after"),
            "source": proposal.get("source"),
            "review": {
                "reviewer_id": decision.get("reviewer_id"),
                "reviewer_note": decision.get("reviewer_note"),
                "decided_at_unix": decision.get("decided_at_unix"),
                "proposal_sha256": decision.get("proposal_sha256"),
            },
        }
        destination = active_dir / f"{rule_id}.json"
        if destination.exists():
            existing = json.loads(destination.read_text(encoding="utf-8"))
            if existing == rule:
                continue
            raise ValueError(f"Refusing to overwrite existing active rule {rule_id}")
        atomic_json_write(destination, rule)
        promoted += 1

    manifest = {
        "schema_version": 1,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "rules": [
            {"file": path.name, "sha256": sha256_hex(path.read_bytes())}
            for path in sorted(active_dir.glob("*.json"))
            if path.name != "manifest.json"
        ],
    }
    atomic_json_write(active_dir / "manifest.json", manifest)
    return promoted


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("review_root", type=Path)
    parser.add_argument("active_policy_dir", type=Path)
    args = parser.parse_args()
    count = promote(args.review_root.resolve(), args.active_policy_dir.resolve())
    print(f"Promoted {count} reviewed policy rules")


if __name__ == "__main__":
    main()
