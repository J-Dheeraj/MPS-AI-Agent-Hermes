# MPS-AI-Agent-Hermes

A self-hosted personal AI agent for Singapore Members of Parliament conducting **Meet-the-People Sessions (MPS)** and constituency casework — built on the **Hermes Agent** platform by Nous Research.

Three independent agent profiles (MP, Volunteers, Vetters), Telegram messaging, MCP CRM bridge, and Hermes's native **GEPA self-improving skills loop**.

---

## Why Hermes

| Feature | NanoClaw | Hermes |
|---|---|---|
| **Self-improving loop** | Manual (weekly task) | Built-in, automatic (GEPA) |
| **Skill evolution** | No | Yes — ICLR 2026 method |
| WhatsApp | Baileys (no API needed) | Meta Cloud API / Twilio |
| Telegram | Yes | Yes — native, streaming |
| Multi-agent profiles | Docker per group | Profiles (separate home dirs) |
| Context files | CLAUDE.md per group | SOUL.md per profile |
| Knowledge | mnemon graph | Built-in memory + SKILL.md |
| MCP servers | Yes | Yes |
| Security | OneCLI vault + Docker | Profile isolation + allowlist |
| Minimum context | Any | 64,000 tokens (enforced) |

The key advantage is **GEPA** (Generalised Experience-driven Policy Adaptation): after each complex MPS case, Hermes automatically writes a skill file summarising what it learned. After 5 cycles, benchmarks show 15–30% task success rate improvement.

---

## What the agent does

| Task | Profile |
|---|---|
| Pre-session briefing — pending cases, policy changes | MP (mps-main) |
| Case history lookup by NRIC | MP + Volunteers |
| Live case triage — agency, scheme, eligibility, urgency | Volunteers (mps-volunteers) |
| Appeal letter drafting — ready to paste into platform | Volunteers |
| Policy fact-checking and letter review | Vetters (mps-vetters) |
| PASS / NEEDS REVISION / FLAG verdict on drafts | Vetters |
| CRM: log cases, attach letters, track agency replies | MP + Volunteers |
| Scheduled policy monitoring (daily, weekly, Budget season) | MP |
| Self-improving skills — learns from each MPS session | All profiles |

---

## Architecture

```
Telegram (3 bots)
  │
  ├── Bot 1 (MP private)       → Hermes profile: mps-main
  │                               SOUL.md + 8 SKILL files
  │                               MCP: crm-bridge (full access)
  │                               GEPA: auto skill evolution
  │
  ├── Bot 2 (volunteer group)  → Hermes profile: mps-volunteers
  │                               SOUL.md + 8 SKILL files
  │                               MCP: crm-bridge (create + lookup)
  │                               Group mode: mention_only
  │
  └── Bot 3 (vetter private)   → Hermes profile: mps-vetters
                                  SOUL.md + 8 SKILL files
                                  MCP: none (policy lookup only)

All three profiles share one SQLite CRM database:
  ~/mps-hermes/crm-data/mps-cases.db

CRM bridge:
  mcp-crm-server.py  (FastMCP, stdio)
  └─ SQLite / Google Sheets / REST API / SharePoint / CSV
```

---

## Profile identities

### mps-main — MP private channel

`profiles/mps-main/SOUL.md` defines the MP's personal agent:

- Pre-session briefing (pending cases + policy changes)
- Case history lookup before each constituent meeting
- Complex case triage and escalation
- Appeal letter drafting + automatic case logging
- Overdue case follow-up digest
- Learns from MP's feedback via `/feedback` command

### mps-volunteers — Volunteer intake team

`profiles/mps-volunteers/SOUL.md` defines the volunteer agent:

- Fast case triage (3–5 lines, speed matters at MPS)
- Complete letter drafts ready to paste into the case platform
- Quick policy questions (income ceilings, scheme names)
- Case logging after letter drafts
- Group Telegram mode: responds only when @mentioned

### mps-vetters — Vetter review team

`profiles/mps-vetters/SOUL.md` defines the vetter agent:

- 6-point letter review: agency name, scheme accuracy, figures, request clarity, promises/speculation, tone, missing info
- PASS / NEEDS REVISION / FLAG verdict with specific corrections
- 2025/2026 policy quick-reference (HDB, CPF, MOH, MSF, MOM, ICA, IRAS)
- No CRM access — vetters do not log cases or see constituent records
- Escalation flags for serious situations with correct hotlines

---

## SKILL files

8 Markdown skill files give all three profiles deep Singapore policy knowledge. Hermes loads them on demand — keeping the base context lean.

