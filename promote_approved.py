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

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

import policy_keys


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


def _load_reviewer_registry() -> set[str] | None:
    """Approved reviewer identities. When REVIEWER_REGISTRY is set, a decision
    sidecar reviewer_id must appear in it; this stops reviewer_id being an
    unconstrained free-text field. The file is a JSON list of identity strings.
    Returns None when no registry is configured (back-compat for dev)."""
    registry_path = os.getenv("REVIEWER_REGISTRY", "").strip()
    if not registry_path:
        return None
    data = json.loads(Path(registry_path).read_text(encoding="utf-8"))
    identities = data.get("reviewers", data) if isinstance(data, dict) else data
    # Signed mode (C2): a mapping reviewer_id -> Ed25519 public key PEM. The
    # decision sidecar must carry a signature verifiable with this key. This
    # replaces the Unix file-owner check, which did not exist on Windows where
    # the reviewer app runs.
    if isinstance(identities, dict):
        return {
            str(k).strip(): _load_pubkey_pem(v)
            for k, v in identities.items() if str(k).strip()
        }
    # Allowlist-only mode (dev back-compat): a list of ids, signing unenforced.
    if isinstance(identities, list) and all(isinstance(i, str) for i in identities):
        return {i.strip() for i in identities if i.strip()}
    raise ValueError(
        "REVIEWER_REGISTRY must be a JSON list of reviewer ids (dev) or a "
        "mapping reviewer_id -> Ed25519 public key PEM (production/signed)")


def decision_signing_payload(decision: dict) -> bytes:
    """Canonical bytes a reviewer signs to authenticate a decision (C2).
    Reused by promote() verification, the CLI signer and the tests so the
    signed content is identical on every platform."""
    return json.dumps(
        {
            "reviewer_id": str(decision.get("reviewer_id", "")),
            "proposal_sha256": str(decision.get("proposal_sha256", "")),
            "decision": str(decision.get("decision", "")),
            "decided_at_unix": int(decision.get("decided_at_unix", 0)),
        },
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def _load_pubkey_pem(pem: str) -> Ed25519PublicKey:
    key = serialization.load_pem_public_key(pem.encode("utf-8"))
    if not isinstance(key, Ed25519PublicKey):
        raise ValueError("Reviewer registry public key must be Ed25519")
    return key


def promote(review_root: Path, active_dir: Path) -> int:
    # In production mode, both the reviewer registry and signing key are
    # mandatory. An unsigned or unreviewed release must not reach production
    # (V3-C4). Set HERMES_ENV=production before running any live promotion.
    if os.getenv("HERMES_ENV", "").strip().lower() == "production":
        missing = []
        if not os.getenv("REVIEWER_REGISTRY", "").strip():
            missing.append("REVIEWER_REGISTRY")
        if not os.getenv("POLICY_SIGNING_KEY", "").strip():
            missing.append("POLICY_SIGNING_KEY")
        if missing:
            raise RuntimeError(
                f"HERMES_ENV=production requires these env vars to be set: "
                f"{', '.join(missing)}. "
                "Unsigned or un-registry-checked releases must not reach production."
            )

    approved_dir = review_root / "approved"
    if not approved_dir.is_dir():
        raise ValueError("Review root does not contain an approved directory")
    active_dir.mkdir(parents=True, exist_ok=True)
    reviewer_registry = _load_reviewer_registry()

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
        reviewer_id = str(decision.get("reviewer_id", "")).strip()
        if not reviewer_id:
            raise ValueError(f"Missing reviewer identity for {proposal_path.name}")
        if reviewer_registry is not None and reviewer_id not in reviewer_registry:
            raise ValueError(
                f"Reviewer {reviewer_id!r} is not in the approved registry "
                f"(for {proposal_path.name})"
            )
        # C2: in production the typed reviewer_id must be cryptographically
        # authenticated. The decision sidecar carries an Ed25519 signature over
        # its canonical content; we verify it against the reviewer's registered
        # public key. This works identically on Windows and Linux (the previous
        # Unix file-owner check did not exist on Windows, where the reviewer
        # app runs).
        if os.getenv("HERMES_ENV", "").strip().lower() == "production":
            if not isinstance(reviewer_registry, dict):
                raise ValueError(
                    "Production REVIEWER_REGISTRY must map reviewer_id -> "
                    "Ed25519 public key PEM so decisions can be signature-verified")
            pubkey = reviewer_registry.get(reviewer_id)
            if pubkey is None:
                raise ValueError(
                    f"Reviewer {reviewer_id!r} has no registered public key "
                    f"(for {proposal_path.name})")
            signature = str(decision.get("signature", "")).strip()
            if not signature:
                raise ValueError(
                    f"Decision for {proposal_path.name} is not signed by "
                    f"reviewer {reviewer_id!r}")
            try:
                policy_keys.verify(
                    pubkey, decision_signing_payload(decision), signature)
            except policy_keys.PolicyKeyError as exc:
                raise ValueError(
                    f"Decision signature for {proposal_path.name} is invalid "
                    f"(reviewer {reviewer_id!r}): {exc}")
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
    # Sign the manifest with the managed release key (Ed25519). NanoClaw will
    # refuse to load a manifest whose signature does not verify against the
    # public key it trusts, so a forged manifest recomputed by someone with
    # only filesystem access is rejected. POLICY_SIGNING_KEY points at the
    # private key PEM; it lives outside the repo and the policy volumes.
    signing_key_path = os.getenv("POLICY_SIGNING_KEY", "").strip()
    if signing_key_path:
        private_key = policy_keys.load_private_key(signing_key_path)
        manifest["key_id"] = policy_keys.key_id(private_key.public_key())
        manifest_path = active_dir / "manifest.json"
        atomic_json_write(manifest_path, manifest)
        manifest_bytes = manifest_path.read_bytes()
        sidecar = {
            "schema_version": 1,
            "key_id": manifest["key_id"],
            "algorithm": "ed25519",
            "signature": policy_keys.sign(private_key, manifest_bytes),
            "signed_at": datetime.now(timezone.utc).isoformat(),
        }
        atomic_json_write(active_dir / "manifest.json.sig", sidecar)
    else:
        # Unsigned (development only). NanoClaw started with POLICY_PUBLIC_KEY
        # set will reject this manifest, which is the intended fail-closed path.
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
