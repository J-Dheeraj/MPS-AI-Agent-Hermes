"""Sign a reviewer decision sidecar with an Ed25519 reviewer key (C2).

Run by the reviewer on their own workstation (Windows or Linux). The matching
public key must be registered in REVIEWER_REGISTRY so promote() can verify it.
This replaces the previous reliance on Unix file ownership.

    python3 sign_decision.py --decision path/to/x.json.decision.json \\
        --reviewer-key reviewer-private.pem

The decision JSON must already contain reviewer_id, decision, proposal_sha256
and decided_at_unix; this tool adds/overwrites the `signature` field in place.
Generate a reviewer keypair with: python3 -m policy_keys --gen-key reviewer-private.pem
"""

import argparse
import json
from pathlib import Path

import policy_keys
from promote_approved import decision_signing_payload


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--decision", required=True,
                        help="path to the *.decision.json sidecar")
    parser.add_argument("--reviewer-key", required=True,
                        help="path to the reviewer's Ed25519 private key PEM")
    args = parser.parse_args()

    decision_path = Path(args.decision)
    decision = json.loads(decision_path.read_text(encoding="utf-8"))
    for field in ("reviewer_id", "decision", "proposal_sha256", "decided_at_unix"):
        if not str(decision.get(field, "")).strip():
            raise SystemExit(f"Decision is missing required field: {field}")

    private_key = policy_keys.load_private_key(args.reviewer_key)
    decision["signature"] = policy_keys.sign(
        private_key, decision_signing_payload(decision))
    decision_path.write_text(json.dumps(decision, indent=2), encoding="utf-8")
    print(f"Signed decision for reviewer {decision['reviewer_id']!r}: {decision_path}")


if __name__ == "__main__":
    main()