| File | Coverage |
|---|---|
| `SKILL-hdb.md` | EHG, PHG, Step-Up grants; new flat ceilings; rental scheme; Fresh Start 2026; letter addressees |
| `SKILL-cpf.md` | Account types; OW ceiling ($8,000/Jan 2026); withdrawal at 55; CPF LIFE; MediSave; MRSS |
| `SKILL-msf.md` | ComCare tiers (Crisis/SMTA/LTA); Silver Support; ComLink+; SSO referral process |
| `SKILL-moh.md` | CHAS Blue/Orange; MediFund; MediShield Life; CareShield Life; ElderShield; Pioneer/Merdeka Generation |
| `SKILL-mom.md` | EP ($5,600/Sep 2025), S Pass ($3,150); LTVP ($2,500 sponsor); TADM; retrenchment; Workfare |
| `SKILL-ica.md` | PR/SC holistic assessment; LTVP/LTVP+; REP; appeal letter guidance |
| `SKILL-letter.md` | Standard MP appeal letter format; tone rules; agency name reference; required fields checklist |
| `SKILL-feedback.md` | Self-improvement feedback capture; `/feedback` command; 6 feedback categories |

After each MPS session, Hermes automatically generates additional skills under `~/.hermes/profiles/<name>/skills/auto/` — named by case type (e.g. `hdb-rental-widow-pattern.md`).

---

## CRM Bridge

`mcp-crm-server.py` connects the agent to your case records via MCP. Five backends supported:

| Backend | `CRM_BACKEND` | Best for |
|---|---|---|
| **SQLite** | `sqlite` | Default — zero infrastructure, works immediately |
| **Google Sheets** | `google_sheets` | Shared spreadsheet for the MP's office team |
| **REST API** | `rest_api` | Existing CRM with a JSON API |
| **SharePoint** | `sharepoint` | Organisations on Microsoft 365 |
| **CSV** | `csv` | Read-only import of legacy records |

### CRM tools available to the agent

| Tool | What it does |
|---|---|
| `lookup_constituent` | Full profile + all cases + letters before an MP meeting |
| `create_case` | Log a new case with issue type, agency, urgency |
| `attach_letter` | Store the full letter text against its case |
| `update_case_status` | Mark case replied / resolved / escalated |
| `get_pending_cases` | List open cases with no reply after N days (default 21) |
| `get_todays_queue` | Tonight's MPS queue sorted by urgency |

### Install

```bash
pip install -r requirements-crm.txt
```

---

## Setup

### Prerequisites

```bash
# 1. Confirm WSL2
wsl.exe --list --verbose   # VERSION must show 2

# 2. Build tools
sudo apt-get update && sudo apt-get install -y python3 python3-pip curl

# 3. Clone into Linux filesystem (not /mnt/c/ — 10x slower)
cd ~
git clone https://github.com/J-Dheeraj/MPS-AI-Agent-Hermes mps-hermes
cd mps-hermes
```

### Automated setup

```bash
bash hermes-setup.sh
```

The script:
1. Installs Hermes Agent
2. Prompts for your Anthropic API key and configures the model
3. Creates all three profiles
4. Copies SOUL.md, config.yaml, and 8 SKILL files to each profile
5. Installs the CRM bridge and Python dependencies
6. Prints next steps

### Manual Telegram configuration

After setup, edit each profile config:

```yaml
# ~/.hermes/profiles/mps-main/config.yaml
gateway:
  telegram:
    token: "YOUR_MAIN_BOT_TOKEN"      # From @BotFather
    allowed_users: ["YOUR_TELEGRAM_ID"]
```

Get Telegram user IDs by messaging `@userinfobot`.

### Start the gateways

```bash
hermes --profile mps-main gateway start --daemon
hermes --profile mps-volunteers gateway start --daemon
hermes --profile mps-vetters gateway start --daemon
```

Check status:

```bash
hermes --profile mps-main gateway status
hermes --profile mps-volunteers gateway status
hermes --profile mps-vetters gateway status
```

---

## Verification checklist

Before the first live MPS session:

- [ ] `hermes --version` returns a version number
- [ ] `hermes --profile mps-main chat` → responds correctly
- [ ] `hermes --profile mps-volunteers chat` → responds correctly
- [ ] `hermes --profile mps-vetters chat` → responds correctly
- [ ] Telegram bot 1 (MP) responds to your message
- [ ] Telegram bot 2 (volunteers) responds when @mentioned in group
- [ ] Telegram bot 3 (vetters) responds
- [ ] `what tools do you have?` → lists CRM tools in mps-main and mps-volunteers
- [ ] `what tools do you have?` → empty list in mps-vetters (no CRM)
- [ ] `what are the CHAS Blue card income thresholds?` → $1,800/month household or $650 per capita
- [ ] `draft an appeal letter to HDB for a widow facing eviction` → complete, formatted letter
- [ ] `hermes --profile mps-main skills list` → shows 8 MPS policy skills
- [ ] `hermes --profile mps-main config get skills.evolution.enabled` → `true`

---

## Self-improvement (GEPA)

