# MPS-AI-Agent-Hermes — Offline Skill Engine (GEPA)

A weekly offline skill improvement engine for the [MPS-AI-Agent-nanoClaw](https://github.com/J-Dheeraj/MPS-AI-Agent-_nanoClaw) production system — built on the **Hermes Agent** platform by Nous Research.

This repo does **not** run as a live agent handling constituent interactions. It runs once per week to process anonymised correction patterns from nanoClaw sessions and improve the agent's policy reasoning via **GEPA** (Generalised Experience-driven Policy Adaptation, ICLR 2026).

> **Production system:** [MPS-AI-Agent-nanoClaw](https://github.com/J-Dheeraj/MPS-AI-Agent-_nanoClaw) handles all live constituent interactions (WhatsApp, Telegram, Web UI) with full security controls. See that repo's [INTEGRATION.md](https://github.com/J-Dheeraj/MPS-AI-Agent-_nanoClaw/blob/main/INTEGRATION.md) for the full combined workflow.

---

## Two-system architecture

```
nanoClaw (production) ─────────────────────────────────────────
  All live constituent interactions
  WhatsApp / Telegram / Web UI / CLI
  Security: OneCLI vault, Docker isolation, local AI
  CRM: case logging, letter storage, overdue tracking
                │
                │  Weekly export — anonymised patterns only
                │  No NRIC. No names. No case IDs.
                │  Human review required before export.
                ▼
Hermes (this repo) ─────────────────────────────────────────────
  Offline skill improvement engine
  GEPA processes correction patterns → generates updated SKILL files
  Human reviews every generated change before approval
                │
                │  Approved improvements merged into nanoClaw CLAUDE.md
                ▼
nanoClaw restarts with improved reasoning
```

**Security boundary:** constituent data never enters this system. Only anonymised policy correction patterns flow in. See [INTEGRATION.md](https://github.com/J-Dheeraj/MPS-AI-Agent-_nanoClaw/blob/main/INTEGRATION.md) for the full security rules.

---

## What GEPA does

After each MPS session, volunteers and the MP log corrections in nanoClaw:

```
/feedback CHAS Blue threshold cited as $2,000 → correct is $1,800/month household | agency: MOH
/feedback EHG ceiling cited as $9,000 → correct ceiling is $8,000 for families | agency: HDB
```

Every Sunday, `weekly-skill-update.sh` (in the nanoClaw repo) exports these anonymised patterns to this repo and triggers a GEPA evolution cycle:

1. GEPA analyses the correction patterns
2. Generates updated or new SKILL files in `skills/auto/`
3. Human reviews every generated file — nothing is applied automatically
4. Approved improvements are manually merged into nanoClaw's `CLAUDE.md`
5. nanoClaw restarts with improved policy knowledge

After 5+ cycles, benchmarks show **15–30% task success rate improvement** on MPS-type cases.

---

## Why offline, not live

Running Hermes as a live agent would mean:

- Constituent data (NRIC, names, case details) entering a system without OneCLI vault, Docker isolation, or mount allowlist protection
- Two live agent systems for the same roles creating duplicate responses and CRM conflicts
- Maintenance of two separate policy knowledge bases that drift apart over time

The offline model gives you GEPA's self-improvement capability without compromising the security architecture. nanoClaw handles all constituent-facing interactions. Hermes handles only anonymised pattern evolution, offline.

---

## SKILL files — policy knowledge base

8 Markdown skill files covering all agencies encountered at Singapore MPS sessions. All three profiles share these files. Hermes loads them on demand via GEPA's retrieval system.

| File | Coverage |
|---|---|
| `SKILL-hdb.md` | EHG, PHG, Step-Up grants; new flat ceilings; rental scheme; Fresh Start 2026; letter addressees |
| `SKILL-cpf.md` | Account types; OW ceiling ($8,000/Jan 2026); withdrawal at 55; CPF LIFE; MediSave; MRSS |
| `SKILL-msf.md` | ComCare tiers (Crisis/SMTA/LTA); Silver Support; ComLink+; SSO referral process |
| `SKILL-moh.md` | CHAS Blue/Orange; MediFund; MediShield Life; CareShield Life; ElderShield; Pioneer/Merdeka Generation |
| `SKILL-mom.md` | EP ($5,600/Sep 2025), S Pass ($3,150); LTVP ($2,500 sponsor); TADM; retrenchment; Workfare |
| `SKILL-ica.md` | PR/SC holistic assessment; LTVP/LTVP+; REP; 7-point PR appeal strategy |
| `SKILL-letter.md` | Standard MP appeal letter format; tone rules; 8 agency physical addresses; required fields |
| `SKILL-feedback.md` | `/feedback` command syntax; GEPA capture; skill evolution; weekly review schedule |

GEPA auto-generates additional skills in `skills/auto/` — named by case type (e.g. `hdb-rental-widow-pattern.md`, `comcare-urgent-crisis-referral.md`). Review these weekly before applying to nanoClaw.

---

## Profile identities (offline reference)

The three profiles define the agent roles used in the combined system. In offline mode, these are reference documents — the profiles are not connected to any live channel.

### mps-main — MP private channel identity
`profiles/mps-main/SOUL.md`: pre-session briefing, case history lookup, complex triage, appeal letter drafting, overdue follow-up, GEPA feedback loop.

### mps-volunteers — Volunteer intake team identity
`profiles/mps-volunteers/SOUL.md`: fast case triage (3–5 lines), complete letter drafts, policy questions, case logging, group Telegram mode.

### mps-vetters — Vetter review team identity
`profiles/mps-vetters/SOUL.md`: 6-point letter review, PASS / NEEDS REVISION / FLAG verdicts, 2025/2026 policy quick-reference, no CRM access.

---

## Offline mode configuration

`profiles/mps-main/config.yaml` is set to offline mode — no live connections:

```yaml
gateway:
  telegram:
    token: ""        # offline — no bot connection
    allowed_users: []

skills:
  evolution:
    enabled: true
    auto_capture: false   # no live sessions; patterns come from nanoClaw export
  curator:
    enabled: true
    interval_days: 7

mcp:
  servers: {}        # no CRM — constituent data stays in nanoClaw
```

See [OFFLINE-MODE.md](./OFFLINE-MODE.md) for the full configuration reference.

---

## Weekly operation

The full pipeline runs from the nanoClaw machine:

```bash
cd ~/nanoclaw
bash weekly-skill-update.sh
```

What the script does:
1. Scans `feedback-log.md` for NRIC/phone patterns — auto-rejects if found
2. Prompts manual review of the log before export
3. Copies anonymised patterns to this repo as `feedback-input.md`
4. Triggers GEPA evolution cycle
5. Shows `skills/auto/` changes for your review
6. Prompts manual merge of approved changes into nanoClaw `CLAUDE.md`
7. Restarts nanoClaw
8. Archives the week's log and resets for next week

### Manual GEPA trigger (if needed)

```bash
hermes --profile mps-main skills evolve --now
hermes --profile mps-main skills curator --run
```

Or in interactive mode:
```
run skills evolve now
```

---

## CRM Bridge

`mcp-crm-server.py` is included for reference — the same server used by nanoClaw. In offline mode, the CRM bridge is **not wired** to any Hermes profile. Constituent case data remains exclusively in nanoClaw.

| Tool | Available in offline Hermes? |
|---|---|
| `lookup_constituent` | ❌ No CRM access |
| `create_case` | ❌ No CRM access |
| `attach_letter` | ❌ No CRM access |
| `update_case_status` | ❌ No CRM access |
| `get_pending_cases` | ❌ No CRM access |
| `get_todays_queue` | ❌ No CRM access |

All CRM operations happen in nanoClaw only.

---

## Setup

### Prerequisites

```bash
# 1. Python 3 and pip
sudo apt-get update && sudo apt-get install -y python3 python3-pip curl

# 2. Clone into Linux filesystem
cd ~
git clone https://github.com/J-Dheeraj/MPS-AI-Agent-Hermes mps-hermes-agent
cd mps-hermes-agent

# 3. Create skills/auto/ directory
mkdir -p skills/auto

# 4. Install Hermes Agent
curl -fsSL https://hermes-agent.nousresearch.com/install.sh | bash

# 5. Configure model
hermes config set model.provider anthropic
hermes config set model.name claude-sonnet-4-5
# Paste your Anthropic API key when prompted
```

### First-time setup

```bash
# Copy profiles to Hermes runtime directory
bash hermes-setup.sh

# Verify offline mode is active
hermes --profile mps-main config get gateway.telegram.token
# Expected: empty string

hermes --profile mps-main config get skills.evolution.enabled
# Expected: true

hermes --profile mps-main config get mcp.servers
# Expected: {}
```

### Verify skills loaded

```bash
hermes --profile mps-main skills list
# Expected: 8 SKILL files listed

hermes --profile mps-main chat
# Test: "what is the income ceiling for CHAS Blue?"
# Expected: $1,800/month household or $650 per capita
```

---

## Verification checklist

Before the first GEPA cycle:

- [ ] `hermes --version` returns a version number
- [ ] `hermes --profile mps-main config get gateway.telegram.token` → empty
- [ ] `hermes --profile mps-main config get mcp.servers` → `{}`
- [ ] `hermes --profile mps-main skills list` → shows 8 SKILL files
- [ ] `skills/auto/` directory exists and is writable
- [ ] `hermes --profile mps-main chat` → policy questions answered correctly
- [ ] `weekly-skill-update.sh` exists in `~/nanoclaw/` and is executable
- [ ] `feedback-log.md` exists in `~/nanoclaw/groups/main/`
- [ ] At least 5 feedback entries in feedback-log.md before first GEPA run

---

## Project structure

```
mps-hermes-agent/
├── profiles/
│   ├── mps-main/
│   │   ├── SOUL.md               ← MP agent identity (offline reference)
│   │   └── config.yaml           ← Offline mode config (no token, no CRM)
│   ├── mps-volunteers/
│   │   ├── SOUL.md               ← Volunteer agent identity (offline reference)
│   │   └── config.yaml           ← Group Telegram mode template
│   └── mps-vetters/
│       ├── SOUL.md               ← Vetter agent identity (offline reference)
│       └── config.yaml           ← No CRM servers
├── skills/
│   ├── SKILL-hdb.md              ← HDB grants, rental, eligibility, Fresh Start 2026
│   ├── SKILL-cpf.md              ← CPF accounts, OW ceiling $8k, withdrawal, MRSS
│   ├── SKILL-msf.md              ← ComCare tiers, Silver Support, SSO
│   ├── SKILL-moh.md              ← CHAS, MediFund, MediShield, CareShield, PGP/MGP
│   ├── SKILL-mom.md              ← Work passes, LTVP, TADM, retrenchment, Workfare
│   ├── SKILL-ica.md              ← PR/citizenship, LTVP+, REP, 7-point appeal strategy
│   ├── SKILL-letter.md           ← MP letter format, tone rules, 8 agency addresses
│   ├── SKILL-feedback.md         ← /feedback command, GEPA capture, evolution workflow
│   └── auto/                     ← GEPA-generated skills (review before applying)
├── mcp-crm-server.py             ← CRM bridge reference (not wired in offline mode)
├── requirements-crm.txt
├── hermes-setup.sh               ← Automated setup script
├── OFFLINE-MODE.md               ← Offline configuration and security boundary reference
├── .env.example
├── .gitignore
└── README.md
```

After setup, Hermes creates runtime files at `~/.hermes/profiles/<name>/` — not stored in this repo.

---

## Important notes

1. **This system never handles constituent data.** No NRIC, no names, no addresses, no case records enter this system. The `weekly-skill-update.sh` PII scan enforces this with an automated check before every export.

2. **Review every GEPA output before applying.** Generated skill files in `skills/auto/` must be read and verified before being merged into nanoClaw's `CLAUDE.md`. Check for fabricated policy thresholds or any text resembling personal data.

3. **Policy accuracy.** Skill files are updated by GEPA based on your corrections. Always verify policy figures with the agency before sending a letter under the MP's name.

4. **GEPA needs volume.** The first meaningful evolution cycle requires at least 5 feedback entries. After 3–4 weekly cycles (15–20 corrections), improvement becomes measurable.

5. **Accumulation over time.** The longer you run the combined system, the better GEPA performs. After 6 months of real MPS sessions, `skills/auto/` will contain 20–40 case-specific patterns that meaningfully improve the agent's reasoning on common case types.

---

## References

- [MPS-AI-Agent-nanoClaw](https://github.com/J-Dheeraj/MPS-AI-Agent-_nanoClaw) — production system
- [INTEGRATION.md](https://github.com/J-Dheeraj/MPS-AI-Agent-_nanoClaw/blob/main/INTEGRATION.md) — combined workflow and security boundary
- [OFFLINE-MODE.md](./OFFLINE-MODE.md) — offline config reference
- [Hermes Agent docs](https://hermes-agent.nousresearch.com/docs)
- [Hermes GitHub](https://github.com/NousResearch/hermes-agent)
- [Anthropic Console](https://console.anthropic.com)
- [HDB](https://www.hdb.gov.sg) · [CPF](https://www.cpf.gov.sg) · [MOM](https://www.mom.gov.sg) · [MOH](https://www.moh.gov.sg) · [MSF](https://www.msf.gov.sg) · [ICA](https://www.ica.gov.sg) · [IRAS](https://www.iras.gov.sg)
- [SupportGoWhere](https://supportgowhere.life.gov.sg)
- [Singapore Budget Archive](https://singaporebudget.gov.sg)

---

## License

MIT
