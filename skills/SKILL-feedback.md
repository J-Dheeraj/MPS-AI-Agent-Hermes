---
name: mps-self-improvement-feedback
description: Captures corrections and feedback from MPS sessions to feed into Hermes self-improvement cycle
triggers:
  - /feedback
  - that was wrong
  - correction
  - the threshold is
  - the policy changed
  - update your knowledge
  - that letter needed
---

# MPS Feedback and Self-Improvement

## How to submit a correction

Send the agent a correction at any time using this format:

```
/feedback [what was wrong] → [what it should be] | case [ID if relevant]
```

Examples:

```
/feedback CHAS Blue stated as household ≤$1,800 only → correct is
household ≤$1,800 OR per capita ≤$650 | case 42

/feedback EHG singles ceiling stated as $40,000 → correct is up to
$40,000, income ceiling $4,500/month | case 39

/feedback Letter to HDB addressed wrong department → should go to
HDB Branch, not HDB HQ for tenancy transfer cases | case 51
```

## What happens with feedback

**In the combined nanoClaw + Hermes setup:**

1. The `/feedback` command is sent in nanoClaw (production system), not Hermes directly
2. nanoClaw logs the correction as an anonymised pattern in `groups/main/feedback-log.md` — no constituent data, no NRICs, no names
3. Every Sunday, `weekly-skill-update.sh` exports the anonymised patterns to Hermes
4. GEPA processes the patterns: if 3+ cases flag the same error (e.g. wrong CHAS threshold), SKILL-moh.md is updated
5. The MP reviews every generated change in `skills/auto/` before it is applied to nanoClaw

**In Hermes standalone mode (offline):**

1. Feed corrections via `feedback-input.md`
2. Run: `hermes --profile mps-main skills evolve --now`
3. Review output in `skills/auto/`

## What triggers automatic skill creation

After any conversation involving 5 or more tool calls, Hermes automatically summarises the case trajectory into a skill file. For MPS, this typically happens when:

- A complex multi-agency case is handled
- A letter is drafted, then revised based on policy clarification
- A constituent has multiple prior cases that required research

These auto-skills appear in `skills/auto/` — for example:

- `hdb-widow-tenancy-transfer.md`
- `comcare-urgent-crisis-referral-pattern.md`
- `cpf-medisave-outpatient-scan-2026.md`

⚠️ **Review all auto-generated skills before applying to nanoClaw.** Check for fabricated policy figures or any text resembling constituent details.

## Forcing an evolution cycle

Via CLI (offline Hermes):

```bash
hermes --profile mps-main skills evolve --now
hermes --profile mps-main skills curator --run
```

Via nanoClaw weekly pipeline:

```bash
cd ~/nanoclaw
bash weekly-skill-update.sh
```

## Weekly self-review

The weekly pipeline (`weekly-skill-update.sh`) runs every Sunday and produces a review of:

1. Policy corrections processed
2. New case patterns learned
3. Skills pruned or consolidated by the Curator
4. Generated changes ready for your review

Review `skills/auto/` after each run and merge approved improvements into nanoClaw's `groups/main/CLAUDE.md`. See `INTEGRATION.md` in the nanoClaw repo for the full workflow.
