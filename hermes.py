"""Create review proposals from a source-backed NanoClaw feedback batch.

This stage is deliberately deterministic. It does not call an LLM and cannot
modify active policy. Human review and promotion are separate steps.
"""

import argparse
import json
import os
import re
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse

PII_PATTERNS = [
    re.compile(r"\b[STFGM]\d{7}[A-Z]\b", re.IGNORECASE),
    re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b"),
    re.compile(r"\b(?:\+?65[-\s]?)?[689]\d{7}\b"),
    re.compile(r"\b(?:bl(?:oc)?k\s*\d+[A-Z]?)\b", re.IGNORECASE),
    re.compile(r"#\d{1,3}-\d{1,4}[A-Z]?"),
]
VALID_AGENCIES = {"HDB", "CPF", "MSF", "MOH", "MOM", "ICA", "GENERAL"}


def contains_pii(value: str) -> bool:
    return any(pattern.search(value or "") for pattern in PII_PATTERNS)


def validate_source(source: dict) -> None:
    parsed = urlparse(str(source.get("url", "")))
    host = (parsed.hostname or "").lower()
    if parsed.scheme != "https" or not (host == "gov.sg" or host.endswith(".gov.sg")):
        raise ValueError("Proposal source must be an HTTPS gov.sg URL")
    datetime.fromisoformat(str(source.get("effective_date", "")))
    if not str(source.get("title", "")).strip():
        raise ValueError("Proposal source title is required")


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


def generate(batch_path: Path, review_root: Path) -> int:
    batch = json.loads(batch_path.read_text(encoding="utf-8"))
    if batch.get("schema_version") != 1 or not isinstance(batch.get("entries"), list):
        raise ValueError("Unsupported feedback batch schema")

    for directory in ("pending", "approved", "rejected"):
        (review_root / directory).mkdir(parents=True, exist_ok=True)

    created = 0
    for entry in batch["entries"]:
        agency = str(entry.get("agency", "")).upper()
        if agency not in VALID_AGENCIES:
            raise ValueError(f"Unsupported agency: {agency}")
        incorrect = str(entry.get("incorrect_claim", "")).strip()
        correct = str(entry.get("correct_answer", "")).strip()
        if not incorrect or not correct or contains_pii(incorrect) or contains_pii(correct):
            raise ValueError(f"Unsafe feedback entry: {entry.get('feedback_id')}")
        source = entry.get("source") or {}
        validate_source(source)

        feedback_id = str(entry.get("feedback_id", ""))
        safe_feedback_id = re.sub(r"[^A-Za-z0-9_-]", "", feedback_id)[:36]
        if not safe_feedback_id:
            raise ValueError("Feedback entry is missing a safe identifier")
        proposal_id = f"{agency.lower()}-{safe_feedback_id}"
        proposal = {
            "schema_version": 1,
            "id": proposal_id,
            "agency": agency,
            "issue": incorrect,
            "correction": correct,
            "before": incorrect,
            "after": correct,
            "source": source,
            "evidence": {
                "batch_id": batch.get("batch_id"),
                "feedback_ids": [feedback_id],
                "validated_by": entry.get("validated_by"),
                "validated_at": entry.get("validated_at"),
            },
            "generated_at": datetime.now(timezone.utc).isoformat(),
        }
        destination = review_root / "pending" / f"{proposal_id}.json"
        if destination.exists():
            continue
        atomic_json_write(destination, proposal)
        created += 1
    return created


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("batch", type=Path)
    parser.add_argument("review_root", type=Path)
    args = parser.parse_args()
    count = generate(args.batch.resolve(), args.review_root.resolve())
    print(f"Created {count} pending policy proposals")


if __name__ == "__main__":
    main()
