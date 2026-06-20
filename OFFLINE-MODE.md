# Hermes — Offline Skill Engine Mode

> **Architecture reconciliation (2026-06-20).** The production policy mechanism is **deterministic, Ed25519-signed JSON policy rules** loaded by the server's `policy_store` from `POLICY_DIR` (manifest + per-rule JSON, validity/supersession/relevance ranking). The legacy "GEPA skill engine" framing and "Markdown SKILL files injected into the prompt" descriptions below are **superseded**: no Markdown skill is injected into letter generation, and proposal generation is deterministic (no LLM converts corrections into policy). "GEPA" persists only as a product name for the deterministic proposal -> human review -> signed promotion pipeline.

## What this means

This Hermes instance does NOT run as a live agent.
It has no Telegram connection, no CRM access, and no constituent data.

It runs **once per week** as an offline GEPA skill improvement engine,
processing anonymised correction patterns exported from nanoClaw.

## Why offline

nanoClaw handles all live constituent interactions with a full security model:
- OneCLI Agent Vault (API key never in container)
- Docker container isolation per group
- Local-only voice (whisper.cpp) and embeddings (Ollama)
- Sender allowlist with drop mode
- Mount allowlist blocking sensitive paths

Hermes complements this by improving the agent's reasoning patterns weekly,
without ever touching constituent data.

## The data flow

```
nanoClaw (live) ──→ feedback-log.md (anonymised) ──→ Hermes GEPA
                                                           │
                                            skills/auto/*.md (reviewed)
                                                           │
                                         nanoClaw CLAUDE.md update
```

## Security boundary

The ONLY data that crosses from nanoClaw to Hermes:
- Policy threshold corrections (e.g. "CHAS Blue is $1,800 not $2,000")
- Case type patterns (generic, no individuals)
- Letter structure improvements

The NEVER list:
- NRIC numbers
- Constituent names or addresses
- Case reference numbers
- CRM records of any kind
- Financial details tied to any individual

## Config summary (profiles/mps-main/config.yaml)

```yaml
gateway:
  telegram:
    token: ""          # empty — no live connection
    allowed_users: []  # empty — no live users

skills:
  evolution:
    enabled: true
    auto_capture: false   # no live sessions to capture from
  curator:
    enabled: true
    interval_days: 7

mcp:
  servers: {}            # no CRM, no tools
```

## Weekly operation

Run from the nanoClaw machine every Sunday:

```bash
cd ~/nanoclaw
bash weekly-skill-update.sh
```

The script handles export, PII scanning, GEPA trigger, review prompt,
merge prompt, nanoClaw restart, and log archiving automatically.

## GEPA output location

Generated and updated skill files appear in:
```
skills/auto/
```

Review every file before applying to nanoClaw. Check for:
- ✅ Threshold corrections matching real feedback
- ✅ New case patterns from real session types
- ❌ Fabricated policy (anything unrecognised)
- ❌ Text resembling constituent details

## Manual GEPA trigger (if hermes CLI not in PATH)

Start Hermes in interactive mode:
```bash
hermes --profile mps-main
```

Then type:
```
run skills evolve now
```

## Integration reference

Full workflow documented in:
`MPS-AI-Agent-_nanoClaw/INTEGRATION.md`