GEPA is **on by default**. After each MPS session with 5+ tool calls:

1. Hermes writes a new skill file in `skills/auto/` capturing the pattern
2. Every 7 days, the Curator consolidates and prunes the skill library
3. The GEPA Optimizer reads execution traces and adjusts drafting behaviour

To force a cycle manually:

```bash
hermes --profile mps-main skills evolve --now
hermes --profile mps-main skills curator --run
```

Provide explicit feedback with:

```
/feedback The letter cited the wrong income ceiling for EHG families — it is $9,000 not $8,000.
```

---

## Common usage examples

### During MPS — volunteer intake

```
@mps_volunteers_bot constituent 70F widow, HDB rental Toa Payoh, husband passed away last month, eviction notice
```

Agent responds: triage (HDB Public Rental, widow compassionate case, urgent), complete draft letter ready to paste.

### MP pre-session

```
what cases are overdue?
```

Agent calls `get_pending_cases(21)` and returns a list sorted by agency and days open.

### Vetter check

```
Please check this draft — HDB rental appeal for elderly widow.
Agency: Housing & Development Board.
[draft letter text]
```

Agent responds: PASS / NEEDS REVISION / FLAG with specific issues and corrections.

### MP feedback

```
/feedback Letter used "unfair" — use neutral language instead.
```

Logged for next GEPA evolution cycle.

---

## Project structure

```
mps-hermes/                       ← Clone into ~/mps-hermes in WSL2
├── profiles/
│   ├── mps-main/
│   │   ├── SOUL.md               ← MP agent identity
│   │   └── config.yaml           ← Profile config template (bot token, MCP)
│   ├── mps-volunteers/
│   │   ├── SOUL.md               ← Volunteer agent identity
│   │   └── config.yaml           ← Group Telegram mode, mention_only
│   └── mps-vetters/
│       ├── SOUL.md               ← Vetter agent identity
│       └── config.yaml           ← No CRM servers
├── skills/
│   ├── SKILL-hdb.md              ← HDB grants, rental, eligibility
│   ├── SKILL-cpf.md              ← CPF accounts, OW ceiling, withdrawal
│   ├── SKILL-msf.md              ← ComCare, Silver Support, SSO
│   ├── SKILL-moh.md              ← CHAS, MediFund, MediShield, CareShield
│   ├── SKILL-mom.md              ← Work passes, LTVP, TADM, Workfare
│   ├── SKILL-ica.md              ← PR, citizenship, LTVP appeals
│   ├── SKILL-letter.md           ← MP letter format, tone rules, agency names
│   └── SKILL-feedback.md         ← Self-improvement feedback capture
├── mcp-crm-server.py             ← CRM bridge (5 backends: sqlite, sheets, REST, SP, csv)
├── requirements-crm.txt          ← Python deps for CRM bridge
├── hermes-setup.sh               ← Automated setup script
├── .env.example                  ← CRM environment variables template
├── .gitignore
└── README.md
```

After setup, Hermes creates its own runtime files at `~/.hermes/profiles/<name>/` — these are NOT in this repo.

---

## Important notes

1. **Policy accuracy.** Singapore policies change at Budget (February) and COS (March). The vetter agent flags potentially outdated information, but always verify with the agency before sending under the MP's name.

2. **Constituent confidentiality.** Add only authorised Telegram IDs to each profile's `allowed_users`. The vetter profile has no CRM access by design.

3. **GEPA and sensitive data.** SKILL files generated by GEPA should not contain constituent names or NRICs. The skill system captures patterns, not personal data. Review auto-generated skills periodically.

4. **WhatsApp.** Hermes uses Meta Cloud API or Twilio for WhatsApp — not the Baileys protocol. This requires Meta Business verification (free but takes a few days). Use Telegram for initial setup and testing.

5. **API costs.** Monitor at [console.anthropic.com/usage](https://console.anthropic.com/usage). Three profiles with frequent MPS sessions can accumulate costs. Set a spending limit before going live.

---

## References

- [Hermes Agent docs](https://hermes-agent.nousresearch.com/docs)
- [Hermes GitHub](https://github.com/NousResearch/hermes-agent)
- [GEPA self-evolution](https://github.com/NousResearch/hermes-agent-self-evolution)
- [Anthropic Console](https://console.anthropic.com)
- [HDB](https://www.hdb.gov.sg) · [CPF](https://www.cpf.gov.sg) · [MOM](https://www.mom.gov.sg) · [MOH](https://www.moh.gov.sg) · [MSF](https://www.msf.gov.sg) · [ICA](https://www.ica.gov.sg) · [IRAS](https://www.iras.gov.sg)
- [SupportGoWhere](https://supportgowhere.life.gov.sg)
- [Singapore Budget Archive](https://singaporebudget.gov.sg)

---

## License

MIT
