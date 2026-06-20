# MPS-AI-Agent-Hermes — GEPA Skill Engine + Hermes Review App

> **Architecture reconciliation (2026-06-20).** The production policy mechanism is **deterministic, Ed25519-signed JSON policy rules** loaded by the server's `policy_store` from `POLICY_DIR` (manifest + per-rule JSON, validity/supersession/relevance ranking). The legacy "GEPA skill engine" framing and "Markdown SKILL files injected into the prompt" descriptions below are **superseded**: no Markdown skill is injected into letter generation, and proposal generation is deterministic (no LLM converts corrections into policy). "GEPA" persists only as a product name for the deterministic proposal -> human review -> signed promotion pipeline.

Hermes is the **offline policy-change governance subsystem** for the nanoClaw MPS AI agent.

> **Production hardening update - 10 June 2026:** The supported flow uses deterministic, source-backed JSON proposals, named human review, proposal SHA-256 binding, and manifested policy promotion. Telegram, conversational memory, direct active-policy mutation, and unapproved CRM writes are outside the production boundary. See [`PRODUCTION_BOUNDARY.md`](PRODUCTION_BOUNDARY.md).

It runs **once a week** (Sunday 2am) on the same server, reads vetted policy corrections collected during MPS nights, and updates the SKILL files that guide nanoClaw's letter generation. A **Tauri v2 desktop app** (`hermes-review-app`) provides a human review step — a reviewer sees before/after diffs for every proposed change and approves or rejects each one.

No constituent data ever enters Hermes. Only anonymised, vetter-validated policy corrections (agency name, incorrect claim, correct answer) are used.

