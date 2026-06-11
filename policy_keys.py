"""Ed25519 signing/verification for the governed policy release chain.

The signing key is the *release authority*. A policy manifest is only trusted
by NanoClaw if it carries a valid signature from a key NanoClaw has been
configured to trust. This converts the original weakness — "anyone with
filesystem access can forge an approval and recompute the manifest" — into
"an attacker also needs the managed private signing key", which is held
outside the repository and outside the review/active policy volumes.

Key handling:
  - Private key: Ed25519 PEM, path in env POLICY_SIGNING_KEY. Never committed.
  - Public key:  Ed25519 PEM, path in env POLICY_PUBLIC_KEY (consumed by
                 NanoClaw policy_store). Safe to distribute.
  - key_id:      sha256 of the raw 32-byte public key, hex. Embedded in the
                 manifest and signature sidecar so a verifier can detect a
                 key mismatch before attempting verification.

Generate a key pair:
    python3 -m policy_keys --gen-key ./policy-signing-key.pem
which writes the private key to the given path (chmod 600) and prints the
matching public key PEM to stdout for distribution to NanoClaw.
"""

from __future__ import annotations

import base64
import hashlib
import os
import sys
from pathlib import Path

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import (
    Ed25519PrivateKey,
    Ed25519PublicKey,
)
from cryptography.exceptions import InvalidSignature


class PolicyKeyError(RuntimeError):
    pass


def _public_raw(public_key: Ed25519PublicKey) -> bytes:
    return public_key.public_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PublicFormat.Raw,
    )


def key_id(public_key: Ed25519PublicKey) -> str:
    """Stable identifier for a public key: sha256 of its raw 32 bytes."""
    return hashlib.sha256(_public_raw(public_key)).hexdigest()


def load_private_key(path: str | os.PathLike) -> Ed25519PrivateKey:
    data = Path(path).read_bytes()
    key = serialization.load_pem_private_key(data, password=None)
    if not isinstance(key, Ed25519PrivateKey):
        raise PolicyKeyError("Signing key must be an Ed25519 private key")
    return key


def load_public_key(path: str | os.PathLike) -> Ed25519PublicKey:
    data = Path(path).read_bytes()
    key = serialization.load_pem_public_key(data)
    if not isinstance(key, Ed25519PublicKey):
        raise PolicyKeyError("Public key must be an Ed25519 public key")
    return key


def sign(private_key: Ed25519PrivateKey, payload: bytes) -> str:
    """Return a base64 signature over payload."""
    return base64.b64encode(private_key.sign(payload)).decode("ascii")


def verify(public_key: Ed25519PublicKey, payload: bytes, signature_b64: str) -> None:
    """Raise PolicyKeyError if the signature does not verify."""
    try:
        public_key.verify(base64.b64decode(signature_b64), payload)
    except (InvalidSignature, ValueError, TypeError) as exc:
        raise PolicyKeyError("Manifest signature is invalid") from exc


def _gen_key(out_path: str) -> None:
    private_key = Ed25519PrivateKey.generate()
    pem = private_key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    )
    path = Path(out_path)
    path.write_bytes(pem)
    os.chmod(path, 0o600)
    public_pem = private_key.public_key().public_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    )
    sys.stderr.write(
        f"Private key written to {path} (chmod 600). key_id="
        f"{key_id(private_key.public_key())}\n"
        "Distribute the public key below to NanoClaw (POLICY_PUBLIC_KEY):\n"
    )
    sys.stdout.write(public_pem.decode("ascii"))


if __name__ == "__main__":
    if len(sys.argv) == 3 and sys.argv[1] == "--gen-key":
        _gen_key(sys.argv[2])
    else:
        sys.stderr.write("usage: python3 -m policy_keys --gen-key <out.pem>\n")
        sys.exit(2)
