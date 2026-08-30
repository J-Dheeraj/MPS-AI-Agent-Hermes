# MPS-AI-Agent-Hermes — Governed Policy Pipeline

> **Architecture reconciliation (2026-06-20, still current).** The production mechanism is **deterministic, Ed25519-signed JSON policy rules**, not the earlier "GEPA skill engine" / "Markdown SKILL files" design. No LLM is in this pipeline at any stage — proposal generation, review, and promotion are all deterministic. "GEPA" survives only as the product name for the proposal → human review → signed promotion cycle.

> **Integration notice (2026-08-25).** [MPS-AI-Agent-_nanoClaw](https://github.com/J-Dheeraj/MPS-AI-Agent-_nanoClaw)'s `main` branch was rewritten on 2026-08-24 into a standalone Tauri + React desktop app with **no server and no policy store**. The `policy_store`/`POLICY_DIR` consumer this pipeline promotes signed rules into no longer exists on nanoClaw's `main` — it is preserved only on nanoClaw's `pre-react-rewrite-backup` branch. **This repository's pipeline currently has no live production consumer** unless nanoClaw is deployed from that backup branch. See [Integration status with nanoClaw](#integration-status-with-nanoclaw).

Hermes is the **offline policy-change governance pipeline** for the MPS AI agent: a deterministic, auditable path from an anonymised correction to a signed, machine-verifiable policy rule, with a mandatory named-human review step in between.

- **Reviewed 2026-07-02** as part of the combined MPS-AI-Agent system, scored **9.4/10** at the time — see [`PRODUCTION_BOUNDARY.md`](PRODUCTION_BOUNDARY.md) for what "production boundary" means and what stays outside it.
- **Verification:** 14 tests pass across `tests/test_governed_pipeline.py`, `tests/test_promote.py`, `tests/test_promote_signing.py`, `tests/test_crm_approval.py`. CI (`.github/workflows/ci.yml`) runs grype pinned to `v0.114.0` with a checksum-verified installer and a fresh vulnerability DB on every push.
- **Two things live in this one repository**, and they are not the same system — see [What's actually in this repository](#whats-actually-in-this-repository) before reading further.

---

## Table of Contents

1. [What's actually in this repository](#whats-actually-in-this-repository)
2. [The governed policy pipeline — step by step](#the-governed-policy-pipeline--step-by-step)
3. [Architecture](#architecture)
4. [The pipeline scripts explained](#the-pipeline-scripts-explained)
   - [hermes.py — deterministic proposal generation](#hermespy--deterministic-proposal-generation)
   - [hermes-review-app — the Tauri review tool](#hermes-review-app--the-tauri-review-tool)
   - [sign_decision.py and policy_keys.py — Ed25519 signing](#sign_decisionpy-and-policy_keyspy--ed25519-signing)
   - [promote_approved.py — verified promotion](#promote_approvedpy--verified-promotion)
5. [The optional live-agent mode (outside the production boundary)](#the-optional-live-agent-mode-outside-the-production-boundary)
   - [profiles/ and hermes-setup.sh](#profiles-and-hermes-setupsh)
   - [mcp-crm-server.py — the CRM bridge](#mcp-crm-serverpy--the-crm-bridge)
6. [Installation and setup — governed pipeline](#installation-and-setup--governed-pipeline)
7. [Operating the pipeline](#operating-the-pipeline)
8. [Security](#security)
9. [Project structure](#project-structure)
10. [Troubleshooting](#troubleshooting)
11. [Integration status with nanoClaw](#integration-status-with-nanoclaw)
12. [Important notes](#important-notes)
13. [References](#references)
14. [License](#license)

---

## What's actually in this repository

This repository has grown two genuinely different subsystems that happen to share a name and a `profiles/` directory. Reading the code makes this unambiguous; reading only the file names does not. Keep them separate in your head:

| | **The governed pipeline** | **The live-agent mode** |
|---|---|---|
| Purpose | Turn anonymised policy corrections into signed policy rules | Run conversational bots (Telegram) with optional CRM write access |
| Entry points | `hermes.py`, `hermes-review-app`, `sign_decision.py`, `promote_approved.py` | `hermes-setup.sh`, `profiles/*/config.yaml`, `mcp-crm-server.py` |
| LLM involved? | **No.** Every stage is deterministic. | Yes — a third-party agent runtime (`hermes-agent`, NousResearch) backed by Ollama. |
| Touches constituent data? | No — inputs are pre-anonymised, source-cited corrections only. | Potentially yes, if wired to Telegram and a CRM backend. |
| Status | **Documented, tested, the supported production flow** (see [`PRODUCTION_BOUNDARY.md`](PRODUCTION_BOUNDARY.md)). | **Explicitly outside the production boundary.** Shipped off by default — every template `config.yaml` in this repo has an empty Telegram token and an empty MCP server map. |

This README documents both, but treats the first as the supported system and the second as an optional, higher-risk capability that exists in the repo and must be deliberately turned on. Do not assume "it's in the repo" means "it's part of the reviewed, production-boundary flow" — `PRODUCTION_BOUNDARY.md` says outright that Telegram, conversational memory, and model-directed CRM access are outside it.

---

## The governed policy pipeline — step by step

```
INPUT (produced elsewhere, outside this repo)
------------------------------------------------
A feedback batch: a JSON file of pre-anonymised, source-cited corrections.
Schema (schema_version: 1):
{
  "batch_id": "batch-1",
  "entries": [{
    "feedback_id": "feedback-1",
    "agency": "HDB",                       # one of HDB/CPF/MSF/MOH/MOM/ICA/GENERAL
    "incorrect_claim": "...",
    "correct_answer": "...",
    "source": {
      "title": "HDB policy",
      "url": "https://www.hdb.gov.sg/policy",   # must be https:// and *.gov.sg
      "effective_date": "2026-01-01"
    },
    "validated_by": "vetter-2",
    "validated_at": "2026-06-10T00:00:00+00:00"
  }]
}

STAGE 1 — PROPOSE (deterministic, no LLM)
--------------------------------------------
  python3 hermes.py batch.json review/

hermes.py, for each entry:
  - rejects the whole batch if schema_version != 1
  - rejects any entry whose agency is not one of the seven valid values
  - re-screens incorrect_claim/correct_answer for PII (NRIC, email, SG phone,
    HDB block/unit) even though the batch is supposed to already be clean —
    defence in depth, not the primary control
  - requires source.url to be an https://*.gov.sg address with a title and
    a valid ISO effective_date
  - writes review/pending/<agency>-<feedback_id>.json — an atomic write
    (write to a temp file, fsync, then os.replace) so a crash never leaves
    a half-written proposal on disk
  - skips (does not overwrite) a proposal that already exists for that id

STAGE 2 — REVIEW (human, via hermes-review-app)
---------------------------------------------------
  A reviewer opens the Tauri app, selects the folder containing
  pending/approved/rejected, types a Reviewer ID, and works through the
  pending queue. For each proposal:
    - reads the proposal's agency, before/after statement, and cited source
    - clicks Approve or Reject, optionally with a note (max 2000 chars)

  On a decision, the app (via its Rust backend):
    - hashes the exact proposal bytes (SHA-256)
    - moves the proposal file to approved/ or rejected/
    - writes a `<file>.decision.json` sidecar containing the reviewer id,
      the decision, the note, the proposal's hash, and a Unix timestamp
    - refuses if a decision for that proposal already exists (no overwrite)

  There is no Edit action — a reviewer approves or rejects the proposal as
  written. If the wording needs to change, reject it and have the correction
  re-submitted.

STAGE 2b — SIGN (optional in dev, required in production)
--------------------------------------------------------------
  On the reviewer's own workstation:
    python3 -m policy_keys --gen-key reviewer-private.pem   # once, ever
    python3 sign_decision.py --decision approved/<file>.decision.json \
        --reviewer-key reviewer-private.pem

  This adds an Ed25519 signature over the decision's canonical fields
  (reviewer_id, proposal_sha256, decision, decided_at_unix) to the sidecar.
  The matching public key must already be registered so promotion can
  verify it — see REVIEWER_REGISTRY below.

STAGE 3 — PROMOTE (deterministic, verifies everything)
------------------------------------------------------------
  python3 promote_approved.py review/ active-policy/

For every approved/*.json (skipping *.decision.json sidecars), promote_approved.py:
  - requires a matching .decision.json sidecar to exist at all
  - requires decision == "approved"
  - recomputes SHA-256 of the proposal bytes and requires it to match the
    sidecar's proposal_sha256 — the exact reviewed bytes, not a re-read
  - requires a non-empty reviewer_id
  - if REVIEWER_REGISTRY is set, requires that reviewer_id to be registered
  - if HERMES_ENV=production, additionally requires REVIEWER_REGISTRY to be
    a reviewer_id -> Ed25519-public-key mapping (not just an allowlist) and
    verifies the sidecar's signature against that key — an unsigned or
    wrongly-signed decision is rejected outright
  - re-validates the proposal's source (https://*.gov.sg, valid date)
  - writes active-policy/<rule_id>.json: {agency, supersedes: before,
    statement: after, source, review: {reviewer_id, note, timestamp, hash}}
  - refuses to silently overwrite an existing rule with different content
  - regenerates active-policy/manifest.json (schema_version, generated_at,
    and a sha256 of every active rule file)
  - if POLICY_SIGNING_KEY is set, signs the manifest with Ed25519 and writes
    active-policy/manifest.json.sig — the consuming policy_store verifies
    this signature and refuses to load an unsigned or wrongly-signed
    manifest when it has been configured with a trusted public key

CONSUMPTION (by a nanoClaw-style server — see the integration notice above)
---------------------------------------------------------------------------------
  A server's policy_store loads active-policy/manifest.json, verifies its
  signature against a trusted public key, verifies every listed rule's
  hash, and serves the matching rules into letter generation. As of
  2026-08-25 this consumer does not exist on nanoClaw's `main` branch.
```

---

## Architecture

```
+-- Feedback batch (JSON, produced outside this repo) --------------+
|   Pre-anonymised, source-cited corrections                        |
+---------------------------------------------------------------------+
        |
        | python3 hermes.py batch.json review/
        v
+-- hermes.py (deterministic — no LLM) --------------------------------+
|   Schema + agency + PII + gov.sg-source validation                   |
|   Atomic write of one proposal JSON per entry                        |
+-------------------------------------------------------------------------+
        |
        | review/pending/<agency>-<id>.json
        v
+-- hermes-review-app (Tauri v2, Rust backend) -------------------------+
|   list_pending / read_proposal / decide_proposal                      |
|   Reviewer approves or rejects, types a Reviewer ID                   |
|   Writes review/{approved,rejected}/<id>.json + <id>.json.decision.json|
+-------------------------------------------------------------------------+
        |
        | sign_decision.py (reviewer's own machine, Ed25519)
        v  adds "signature" to the decision sidecar
        |
        | python3 promote_approved.py review/ active-policy/
        v
+-- promote_approved.py (deterministic — verifies hash + signature) ------+
|   Writes active-policy/<rule_id>.json                                   |
|   Writes + Ed25519-signs active-policy/manifest.json[.sig]              |
+---------------------------------------------------------------------------+
        |
        | active-policy/manifest.json + manifest.json.sig + <rule_id>.json
        v
+-- A server-side policy_store (POLICY_DIR consumer) -----------------------+
|   Verifies manifest signature, verifies each rule's hash, serves rules   |
|   *** Not present on nanoClaw's `main` as of 2026-08-24 — see below ***  |
+------------------------------------------------------------------------------+
```

---

## The pipeline scripts explained

### `hermes.py` — deterministic proposal generation

117 lines. No network access, no LLM call, no dependency beyond the standard library. Its docstring states the design intent directly:

> "This stage is deliberately deterministic. It does not call an LLM and cannot modify active policy."

Every validation happens before a proposal is written, not after: agency must be one of `HDB/CPF/MSF/MOH/MOM/ICA/GENERAL`; both `incorrect_claim` and `correct_answer` are re-scanned for NRIC/email/SG-phone/HDB-block patterns even though the input is supposed to already be anonymised (defence in depth against a broken upstream export, not the primary control); the source must be an `https://` URL on `gov.sg` or a `*.gov.sg` subdomain, with a non-empty title and a parseable `effective_date`. Any single bad entry raises and aborts the whole batch — there is no partial-success mode.

Proposal writes are atomic: write to a temp file in the same directory, `fsync`, then `os.replace`. A process killed mid-write leaves either the old state or nothing — never a half-written proposal.

### `hermes-review-app` — the Tauri review tool

A Tauri v2 app (JavaScript frontend, Rust backend) that does exactly one job: show a pending proposal, record a human decision, move the file. Its own source comment is explicit about what it deliberately does not do:

> "This app intentionally does NOT talk to mps_server or touch any petitioner data — by the time a correction reaches this stage it should already be anonymised down to a 'learning point'... This screen's only job is the human-review gate before a correction is allowed to influence [letter generation]."

Rust commands (`hermes-review-app/src-tauri/src/main.rs`):

| Command | Does |
|---|---|
| `list_pending(base_dir)` | Lists `pending/*.json`, returning id, agency, and issue summary for each |
| `read_proposal(base_dir, file_name)` | Reads one proposal's full detail |
| `decide_proposal(base_dir, file_name, decision, reviewer_id, reviewer_note)` | Validates `reviewer_id` is 3–100 chars and the note ≤2000 chars, hashes the proposal, moves it to `approved/` or `rejected/`, and atomically writes the `.decision.json` sidecar — refusing outright if a decision already exists for that file |

The app never opens a network socket — everything is local filesystem access under a canonicalized root (`canonical_root()`), and file names are sanitized before use in any path join.

### `sign_decision.py` and `policy_keys.py` — Ed25519 signing

`policy_keys.py` is the shared crypto module: generate an Ed25519 keypair (`python3 -m policy_keys --gen-key out.pem`), sign bytes, verify a signature, and compute a stable `key_id` (SHA-256 of the raw 32-byte public key) so a verifier can detect a key mismatch before attempting verification.

`sign_decision.py` is a small CLI a reviewer runs on their own workstation: given a `.decision.json` sidecar and their private key PEM, it signs the sidecar's canonical fields (`reviewer_id`, `proposal_sha256`, `decision`, `decided_at_unix` — reused from `promote_approved.decision_signing_payload()` so the signed content is identical everywhere) and writes the signature into the sidecar in place. This is a deliberate replacement for an earlier design that checked Unix file ownership to authenticate a reviewer — that check silently did nothing on Windows, which is where the review app actually runs.

### `promote_approved.py` — verified promotion

248 lines, and every check in it exists because its absence was a named finding at some point in this repo's history (the inline comments cite them: C2, V3-C4). Promotion:

1. Requires a `.decision.json` sidecar for every approved proposal, and requires `decision == "approved"`.
2. Recomputes the proposal's SHA-256 and requires it to match the sidecar — the promoted content is exactly the bytes a human reviewed, not a re-read that could have changed.
3. Requires a non-empty `reviewer_id`; if `REVIEWER_REGISTRY` is set, requires it to be a known identity.
4. **In production** (`HERMES_ENV=production`): requires `REVIEWER_REGISTRY` to map identities to Ed25519 public keys (not just an allowlist) and `POLICY_SIGNING_KEY` to be set — refusing to start otherwise — then verifies the decision's signature against the reviewer's registered key.
5. Re-validates the source URL (still `https://*.gov.sg`, still a valid date) — the check isn't trusted to have survived from stage 1 unchanged.
6. Writes the active rule and refuses to silently overwrite an existing rule with different content (an identical rewrite is a no-op; a conflicting one is an error).
7. Regenerates `manifest.json` (every active rule's filename and SHA-256) and, if `POLICY_SIGNING_KEY` is set, signs it and writes `manifest.json.sig`. Without a signing key, the manifest is still written — for development only, and the intended fail-closed behaviour is that a `policy_store` configured with a trusted public key rejects an unsigned manifest.

---

## The optional live-agent mode (outside the production boundary)

Everything in this section is explicitly **not** part of the reviewed, tested pipeline above. It exists in the repository, is off by default in every shipped template, and — per `PRODUCTION_BOUNDARY.md` — is not something the production boundary covers. Read it as documentation of a capability an operator could choose to turn on, with the risks that come with turning it on, not as a description of what runs today.

### `profiles/` and `hermes-setup.sh`

`hermes-setup.sh` installs a **third-party** agent runtime called `hermes-agent` (from NousResearch — an unrelated project that happens to share this repository's name) and configures three profiles for it:

| Profile | Intended purpose | May have a Telegram token? |
|---|---|---|
| `mps-main` | MP-facing bot | Yes |
| `mps-volunteers` | Volunteer-facing bot, letter drafting | Yes |
| `mps-vetters` | Vetter-facing bot, reviews letter content | **No — never.** `profiles/mps-vetters/config.yaml`'s own header calls itself "offline, production-safe" and ships with an empty token. |

The setup script's own output is explicit about why: *"Vetters process letter content (constituent data). Telegram is a cloud service. Enabling it here would route constituent data off-premises."* Every shipped `config.yaml` — including `mps-main`'s — has `gateway.telegram.token: ""` and `mcp.servers: {}` out of the box; `mps-main`'s file header states it runs in "OFFLINE SKILL ENGINE MODE" with a comment reading *"DO NOT add bot tokens or CRM access to this config."* Turning any of this into a live bot is a manual, deliberate operator step the script neither performs nor defaults to.

`profiles/*/hermes-config.yaml` (a separate, older config format under `profiles/mps-volunteers/`) still describes the pre-reconciliation design — an `hermes.py`-polls-`/feedback/approved` flow with a `skill_files` list — and is not read by anything in the current governed pipeline described above. Treat it as a leftover, not documentation of current behaviour.

### `mcp-crm-server.py` — the CRM bridge

A 1,050-line [Model Context Protocol](https://modelcontextprotocol.io) server exposing six tools to whatever agent connects to it — `lookup_constituent`, `create_case`, `attach_letter`, `update_case_status`, `get_pending_cases`, `get_todays_queue` — backed by a selectable storage backend (`CRM_BACKEND`: `sqlite` by default, or `google_sheets`, `rest_api`, `sharepoint`, `csv`).

Two things are worth knowing if this is ever enabled:

- **Writes are disabled by default.** `CRM_WRITE_MODE` must be explicitly set to `approval_required` (the only alternative to `disabled`), and every write tool (`create_case`, `attach_letter`, `update_case_status`) requires an `approval_token` parameter. Tokens are minted out-of-band by `crm_approval.py`, run by a human on a separate, approval-only environment — the agent itself has no tool that can mint one. A token is HMAC-signed over the exact canonical JSON payload it authorizes, expires in 30–900 seconds, and is single-purpose (`action` + `payload_sha256` bound together).
- **NRIC masking is enforced in the tool itself**, not left to the caller: `create_case` rejects any `constituent_nric` that is not already in masked form (`S****567A`).

This bridge is not started or wired into anything by default — it is a standalone script an operator would run and connect deliberately.

---

## Installation and setup — governed pipeline

This covers the supported pipeline only. Setting up the optional live-agent mode is `hermes-setup.sh`'s job, and that script's own output tells you the manual steps (Telegram tokens, gateway start commands) — see the warnings above before running it.

### Prerequisites

```bash
git clone https://github.com/J-Dheeraj/MPS-AI-Agent-Hermes.git
cd MPS-AI-Agent-Hermes
pip3 install cryptography    # Ed25519 signing/verification (policy_keys.py)
```

There is no root `requirements.txt` — the governed pipeline's only third-party dependency is `cryptography`, used for Ed25519. (`requirements-crm.txt` is for the separate CRM bridge above, not this pipeline.)

### Generate a signing key (once)

```bash
python3 -m policy_keys --gen-key ./policy-signing-key.pem
# Prints the public key PEM to stdout — distribute this to whatever
# policy_store will consume the manifest (POLICY_PUBLIC_KEY).
# The private key is written with mode 600. Never commit it.
```

### Generate a reviewer key (once per reviewer, on the reviewer's own machine)

```bash
python3 -m policy_keys --gen-key ./reviewer-private.pem
```

Register the resulting public key under that reviewer's identity in your `REVIEWER_REGISTRY` file — a JSON mapping of `reviewer_id -> Ed25519 public key PEM` for production, or a plain JSON list of ids for unsigned development use.

### Run the pipeline end to end

```bash
python3 hermes.py batch.json review/
# -> Created N pending policy proposals

# ... review via hermes-review-app, or manually move a proposal +
#     write/sign a .decision.json sidecar for testing ...

export REVIEWER_REGISTRY=/path/to/reviewer-registry.json
export POLICY_SIGNING_KEY=/path/to/policy-signing-key.pem
export HERMES_ENV=production   # enforces signed-decision verification

python3 promote_approved.py review/ active-policy/
# -> Promoted M reviewed policy rules
```

### Build `hermes-review-app`

```bash
cd hermes-review-app
npm install
npm run tauri dev      # development
npm run tauri build    # production binary, under src-tauri/target/release/
```

---

## Operating the pipeline

```
1. Wherever corrections are collected and vetted, export an approved,
   anonymised batch as JSON matching the schema in step 1 of the pipeline
   above. This repository does not produce that export itself — it is the
   input contract, not a feature of this repo.

2. Run hermes.py against the batch:
     python3 hermes.py batch.json review/

3. Open hermes-review-app, point it at review/, type your Reviewer ID,
   and work through the pending queue: read each proposal's before/after
   and cited source, then Approve or Reject.

4. On your own workstation, sign each approved decision:
     python3 sign_decision.py --decision review/approved/<file>.decision.json \
         --reviewer-key your-reviewer-private.pem

5. Promote:
     python3 promote_approved.py review/ active-policy/

6. Point your policy_store's POLICY_DIR at active-policy/ and its
   POLICY_PUBLIC_KEY at the signing public key from setup. It will refuse
   to load the manifest if the signature doesn't verify.
```

There is no built-in scheduler, cron entry, or daemon in this repository — steps 2–5 are run manually or wired into whatever automation you build around them.

---

## Security

| Control | Implementation |
|---|---|
| **No LLM in the pipeline** | `hermes.py` and `promote_approved.py` are pure deterministic Python — no model call, no possibility of a hallucinated policy rule. |
| **PII re-screened at proposal time** | `hermes.py` scans `incorrect_claim`/`correct_answer` for NRIC, email, SG phone numbers, and HDB block/unit patterns even though the input batch is expected to already be clean — defence in depth. |
| **Source provenance required** | Every proposal and every promoted rule must cite an `https://` URL on `gov.sg` (or a `*.gov.sg` subdomain), a title, and a valid effective date — checked twice, once at proposal and once at promotion. |
| **Exact-bytes review binding** | Promotion recomputes the SHA-256 of the proposal file and requires it to match the reviewer's recorded hash — a proposal edited after review is rejected, not silently re-approved. |
| **Named, optionally signed reviewers** | `reviewer_id` is mandatory; `REVIEWER_REGISTRY` can restrict it to known identities; in `HERMES_ENV=production`, the decision must carry an Ed25519 signature verifiable against that reviewer's registered public key. |
| **Cross-platform signing, not file-ownership checks** | The reviewer-authentication mechanism was moved from a Unix file-owner check (silently inert on Windows) to Ed25519 signatures, which verify identically everywhere. |
| **Manifest signed, fail-closed on the consumer side** | `promote_approved.py` signs `manifest.json` with `POLICY_SIGNING_KEY` when set; a consuming `policy_store` configured with the matching public key refuses an unsigned or forged manifest. |
| **No silent overwrites** | Both proposal generation and promotion refuse to overwrite an existing file with different content — a naming collision is an error, not data loss. |
| **CRM writes disabled by default, then token-gated** | `CRM_WRITE_MODE=disabled` unless explicitly changed; writes additionally require a short-lived (30–900s), payload-bound HMAC token minted by a human on a separate approval workflow — the agent has no tool to mint its own approval. |
| **NRIC masking enforced server-side** | `mcp-crm-server.py`'s `create_case` rejects an unmasked NRIC outright, rather than trusting the caller to have masked it. |
| **CI hardened and fail-closed** | grype pinned to `v0.114.0` with a checksum-verified installer and a forced-fresh vulnerability database (no stale-DB bypass); GitHub Actions pinned by commit SHA; `pip-audit --strict`, SBOM generation, and gitleaks secret scanning all run on every push. |

---

## Project structure

```
MPS-AI-Agent-Hermes/
|
+-- hermes.py                     <- Stage 1: deterministic batch -> pending proposals
+-- promote_approved.py           <- Stage 3: verify + promote approved proposals
+-- sign_decision.py              <- Reviewer-side: Ed25519-sign a decision sidecar
+-- policy_keys.py                <- Shared Ed25519 keygen/sign/verify
|
+-- hermes-review-app/            <- Stage 2: Tauri v2 review tool
|   +-- src/main.js                <- UI: pending queue, proposal detail, approve/reject
|   +-- src-tauri/src/main.rs      <- list_pending / read_proposal / decide_proposal
|
+-- crm_approval.py               <- Live-agent mode: mint short-lived CRM write tokens
+-- mcp-crm-server.py             <- Live-agent mode: MCP CRM bridge (5 backends)
+-- requirements-crm.txt          <- Deps for the CRM bridge only
+-- .env.example                  <- CRM backend configuration template
|
+-- hermes-setup.sh               <- Live-agent mode: installs hermes-agent + 3 profiles
+-- profiles/
|   +-- mps-main/       config.yaml, SOUL.md      <- MP bot (Telegram-capable)
|   +-- mps-volunteers/ config.yaml, SOUL.md, hermes-config.yaml (legacy, unused)
|   +-- mps-vetters/    config.yaml, SOUL.md      <- never gets a Telegram token
|
+-- skills/                       <- Markdown policy knowledge for the live-agent mode
|   +-- SKILL-hdb.md, SKILL-cpf.md, SKILL-msf.md, SKILL-moh.md,
|       SKILL-mom.md, SKILL-ica.md, SKILL-letter.md, SKILL-feedback.md
|
+-- tests/
|   +-- test_governed_pipeline.py  <- End-to-end: batch -> proposal -> decision -> promote
|   +-- test_promote.py
|   +-- test_promote_signing.py
|   +-- test_crm_approval.py
|
+-- PRODUCTION_BOUNDARY.md        <- What is and isn't the supported flow
+-- OFFLINE-MODE.md               <- The offline-mode rationale for the profiles above
+-- README.md                     <- this file
```

`review/` and `active-policy/` are not checked into the repository — they are working directories you create when you run the pipeline (see [Installation and setup](#installation-and-setup--governed-pipeline)).

---

## Troubleshooting

**`hermes.py` raises "Unsupported agency" or "Unsafe feedback entry"**

The input batch failed validation — this is by design, not a bug. Check that every entry's `agency` is one of `HDB/CPF/MSF/MOH/MOM/ICA/GENERAL`, and that `incorrect_claim`/`correct_answer` contain no NRIC, email, phone number, or block/unit pattern. There is no partial-success mode — fix the batch and re-run.

**`promote_approved.py` raises "Missing decision sidecar"**

Every file in `approved/` needs a matching `<file>.decision.json` written by `hermes-review-app` (or hand-constructed to match its schema for testing). A proposal moved into `approved/` any other way will fail here.

**`promote_approved.py` raises "Proposal hash mismatch"**

The proposal file was modified after the sidecar recorded its hash. This is the review-binding control working as intended — re-review the current file rather than promoting stale content.

**`promote_approved.py` raises "Decision signature is invalid" or refuses to start in `HERMES_ENV=production`**

In production mode, `REVIEWER_REGISTRY` must map reviewer ids to Ed25519 public keys (not a plain id list) and `POLICY_SIGNING_KEY` must be set. Run `sign_decision.py` on the reviewer's own machine with their private key before promoting.

**`hermes-review-app` shows an empty pending list**

`list_pending` only reads `<base_dir>/pending/*.json`. Confirm you selected the folder containing `pending/approved/rejected`, not one of those subfolders directly, and that `hermes.py` actually ran and produced output.

**I ran `hermes-setup.sh` and now have live Telegram bots I didn't mean to fully configure**

The script only creates profiles and copies templates — every shipped config ships with an empty Telegram token, so nothing goes live until you edit a `config.yaml` and add one yourself. If a bot is unexpectedly responding, check `~/.hermes/profiles/*/config.yaml` for a token you (or someone) added, and stop the gateway with `hermes --profile <name> gateway stop`.

---

## Integration status with nanoClaw

As of **2026-08-24**, nanoClaw's `main` branch is a standalone Tauri + React desktop app with no server component. It talks directly to a local Ollama instance for letter drafting and has no `policy_store`, no `POLICY_DIR`, and nothing that reads `active-policy/manifest.json`.

The pipeline in this repository still produces exactly what a `policy_store` like the one nanoClaw previously shipped expects — signed JSON policy rules and a signed manifest — but as of this integration notice, **nothing consumes that output on nanoClaw's `main`**. The consumer exists, unmodified, on nanoClaw's **`pre-react-rewrite-backup`** branch.

Practically, this means:

- If you are running nanoClaw from `main`, this pipeline currently has no effect on letter generation — there is no policy store for it to feed.
- If you are running nanoClaw from `pre-react-rewrite-backup`, the integration described throughout this README (a server-side `policy_store` loading `active-policy/manifest.json`) still applies as documented.
- This is not a bug in this repository — Hermes has not changed its contract. The consumer on the other side of that contract moved.

---

## Important notes

1. **This pipeline makes no judgment about correctness.** It verifies provenance, hashing, and signatures — not whether the *content* of a correction is actually right. A reviewer who approves a wrong-but-well-sourced correction will get it promoted exactly as reviewed. Verify against the cited source before approving, not after.

2. **There is no automatic scheduling.** Unlike the pre-reconciliation design this README used to describe, nothing in this repository runs on a cron or timer. Steps 2–5 under [Operating the pipeline](#operating-the-pipeline) are run manually or by automation you build yourself.

3. **`skills/*.md` and `profiles/*/hermes-config.yaml` are not part of the governed pipeline.** They belong to the optional live-agent mode and an older, unused config format respectively. Do not expect editing them to affect anything `hermes.py` or `promote_approved.py` does.

4. **Rollback is a filesystem operation.** There is no built-in undo for a promoted rule. To retract one, remove its `<rule_id>.json` from `active-policy/`, re-run `promote_approved.py` (which will regenerate and re-sign `manifest.json` from whatever remains), and redeploy the manifest to the consumer.

5. **A reviewer's private key is that reviewer's sole credential.** There is no password reset — losing it means generating a new keypair and re-registering under `REVIEWER_REGISTRY`, and any decisions already signed with the lost key remain valid (the signature verifies against a key that still existed at signing time).

---

## References

- [PRODUCTION_BOUNDARY.md](PRODUCTION_BOUNDARY.md) — the authoritative statement of what is and isn't the supported flow
- [OFFLINE-MODE.md](OFFLINE-MODE.md) — rationale for keeping the live-agent profiles offline by default
- [MPS-AI-Agent-_nanoClaw](https://github.com/J-Dheeraj/MPS-AI-Agent-_nanoClaw) — the system this pipeline's output is designed to feed (see [Integration status](#integration-status-with-nanoclaw) for the current gap)
- [Model Context Protocol](https://modelcontextprotocol.io) — the protocol `mcp-crm-server.py` implements
- [Tauri v2 docs](https://v2.tauri.app)
- [Ollama](https://ollama.com)
- [HDB](https://www.hdb.gov.sg) | [CPF](https://www.cpf.gov.sg) | [MOM](https://www.mom.gov.sg) | [MOH](https://www.moh.gov.sg) | [MSF](https://www.msf.gov.sg) | [ICA](https://www.ica.gov.sg)

---

## License

MIT
