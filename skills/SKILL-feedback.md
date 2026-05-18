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

1. The correction is logged immediately with timestamp and case reference
2. At the next scheduled evolution cycle (default: after 5+ tool-call sessions, or weekly via Curator), Hermes reviews logged feedback
3. The GEPA Optimizer reads the correction against its recent execution traces to understand the error pattern
4. A revised skill file is generated — for example, if 3 cases flagged the same CHAS threshold error, the SKILL-moh.md is updated
5. The updated skill is used from the next session onwards

## What triggers automatic skill creation

After any conversation involving 5 or more tool calls, Hermes automatically summarises the case trajectory into a skill file. For MPS, this typically happens when:

- A complex multi-agency case is handled
- A letter is drafted, then revised based on policy clarification
- A constituent has multiple prior cases that required research

These auto-skills appear in `skills/auto/` — for example:

- `hdb-widow-tenancy-transfer.md`
- `comcare-urgent-crisis-referral-pattern.md`
- `cpf-medisave-outpatient-scan-2026.md`

## Reviewing what the agent has learned

Ask the agent at any time:

```
show me your recent auto-skills
what have you learned from the last 10 MPS sessions?
summarise all corrections logged this month
```

## Forcing an evolution cycle

To trigger a manual self-improvement run (e.g. after a session with many corrections):

```
run skills evolve now
```

To run the Curator (consolidation and pruning):

```
run skills curator now
```

## Weekly self-review (scheduled)

Set up this task once (send to the MP bot):

```
Set up a scheduled task: every Monday at 6:00am, review all feedback
logged in the past 7 days and all auto-skills generated this week.
Send me a summary of:

1. Policy corrections made
2. New case patterns learned
3. Any skills that were pruned or consolidated
4. Suggested updates to my core knowledge (SOUL.md)

Name this task: weekly-self-review
```

The agent will send a Monday morning digest showing exactly what it has learned and proposing any SOUL.md updates for your approval.
