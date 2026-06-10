# Hermes Production Boundary

Hermes is an offline policy-change proposal service, not a constituent-facing agent.

Supported flow:

1. NanoClaw exports only approved, source-backed corrections after PII screening.
2. `hermes.py` deterministically creates JSON proposals in `review/pending`.
3. A named reviewer uses the desktop review application. The application records the exact proposal SHA-256, reviewer identity, note, decision, and timestamp.
4. `promote_approved.py` verifies the approved sidecar and original bytes, then creates immutable policy rules and a SHA-256 manifest.
5. NanoClaw loads the manifested release read-only and cites rule identifiers.

Telegram, conversational memory, direct active-policy writes, and model-directed CRM access are outside the production boundary. MCP writes are disabled by default. Enabling them for a controlled test requires a payload-bound, short-lived approval token and loopback-only transport.

The review filesystem should reside on encrypted storage with access control and backup. File hashes provide integrity linkage, not non-repudiation; enterprise deployment should additionally sign release manifests with an organisation-managed signing key and publish the signature to an independent audit store.
