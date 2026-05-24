# MPS-AI-Agent-Hermes — Offline Skill Engine (GEPA)

A weekly offline skill improvement engine for the [MPS-AI-Agent-nanoClaw](https://github.com/J-Dheeraj/MPS-AI-Agent-_nanoClaw) production system — powered by **Ollama** running fully on-premises. No API key. No cloud calls. No constituent data.

GEPA (Generalised Experience-driven Policy Adaptation, ICLR 2026) reads **vetter-validated, anonymised policy corrections** from the nanoClaw FastAPI server and improves SKILL files weekly.

> **Production system:** [MPS-AI-Agent-nanoClaw](https://github.com/J-Dheeraj/MPS-AI-Agent-_nanoClaw) handles all live volunteer and vetter interactions via a GTK4 native desktop app + FastAPI backend + Ollama. See that repo's [INTEGRATION.md](https://github.com/J-Dheeraj/MPS-AI-Agent-_nanoClaw/blob/main/INTEGRATION.md) for the full combined workflow.

---

## Two-system architecture

```
nanoClaw (production) ─────────────────────────────────────────────────────
  GTK4 client on each volunteer/vetter laptop
  FastAPI server (mps_server) on central machine
  Ollama (llama3.2:3b) — all inference on-premises, no API key
  SQLite + append-only audit log
  NRIC never stored in full (S****567A)
                │
                │  Vetters validate corrections in GTK4 client
                │  Only approved, anonymised corrections leave nanoClaw
                │  via GET /feedback/approved  (LAN call, no internet)
                │  No NRIC. No names. No case IDs.
                ▼
Hermes (this repo) ─────────────────────────────────────────────────────────
  Runs on the same server, Sunday 2am
  Ollama (llama3.2:3b) — same inference, still offline
  GEPA reads /feedback/approved → improves SKILL-*.md files
  Human reviews every generated change before it takes effect
                │
                │  Approved SKILL file changes → committed to this repo
                ▼
nanoClaw loads updated SKILL files at next session
```

**Security boundary:** constituent data never enters this system. Only vetter-validated policy corrections (not case data, not NRIC, not names) flow in via the local API.

---

## What changed from the previous version

| Before | Now |
|--------|-----|
| Anthropic Claude API (sk-ant- key) | **Ollama on-premises** — no API key |
| feedback-log.md exported manually | **GET /feedback/approved** — API call to nanoClaw server |
| Weekly shell script triggers GEPA | **Cron job** Sunday 2am, automatic |
| Profiles reference live Telegram bots | **Offline only** — no live connections |
| Manual PII scan before export | **Server-side enforcement** — vetters validate before approval |

---

## What GEPA does

After each MPS session, volunteers and vetters log corrections in the GTK4 client:

```
Incorrect claim: "EHG ceiling is $9,000"
Correct answer:  "EHG ceiling is $8,000 for families"
Agency: HDB
```

A vetter must approve the correction before it reaches Hermes. Only approved, anonymised entries flow in.

Every Sunday 2am, the GEPA cycle runs automatically:

1. Reads approved corrections from `http://127.0.0.1:8000/feedback/approved`
2. Analyses patterns — does not store raw feedback
3. Generates updated SKILL files in `skills/auto/`
4. Human reviews every generated file — nothing applies automatically
5. Approved improvements are committed to this repo
6. nanoClaw loads updated SKILL files at next session

After 5+ cycles, benchmarks show **15–30% task success rate improvement** on MPS-type cases.

---

## Configuration

### `profiles/mps-volunteers/hermes-config.yaml`

```yaml
profile: mps-volunteers
llm:
  provider: ollama
  base_url: http://localhost:11434
  model: llama3.2:3b
  # Upgrade to 8b for better quality:
  # model: llama3.1:8b

gepa:
  schedule: "0 2 * * 0"    # Sunday 2am
  skill_files:
    - skills/HDB.md
    - skills/CPF.md
    - skills/MSF.md
    - skills/MOH.md
    - skills/MOM.md
    - skills/ICA.md
    - skills/letter-format.md
  feedback_endpoint: http://127.0.0.1:8000/feedback/approved
  feedback_token_env: MPS_HERMES_TOKEN
  data_isolation: strict    # never stores raw feedback
```

Set `MPS_HERMES_TOKEN` in `.env` — a service account JWT from the nanoClaw server with `vetter` role.

---

## SKILL files

8 Markdown reference files. GEPA improves these weekly based on vetter-validated corrections.

| File | Agency | Coverage |
|------|--------|---------|
| `skills/HDB.md` | HDB | EHG/PHG/Step-Up grants, BTO ceilings, rental, Fresh Start 2026 |
| `skills/CPF.md` | CPF | OA/SA/MA/RA, OW ceiling $8,000 (Jan 2026), CPF LIFE, MediSave, MRSS |
| `skills/MSF.md` | MSF | ComCare tiers (Crisis/SMTA/LTA), Silver Support, ComLink+, SSO referral |
| `skills/MOH.md` | MOH | CHAS Blue/Orange, MediFund, MediShield Life, CareShield Life, PGP/MGP |
| `skills/MOM.md` | MOM | EP ($5,600/Sep 2025), S Pass ($3,150), LTVP, TADM, Workfare |
| `skills/ICA.md` | ICA | PR holistic assessment, LTVP/LTVP+, REP, citizenship appeal strategy |
| `skills/letter-format.md` | All | Standard MP appeal letter format, tone rules, agency addresses |

GEPA auto-generates additional skills in `skills/auto/` — review before applying.

---

## Original SKILL files (from v1)

The original Hermes skill files are preserved with full policy content:

| File | Coverage |
|------|---------|
| `SKILL-hdb.md` | EHG, PHG, Step-Up grants; new flat ceilings; rental scheme; Fresh Start 2026 |
| `SKILL-cpf.md` | Account types; OW ceiling ($8,000/Jan 2026); withdrawal at 55; CPF LIFE; MRSS |
| `SKILL-msf.md` | ComCare tiers; Silver Support; ComLink+; SSO referral process |
| `SKILL-moh.md` | CHAS Blue/Orange; MediFund; MediShield Life; CareShield Life; PGP/MGP |
| `SKILL-mom.md` | EP ($5,600), S Pass ($3,150); LTVP; TADM; retrenchment; Workfare |
| `SKILL-ica.md` | PR/SC holistic assessment; LTVP/LTVP+; REP; 7-point appeal strategy |
| `SKILL-letter.md` | Standard MP appeal letter format; 8 agency addresses |
| `SKILL-feedback.md` | Feedback workflow; GEPA capture; evolution schedule |

---

## Profile identities

### mps-main — MP private channel
Pre-session briefing, case history lookup, complex triage, appeal letter drafting, overdue follow-up, GEPA feedback loop.

### mps-volunteers — Volunteer intake team
Fast case triage, complete letter drafts, policy questions, case logging.

### mps-vetters — Vetter review team
6-point letter review, PASS / NEEDS REVISION / FLAG verdicts, 2025/2026 policy quick-reference.

All profiles operate in **offline mode** — no live channel connections. nanoClaw handles all constituent-facing interactions.

---

## Setup

### Prerequisites

```bash
# Python 3 and pip
sudo apt-get update && sudo apt-get install -y python3 python3-pip curl

# Ollama (same instance as nanoClaw — no need to install twice)
# If not already installed:
curl -fsSL https://ollama.com/install.sh | sh
ollama pull llama3.2:3b
```

### Clone and configure

```bash
cd ~
git clone https://github.com/J-Dheeraj/MPS-AI-Agent-Hermes.git mps-hermes-agent
cd mps-hermes-agent

mkdir -p skills/auto

# Set your Hermes service account token
cp .env.example .env
# Edit .env:
#   MPS_HERMES_TOKEN=<JWT from nanoClaw /auth/login for a vetter service account>
#   OLLAMA_URL=http://localhost:11434
```

### Create the Hermes service account in nanoClaw

```bash
# On the nanoClaw server:
curl -X POST http://127.0.0.1:8000/auth/register \
  -H "Authorization: Bearer <admin_token>" \
  -H "Content-Type: application/json" \
  -d '{"username":"hermes-gepa","password":"STRONG_PW","role":"vetter","full_name":"Hermes GEPA"}'

# Then login to get the token:
curl -X POST http://127.0.0.1:8000/auth/login \
  -d 'username=hermes-gepa&password=STRONG_PW'
# Paste the access_token into .env as MPS_HERMES_TOKEN
```

### Verify

```bash
# Check Ollama is running
curl http://localhost:11434/api/tags | grep llama

# Check feedback endpoint is reachable
curl http://127.0.0.1:8000/feedback/approved \
  -H "Authorization: Bearer $MPS_HERMES_TOKEN"
# Expected: [] or list of approved corrections

# Check skills are present
ls skills/
# Expected: HDB.md  CPF.md  MSF.md  MOH.md  MOM.md  ICA.md  letter-format.md
```

---

## Weekly operation

The GEPA cycle runs automatically on Sunday 2am via the cron schedule in `hermes-config.yaml`.

To trigger manually:

```bash
# Run GEPA cycle now
python3 -m hermes_gepa --profile mps-volunteers --run-now

# Or, if using the Hermes CLI:
hermes --profile mps-volunteers skills evolve --now
```

After the cycle:
1. Check `skills/auto/` for generated improvements
2. Review each file — verify no fabricated policy numbers
3. If approved, move to `skills/` and commit to this repo
4. nanoClaw loads updated SKILL files at next session

### GEPA needs volume

| Feedback count | Expected improvement |
|---------------|---------------------|
| 1–4 entries | No meaningful change |
| 5–10 entries | First evolution cycle viable |
| 15–20 entries | Measurable improvement in letter quality |
| 50+ (over 3–4 months) | Significant skill specialisation |

---

## CRM Bridge

`mcp-crm-server.py` is included for reference — the same server used by nanoClaw. In Hermes, the CRM bridge is **not wired** to any profile. Constituent case data remains exclusively in nanoClaw.

---

## Security

| Control | How enforced |
|---------|-------------|
| No constituent data in Hermes | Vetter validates in nanoClaw before approval; API returns anonymised corrections only |
| No cloud AI | Ollama runs on-premises — same instance as nanoClaw |
| No API key | llama3.2:3b via Ollama — no Anthropic key required |
| Feedback isolation | `data_isolation: strict` — GEPA extracts policy patterns, never stores raw feedback |
| Human review | Every generated skill file must be manually approved before applying |
| No live connections | All profiles set to offline mode — no Telegram/WhatsApp tokens |

---

## Project structure

```
mps-hermes-agent/
├── profiles/
│   ├── mps-main/
│   │   ├── SOUL.md               ← MP agent identity (offline reference)
│   │   └── config.yaml           ← Offline mode config
│   ├── mps-volunteers/
│   │   ├── SOUL.md               ← Volunteer agent identity
│   │   ├── config.yaml           ← Offline mode config
│   │   ├── hermes-config.yaml    ← GEPA config (Ollama, cron, feedback endpoint) ← NEW
│   │   └── skills/               ← SKILL file stubs (improved weekly by GEPA) ← NEW
│   │       ├── HDB.md
│   │       ├── CPF.md
│   │       ├── MSF.md
│   │       ├── MOH.md
│   │       ├── MOM.md
│   │       ├── ICA.md
│   │       └── letter-format.md
│   └── mps-vetters/
│       ├── SOUL.md               ← Vetter agent identity
│       └── config.yaml           ← No CRM servers
├── skills/
│   ├── SKILL-hdb.md              ← Full HDB policy reference (v1)
│   ├── SKILL-cpf.md              ← Full CPF policy reference (v1)
│   ├── SKILL-msf.md              ← Full MSF / ComCare reference (v1)
│   ├── SKILL-moh.md              ← Full MOH / CHAS reference (v1)
│   ├── SKILL-mom.md              ← Full MOM / work passes reference (v1)
│   ├── SKILL-ica.md              ← Full ICA / PR / citizenship reference (v1)
│   ├── SKILL-letter.md           ← MP letter format, tone rules, addresses (v1)
│   ├── SKILL-feedback.md         ← Feedback workflow, GEPA evolution (v1)
│   └── auto/                     ← GEPA-generated improvements (review before applying)
├── mcp-crm-server.py             ← CRM bridge reference (not wired in offline mode)
├── requirements-crm.txt
├── hermes-setup.sh               ← Setup script
├── OFFLINE-MODE.md               ← Offline configuration reference
├── .env.example                  ← Template (copy to .env, add MPS_HERMES_TOKEN)
├── .gitignore
└── README.md
```

---

## Important notes

1. **This system never handles constituent data.** Only vetter-approved, anonymised policy corrections flow in. No NRIC, no names, no case IDs.

2. **Review every GEPA output before applying.** Generated skill files in `skills/auto/` must be read and verified before committing. Check for fabricated policy thresholds.

3. **Policy accuracy.** Skill files are improved by GEPA based on MPS session corrections. Always verify policy figures with the official agency source before sending a letter under the MP's name.

4. **GEPA needs volume.** First meaningful improvement requires at least 5 approved feedback entries. After 3–4 weekly cycles, improvement becomes measurable.

5. **Ollama model choice.** `llama3.2:3b` runs on any modern laptop. `llama3.1:8b` gives better letter quality but needs 8GB+ RAM. Both are fully offline.

---

## References

- [MPS-AI-Agent-nanoClaw](https://github.com/J-Dheeraj/MPS-AI-Agent-_nanoClaw) — production GTK4 + FastAPI + Ollama system
- [INTEGRATION.md](https://github.com/J-Dheeraj/MPS-AI-Agent-_nanoClaw/blob/main/INTEGRATION.md) — combined workflow and security boundary
- [OFFLINE-MODE.md](./OFFLINE-MODE.md) — offline configuration reference
- [Ollama](https://ollama.com) — local LLM inference
- [HDB](https://www.hdb.gov.sg) · [CPF](https://www.cpf.gov.sg) · [MOM](https://www.mom.gov.sg) · [MOH](https://www.moh.gov.sg) · [MSF](https://www.msf.gov.sg) · [ICA](https://www.ica.gov.sg)
- [SupportGoWhere](https://supportgowhere.life.gov.sg)

---

## License

MIT
