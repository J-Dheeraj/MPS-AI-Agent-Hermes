# SKILL-feedback — Self-Improvement Feedback Capture

## Purpose

This skill provides a structured way to capture corrections and improvements from the MP after any MPS interaction. Feedback captured here feeds directly into Hermes's GEPA self-improvement cycle.

---

## How to submit feedback

The MP sends:

```
/feedback [description of what was wrong and what it should have been]
```

The agent will:

1. Acknowledge the feedback
2. Record it in a structured format in the feedback log
3. Flag it for the next GEPA evolution cycle

---

## Feedback categories

When receiving a `/feedback` command, classify it into one of these categories:

### POLICY_ERROR
Wrong policy information was given — incorrect income threshold, wrong scheme name, outdated eligibility rule, wrong agency.

Example:
> /feedback The letter said the EHG income ceiling is $8,000 for families. It is $9,000.

### TONE_ERROR
The drafted letter's tone was wrong — too emotional, too combative, too informal, or too cold.

Example:
> /feedback The letter used the word "unfair" which the agency may take badly. Use neutral language instead.

### FORMAT_ERROR
The letter structure was wrong — missing field, wrong addressee, wrong salutation, too long.

Example:
> /feedback Forgot to include the MP office email in the cc block.

### ROUTING_ERROR
The wrong agency was identified or the wrong department was addressed.

Example:
> /feedback I said write to MOM but this LTVP case should go to ICA.

### TRIAGE_ERROR
The urgency was mis-assessed, or the wrong action (letter vs SSO referral) was recommended.

Example:
> /feedback Flagged as normal urgency but this constituent had no food — should have been urgent with SSO referral.

### BEHAVIOUR_ERROR
The agent made a promise, speculated, or behaved outside its stated rules.

Example:
> /feedback Agent said "this should be approved by HDB" — that is a promise we cannot make.

---

## Feedback record format

When a `/feedback` command is received, write a new entry in the format below. The skills evolution system will index this automatically.

```
## Feedback entry — [DATE]

Category: [POLICY_ERROR | TONE_ERROR | FORMAT_ERROR | ROUTING_ERROR | TRIAGE_ERROR | BEHAVIOUR_ERROR]

What happened:
[Brief description of what the agent did]

What it should have done:
[Description of the correct behaviour]

Case context (optional):
[Agency, issue type — no constituent names or NRICs]

Action for next evolution cycle:
[What rule or knowledge should be updated]
```

---

## Patterns to watch for

If the same type of feedback appears more than once, flag it explicitly:

> **Recurring pattern:** [category] — this has occurred [N] times. Recommend GEPA priority review.

The curator will consolidate recurring feedback patterns into updated skill rules automatically during the weekly curation cycle.

---

## What this skill does NOT do

- It does not store constituent names, NRICs, or personal details in feedback entries  
- It does not override the agent's core behavioural rules without a GEPA evolution cycle  
- It does not bypass the PASS / NEEDS REVISION / FLAG vetting process

---

## Manual evolution trigger (if needed)

To force an immediate evolution cycle after multiple feedback entries:

```
hermes --profile mps-main skills evolve --now
```

Or ask the agent:

> Run a skills evolution cycle now based on the recent feedback.