> **Parent system:** [MPS-AI-Agent-nanoClaw](https://github.com/J-Dheeraj/MPS-AI-Agent-_nanoClaw) — the MPS session tool that collects the feedback Hermes consumes.

---

## Table of Contents

1. [What Hermes does — overview](#what-hermes-does--overview)
2. [GEPA cycle — step by step](#gepa-cycle--step-by-step)
3. [Architecture](#architecture)
4. [SKILL files explained](#skill-files-explained)
5. [hermes-config.yaml explained](#hermes-configyaml-explained)
6. [hermes-review-app — Tauri desktop tool](#hermes-review-app--tauri-desktop-tool)
7. [Installation and setup](#installation-and-setup)
   - [Server setup](#1-server-setup-runs-on-same-machine-as-mps_server)
   - [Hermes Review App setup](#2-hermes-review-app-setup)
   - [Running in development mode](#3-running-in-development-mode)
   - [Building for production](#4-building-for-production)
8. [Weekly operation](#weekly-operation)
9. [Security](#security)
10. [Project structure](#project-structure)
11. [Troubleshooting](#troubleshooting)

---

## What Hermes does — overview

During MPS nights, volunteers and vetters notice policy errors in the AI's drafts — wrong CPF withdrawal age, outdated HDB grant amounts, incorrect MOM eligibility criteria. They log these corrections in the **Feedback** tab of the Tauri client. Vetters validate each correction before it is accepted.

Hermes reads these corrections once a week and does three things:

1. **Analyses** each correction using Ollama (`llama3.1:8b` for better reasoning at this step) to understand what is wrong in the current SKILL file and what the correct version should say.

2. **Proposes edits** to the relevant SKILL files — these go into a `skills/auto/` staging folder, one `.md` patch file per change.

3. **Presents diffs** to a human reviewer via `hermes-review-app`. The reviewer sees the old text and the proposed new text side by side and clicks Approve or Reject for each change.

Only approved changes are written back to the active SKILL files. nanoClaw loads the updated SKILL files at the next MPS session.

**The key principle:** Hermes improves the system from real-world signal (what was wrong at the last MPS session) but a human always has the final say. Nothing is auto-merged without review.

---

## GEPA cycle — step by step

GEPA = Generalised Experience-driven Policy Adaptation.

```
COLLECTION (during MPS night, in nanoClaw)
------------------------------------------
1. Volunteer notices the draft says "CPF withdrawal age is 55"
   but the correct age is 65 for the ordinary account.
   Volunteer clicks "Log Correction" in the Feedback tab.
   Fills in:
     Agency:            CPF
     Incorrect claim:   "CPF withdrawal age is 55"
     Correct answer:    "CPF Ordinary Account withdrawal age is 65; full withdrawal at 55 only for retirement sum shortfalls under specific conditions"

2. Vetter sees this in the validation queue.
   Vetter confirms the correction is accurate.
   Clicks "Approve".
   Status changes to "approved".
   No case ID, no resident data, no NRIC — fully anonymised.

EXTRACTION (Sunday 2am, automated)
------------------------------------
3. Hermes scheduler fires (cron: 0 2 * * 0).

4. Hermes calls GET /feedback/approved on the nanoClaw server.
   Gets back the list of approved corrections since the last run.
   Marks the last-processed timestamp to avoid reprocessing.

5. For each correction, Hermes:
   a. Determines which SKILL file is affected (agency -> file mapping).
   b. Reads the current SKILL file content.
   c. Calls Ollama (llama3.1:8b or llama3.2:3b) with a prompt:
        "The current skill file says: [relevant excerpt].
         The correction says this is wrong: [incorrect_claim].
         The correct information is: [correct_answer].
         Generate a minimal edit to fix only the incorrect information.
         Output: the old paragraph, then the new paragraph."
   d. Saves the proposed change as a patch file in skills/auto/:
        skills/auto/2026-06-08_cpf_withdrawal_age.md

REVIEW (human reviewer, same day or next day)
-----------------------------------------------
6. Reviewer opens hermes-review-app (Tauri desktop app).
   Clicks "Open Skills Folder" and selects skills/auto/.

7. App shows the pending queue — one row per proposed change.
   Each row shows: agency, date, a summary of what changed.

8. Reviewer clicks a row to open the Diff view.
   Left panel: old text (red highlights on removed content).
   Right panel: new text (green highlights on added content).

9. Reviewer clicks:
   - "Approve" -> change is moved from skills/auto/ to skills/ (overwrites active file)
   - "Reject"  -> patch file is deleted, change is discarded
   - "Edit"    -> reviewer edits the proposed text before approving

10. After all reviews:
    - Approved changes are active in skills/ immediately
    - Rejected changes are gone
    - skills/auto/ is now empty

AT NEXT MPS SESSION
--------------------
11. nanoClaw reads the updated skills/ files at startup.
    The letter generation system prompt now includes the corrected policy information.
    The same mistake will not be made again.
```

---

## Architecture

```
+-- nanoClaw server (mps_server) ----------------+
|   GET /feedback/approved                        |
|   Returns approved corrections since last run   |
+------------------------------------------------+
         |
         | (Sunday 2am, HTTP call on localhost)
         v
+-- Hermes engine (Python) ----------------------+
|   hermes.py                                     |
|   Reads corrections                             |
|   Identifies affected SKILL files              |
|   Calls Ollama to generate minimal edits       |
|   Writes patch files to skills/auto/           |
+------------------------------------------------+
         |
         | skills/auto/*.md
         v
+-- hermes-review-app (Tauri v2) ----------------+
|   Reviewer opens skills/auto/                   |
|   Sees list of pending changes                  |
|   Opens each: diff view (before / after)        |
|   Clicks Approve or Reject                      |
|   Approved: moves patch to skills/ (active)     |
|   Rejected: deletes patch file                  |
+------------------------------------------------+
         |
         | skills/*.md  (updated active files)
         v
+-- nanoClaw (next session) ---------------------+
|   Loads updated SKILL files into system prompt  |
|   Letter generation now uses correct policy     |
+------------------------------------------------+
```

---

## SKILL files explained

**Legacy mechanism (superseded).** SKILL files were plain Markdown documents in `skills/`, one per domain. In the supported production path they are **not** injected into letter generation: the server loads deterministic Ed25519-signed JSON policy rules via `policy_store` (`POLICY_DIR`/manifest). The review/promotion tooling now emits and signs JSON policy rules, not Markdown prompt fragments.

### File naming

```
skills/
  HDB.md               # HDB grants, eligibility, flat types, application process
  CPF.md               # CPF schemes, withdrawal rules, accounts, Silver Support
  MSF.md               # ComCare, FSC, CHAS, SSO schemes
  MOH.md               # MediFund, MedishieldLife, CHAS eligibility, MOH clinics
  MOM.md               # Employment pass, work permit, MOM appeals, levy waiver
  ICA.md               # PR/citizenship applications, appeals, travel docs
  letter-format.md     # 10-part letter structure, tone rules, MP signature block
  auto/                # Staging folder — proposed changes waiting for review
    2026-06-08_cpf_withdrawal_age.md
    2026-06-01_hdb_proximity_grant_quantum.md
```

### SKILL file structure (example: CPF.md)

```markdown
# CPF SKILL — nanoClaw MPS Agent

## Scope
This file covers CPF-related appeals and enquiries at MPS.
Use this when: case.agency == "CPF"

## Key schemes and eligibility

### CPF Ordinary Account (OA)
- Members can withdraw OA savings at age 55 to meet the Basic Retirement Sum (BRS)
- Withdrawal age: 55 (for amounts above the BRS/FRS/ERS threshold)
- Members who cannot meet the BRS may still withdraw with CPF Board approval

### CPF Retirement Sum (as of 2026)
- Basic Retirement Sum (BRS): $102,900
- Full Retirement Sum (FRS): $205,800 (2x BRS)
- Enhanced Retirement Sum (ERS): $308,700 (3x BRS)
- These figures increase annually — always verify at cpf.gov.sg/retirement-sum

### Silver Support Scheme
- Eligibility: Singapore Citizens, age 65+, lower quarter of CPF contributions
- Quarterly payouts: $600-$1,200 depending on housing type
- Application: automatic — no application needed for eligible citizens

## Appeals guidance

### When to write a CPF appeal letter
- Member disagrees with CPF Board's computation
- Member faces hardship due to inability to meet minimum sum
- Member requests withdrawal of CPF savings under hardship provision

### Key grounds for appeal
1. Financial hardship (medical bills, retrenchment, family circumstances)
2. Disability or reduced work capacity
3. Terminal illness
4. Voluntary contribution disputes

### Tone notes
- CPF Board responds to factual, specific appeals
- Include: NRIC (masked), CPF member number (if known), specific scheme and amount in dispute
- Avoid: emotional language, vague requests

## Common mistakes to avoid
- Do not cite outdated retirement sum figures — these change every year
- Do not promise any outcome — the letter requests consideration, not a guarantee
- Do not include the resident's full NRIC — use masked format only
```

### What Hermes changes in SKILL files

Hermes makes **minimal, targeted edits** — it does not rewrite the whole file. A typical change:

```diff
 ### CPF Retirement Sum (as of 2026)
-  - Basic Retirement Sum (BRS): $99,400
+  - Basic Retirement Sum (BRS): $102,900
-  - Full Retirement Sum (FRS): $198,800 (2x BRS)
+  - Full Retirement Sum (FRS): $205,800 (2x BRS)
```

The reviewer sees exactly this diff in the `hermes-review-app` diff view.

---

## `hermes-config.yaml` explained

Located at `groups/mps-volunteers/hermes-config.yaml`:

```yaml
# hermes-config.yaml
# Hermes GEPA configuration for the nanoClaw MPS agent

version: 1

# Where to find the nanoClaw API
nanoclaw:
  base_url: "http://127.0.0.1:8000"
  # Token is fetched at runtime using service account credentials
  # Credentials stored in ~/.config/hermes/service-account.json
  # Never hardcode credentials here

# SKILL files
skills:
  active_dir: "skills/"           # Active skill files loaded by nanoClaw
  staging_dir: "skills/auto/"     # Proposed changes waiting for review

# Agency -> SKILL file mapping
agency_skill_map:
  HDB: "skills/HDB.md"
  CPF: "skills/CPF.md"
  MSF: "skills/MSF.md"
  MOH: "skills/MOH.md"
  MOM: "skills/MOM.md"
  ICA: "skills/ICA.md"
  GENERAL: "skills/letter-format.md"

# Ollama configuration
ollama:
  base_url: "http://127.0.0.1:11434"
  model: "llama3.1:8b"            # Better reasoning for GEPA analysis
  # llama3.2:3b is acceptable if the server is memory-constrained
  timeout_seconds: 120

# GEPA schedule
schedule:
  cron: "0 2 * * 0"              # Every Sunday at 2am
  timezone: "Asia/Singapore"

# Safety controls
limits:
  max_corrections_per_run: 50    # Ignore runs with more corrections (likely a bug)
  max_skill_file_change_pct: 20  # Reject if Hermes tries to change >20% of a file
  require_human_review: true     # NEVER auto-merge — always go through hermes-review-app

# Logging
logging:
  log_file: "logs/hermes.log"
  level: "INFO"
```

**The `require_human_review: true` flag is non-negotiable.** Even if Hermes generates a perfect correction, it goes through `hermes-review-app` before being written to the active SKILL files. There is no auto-merge mode.

---

## `hermes-review-app/` — Tauri desktop tool

A Tauri v2 + Vite + vanilla JavaScript app for reviewing proposed SKILL file changes. Built to be fast and simple — it does one job: show diffs, get a human decision, apply or discard.

### How it works

```
+-----------------------------------------------------------+
|  hermes-review-app window                                 |
|                                                           |
|  [Open Skills Folder]   skills/auto/ (3 pending)         |
|                                                           |
|  Pending changes:                                         |
|  +--------------------------------------------------+    |
|  | CPF.md   | 2026-06-08 | CPF withdrawal age      | [>]|  <- click to review
|  | HDB.md   | 2026-06-01 | Proximity grant quantum  | [>]|
|  | MSF.md   | 2026-05-25 | CHAS eligibility income  | [>]|
|  +--------------------------------------------------+    |
|                                                           |
|  +--------------------------+  +------------------------+ |
|  |  BEFORE (current file)   |  |  AFTER (proposed)      | |
|  |                          |  |                        | |
|  |  BRS: $99,400            |  |  BRS: $102,900         | |  <- diff view
|  |  FRS: $198,800           |  |  FRS: $205,800         | |
|  |                          |  |                        | |
|  +--------------------------+  +------------------------+ |
|                                                           |
|  [Approve]  [Edit]  [Reject]                             |
|                                                           |
+-----------------------------------------------------------+
```

### Source files

**`src/main.js`** — App entry point

Initialises the app, loads the last-used folder from the Rust store, and renders the main layout (folder selector + change list).

**`src/views/reviewList.js`** — Pending changes list

Reads the contents of the selected `skills/auto/` folder. Each `.md` patch file is parsed to extract:
- Which SKILL file it modifies (from the patch file header)
- The date of the correction
- A one-line summary of the change

Renders a sorted table. Clicking a row opens `diffView.js`.

**`src/views/diffView.js`** — Side-by-side diff view

The core of the app. Given a patch file, it:
1. Reads the current active SKILL file content (from `skills/`)
2. Reads the proposed new content (from the patch file)
3. Renders both side by side with inline character-level diff highlighting:
   - Removed text in red background
   - Added text in green background
4. Shows the full file context around the changed section

Three actions:
- **Approve:** Overwrites the active SKILL file with the proposed content. Deletes the patch file from `skills/auto/`.
- **Edit:** Makes the proposed text editable in-place. Reviewer can fix wording before approving.
- **Reject:** Deletes the patch file. The active SKILL file is unchanged.

**`src/state/store.js`** — App state

Same pub/sub pattern as the nanoClaw client. Tracks: selected folder path, list of pending patches, currently selected patch, review decisions.

#### `src-tauri/src/main.rs` — Rust backend

Tauri v2 commands for filesystem access:
- `read_skill_files(folder_path)` — reads the `skills/auto/` directory
- `read_file_content(file_path)` — reads a specific file
- `write_file_content(file_path, content)` — writes a file (for Approve)
- `delete_file(file_path)` — deletes a patch file (for Reject)
- `move_file(from, to)` — moves an approved patch to the active skills folder

#### `src-tauri/capabilities/default.json`

```json
{
  "identifier": "default",
  "description": "Default capabilities for Hermes review app",
  "windows": ["main"],
  "permissions": [
    "core:default",
    "fs:default",
    "fs:allow-read-text-file",
    "fs:allow-write-text-file",
    "fs:allow-read-dir",
    "dialog:default",
    "dialog:allow-open"
  ]
}
```

No network permissions — `hermes-review-app` only reads and writes local files. It cannot make HTTP calls at all.

---

## Installation and setup

### Prerequisites

- Same server as nanoClaw, or any Linux/Windows/macOS machine that can reach the nanoClaw server
- Python 3.10+ (for the Hermes engine)
- Ollama running locally with `llama3.1:8b` pulled
- Node.js 22 + Rust (for building the review app)

### 1. Server setup (runs on same machine as mps_server)

```bash
# Clone the repo
cd ~
git clone https://github.com/J-Dheeraj/MPS-AI-Agent-Hermes.git hermes
cd hermes

# Install Python dependencies
pip3 install -r requirements.txt --user

# Create service account credentials for Hermes to call the nanoClaw API
mkdir -p ~/.config/hermes
cat > ~/.config/hermes/service-account.json << 'EOF'
{
  "username": "hermes-service",
  "password": "STRONG_SERVICE_ACCOUNT_PASSWORD"
}
EOF
chmod 600 ~/.config/hermes/service-account.json

# Register the service account in nanoClaw
# (Run this on the machine where mps_server is running)
TOKEN=$(curl -s -X POST http://127.0.0.1:8000/auth/login \
  -d 'username=admin&password=YOUR_ADMIN_PASSWORD' \
  | python3 -c "import sys,json; print(json.load(sys.stdin)['access_token'])")

curl -X POST http://127.0.0.1:8000/auth/register \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"username":"hermes-service","password":"STRONG_SERVICE_ACCOUNT_PASSWORD","role":"vetter","full_name":"Hermes GEPA Service"}'

# Verify the config file
cat groups/mps-volunteers/hermes-config.yaml
# Check that base_url and ollama settings are correct for your machine

# Ensure Ollama has the model Hermes needs
ollama pull llama3.1:8b
# If memory is tight, llama3.2:3b works too — edit hermes-config.yaml to match

# Run Hermes manually once to test
python3 hermes.py --run-once
# Expected: "Fetched N corrections", "Generated M skill patches", "Written to skills/auto/"

# Set up the cron job (every Sunday at 2am Singapore time)
crontab -e
# Add this line:
# 0 2 * * 0 cd ~/hermes && python3 hermes.py >> logs/hermes.log 2>&1

# Verify the cron is registered
crontab -l
```

### 2. Hermes Review App setup

The review app is used by the human reviewer (typically the vetter lead or the MP's staff manager). It can run on any machine that has access to the `hermes/skills/` folder — either the server itself, or a laptop with the folder mounted via NFS/SMB.

#### Option A: Use a pre-built binary

Download the latest binary from the GitHub Releases page and run it directly.

#### Option B: Build from source

```bash
# Install Rust
curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs | sh
source ~/.cargo/env

# Install Node.js 22 via nvm
curl -o- https://raw.githubusercontent.com/nvm-sh/nvm/v0.40.1/install.sh | bash
source ~/.nvm/nvm.sh
nvm install 22
nvm use 22

# Install Tauri system dependencies (Ubuntu 22.04)
sudo apt-get update
sudo apt-get install -y \
  libwebkit2gtk-4.1-dev libssl-dev libayatana-appindicator3-dev \
  librsvg2-dev libgtk-3-dev build-essential \
  gstreamer1.0-plugins-good libgstreamer-plugins-good1.0-0

# Install npm dependencies
cd hermes/hermes-review-app
npm install

# Build production binary
npm run tauri build
# Output: src-tauri/target/release/bundle/
```

---

### 3. Running in development mode

```bash
cd hermes/hermes-review-app

source ~/.cargo/env
fuser -k 1420/tcp 2>/dev/null

npm run tauri dev
```

The Tauri window opens. Click **Open Skills Folder** and navigate to `hermes/skills/auto/`.

---

### 4. Building for production

```bash
cd hermes/hermes-review-app
npm run tauri build

# Linux outputs:
#   src-tauri/target/release/hermes-review
#   src-tauri/target/release/bundle/deb/hermes-review_0.1.0_amd64.deb
```

---

## Weekly operation

This is the reviewer's checklist for every Monday morning (after Hermes runs Sunday 2am):

```bash
# 1. Check that Hermes ran
tail -50 ~/hermes/logs/hermes.log
# Expected last lines:
#   [INFO] Fetched 12 approved corrections
#   [INFO] Generated 5 skill patches
#   [INFO] Run complete

# 2. Check what patches were generated
ls ~/hermes/skills/auto/
# Example output:
#   2026-06-08_cpf_brs_amount.md
#   2026-06-08_hdb_proximity_grant_quantum.md
#   2026-06-01_msf_comcare_income_ceiling.md

# 3. Open the review app
./hermes-review           # production binary
# OR
cd ~/hermes/hermes-review-app && npm run tauri dev

# 4. Click "Open Skills Folder" -> select ~/hermes/skills/auto/

# 5. For each pending change:
#    a. Read the diff carefully
#    b. Verify the correct_answer against the official agency website
#    c. Click Approve (or Reject if the correction looks wrong)
#    d. If the wording is right but awkward, click Edit, fix the text, then Approve

# 6. After all reviews, skills/auto/ should be empty
ls ~/hermes/skills/auto/
# Expected: empty

# 7. The updated skill files are now active in skills/
# nanoClaw loads these at the next session automatically
```

---

## Security

| Control | Implementation |
|---------|---------------|
| **No constituent data** | Hermes only receives anonymised corrections (agency + incorrect claim + correct answer). No NRIC, no names, no case content ever enters Hermes. |
| **Ollama only** | All LLM inference via local Ollama. No Anthropic API key. No cloud calls. |
| **Service account scoped** | Hermes authenticates to nanoClaw with a dedicated service account that has `vetter` role. It can only read approved feedback — it cannot read cases, letters, or resident records. |
| **Human review required** | `require_human_review: true` in config. No auto-merge. All changes go through `hermes-review-app` before being applied. |
| **File-system only** | `hermes-review-app` has no network permissions (no `http:allow-fetch` in capabilities). It only reads and writes local files. |
| **20% change limit** | Hermes rejects any proposed change that modifies more than 20% of a SKILL file. Protects against a runaway LLM overwriting the whole file. |
| **Max corrections per run** | Hermes ignores runs with more than 50 corrections (likely a data error). |
| **Service account credentials outside project** | `~/.config/hermes/service-account.json` is outside the repo, mode `600`. |
| **Log everything** | All Hermes actions logged to `logs/hermes.log`. |

---

## Project structure

```
hermes/
|
+-- hermes.py                          <- Main GEPA engine
|   Fetches corrections from nanoClaw
|   Identifies affected SKILL files
|   Calls Ollama to generate patch content
|   Writes patches to skills/auto/
|
+-- requirements.txt                   <- Python dependencies
|
+-- groups/
|   +-- mps-volunteers/
|       +-- hermes-config.yaml         # All Hermes configuration
|       +-- skills/
|           +-- HDB.md                 # Active: HDB policy knowledge
|           +-- CPF.md                 # Active: CPF policy knowledge
|           +-- MSF.md                 # Active: MSF/ComCare knowledge
|           +-- MOH.md                 # Active: MOH/MediFund knowledge
|           +-- MOM.md                 # Active: MOM/employment knowledge
|           +-- ICA.md                 # Active: ICA/residency knowledge
|           +-- letter-format.md       # Active: 10-part letter structure + tone
|           +-- auto/                  # STAGING: proposed patches waiting for review
|               +-- 2026-06-08_cpf_brs_amount.md
|               +-- ...
|
+-- hermes-review-app/                 <- Tauri v2 review app
|   +-- index.html
|   +-- package.json
|   +-- vite.config.js
|   +-- src/
|   |   +-- main.js                    # App entry
|   |   +-- style.css
|   |   +-- state/
|   |   |   +-- store.js               # Pub/sub state
|   |   +-- views/
|   |       +-- reviewList.js          # List of pending patches
|   |       +-- diffView.js            # Side-by-side diff + approve/reject
|   +-- src-tauri/
|       +-- tauri.conf.json
|       +-- Cargo.toml
|       +-- build.rs
|       +-- capabilities/
|       |   +-- default.json           # fs + dialog only — no network
|       +-- icons/
|       +-- src/
|           +-- main.rs                # Rust: fs commands + plugin registration
|
+-- logs/
|   +-- hermes.log                     <- Append-only Hermes run log
|
+-- docs/
    +-- gepa-design.md                 <- GEPA algorithm design doc
```

---

## Troubleshooting

**Hermes says "0 corrections fetched" every week**

Vetters may not be approving corrections in the nanoClaw Feedback tab. Check:
1. Are corrections being logged? Open the Feedback tab in the Tauri client.
2. Are corrections being validated? Vetters need to click Approve in the validation queue.
3. Is the service account working?
   ```bash
   python3 hermes.py --test-connection
   # Expected: "Connected to nanoClaw at 127.0.0.1:8000 — OK"
   ```

**Hermes fails with "Connection refused"**

The nanoClaw mps_server is not running.
```bash
curl http://127.0.0.1:8000/health
# If this fails, start the server first:
bash ~/nanoclaw/start-server.sh
```

**`hermes-review-app` shows blank patch list**

The `skills/auto/` folder is empty — either Hermes hasn't run yet this week, or all patches were already reviewed.
```bash
ls ~/hermes/skills/auto/
# If empty, check when Hermes last ran:
tail -20 ~/hermes/logs/hermes.log
```

**A patch looks wrong — LLM generated incorrect content**

Click **Reject** in `hermes-review-app`. The active SKILL file is unchanged. If the correction from the feedback was valid but the LLM misapplied it, you can manually edit the SKILL file directly:
```bash
nano ~/hermes/groups/mps-volunteers/skills/CPF.md
```

**`cargo: command not found` when building the review app**
```bash
source ~/.cargo/env
echo 'source ~/.cargo/env' >> ~/.bashrc
```

**`libwebkit2gtk-4.1-dev: not found`**
```bash
sudo apt-get update
sudo apt-get install -y gstreamer1.0-plugins-good libgstreamer-plugins-good1.0-0
sudo dpkg --configure -a
sudo apt-get install -y libwebkit2gtk-4.1-dev
```

---

## Important notes

1. **GEPA improves over time.** After 6 months of consistent feedback logging and weekly review, the SKILL files become very accurate for the specific constituency's most common case types.

2. **Verify corrections before approving.** When a correction appears in `hermes-review-app`, always verify the proposed content against the official agency website (cpf.gov.sg, hdb.gov.sg, etc.) before clicking Approve. Policy figures change at Budget and COS — Hermes learns from the vetters, who are human and can also make mistakes.

3. **letter-format.md is the most stable file.** The 10-part letter structure rarely changes. Be conservative about approving changes to this file.

4. **Hermes does not learn from rejected feedback.** If a correction is rejected in the nanoClaw validation queue (by a vetter), it never reaches Hermes. If a patch is rejected in `hermes-review-app`, the correction is noted in the log but not reprocessed.

5. **Back up skill files before a Hermes run.** Hermes backs them up automatically to `skills/backup/YYYY-MM-DD/`, but it is good practice to verify backups exist.

6. **Rollback is simple.** If a bad change slips through, roll back by copying the backup:
   ```bash
   cp ~/hermes/groups/mps-volunteers/skills/backup/2026-06-01/CPF.md \
      ~/hermes/groups/mps-volunteers/skills/CPF.md
   ```

---

## References

- [MPS-AI-Agent-nanoClaw](https://github.com/J-Dheeraj/MPS-AI-Agent-_nanoClaw) — parent system (mps_server + Tauri client)
- [Tauri v2 docs](https://v2.tauri.app)
- [Ollama](https://ollama.com)
- [HDB](https://www.hdb.gov.sg) | [CPF](https://www.cpf.gov.sg) | [MOM](https://www.mom.gov.sg) | [MOH](https://www.moh.gov.sg) | [MSF](https://www.msf.gov.sg) | [ICA](https://www.ica.gov.sg)

---

## License

MIT
