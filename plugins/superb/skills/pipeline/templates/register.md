<!--
TEMPLATE — read-only. Copy to the run directory, then delete this comment:
  <PROJECT_DIR>/docs/superpowers/runs/YYYY-MM-DD-<topic>/register.md
-->

# Assumptions Register

An entry is closed **only** by an explicit user answer to **that entry**. Bulk
replies ("approved", "go", "looks good") close nothing. No gate may be
presented while the Open table has any row.

- **Last updated:** <timestamp>

## Operating mode

Normal — every open entry is a question to the user. Brain-Agent mode is on
only if the user declaring message is pasted verbatim below with its date
(see references/parallel.md); a summary or a memory of it does not count.

<!-- <date> — user, verbatim: "..." -->

## Open — these block the next gate

| ID | Entry | Why it is not mine to decide | Opened at |
| -- | ----- | ---------------------------- | --------- |
| A1 | Which ticket/issue key does every commit in this run carry? | No repo rule names the key for a particular run — only the user does, and every task in the run commits. Getting it wrong is not fixable without rewriting history. | Stage 1 |
| A1b | Does this repo require a key in a commit subject at all? | Open ONLY while the written rule has not been found. Find it and this row moves to *Decided without asking* with the rule cited; find that there is none and it closes there the same way. | Stage 1 |
| A2 | <the unknown, stated as the question it will become> | <why no default is legitimate> | <stage/phase> |

## Closed

| ID | Entry | Closed by (the user's actual answer) | Closed at |
| -- | ----- | ------------------------------------ | --------- |
| A0 | <entry> | <verbatim answer, not a paraphrase> | <timestamp> |

## Decided without asking — recorded so the user can overrule

Only for things a **written** repo rule or the approved spec already answers.
Anything else belongs in Open.

| Item | Call | The written rule or spec line that decided it |
| ---- | ---- | -------------------------------------------- |
| A1b — does a commit subject need a key? | <yes / no> | <the rule, cited — while this cell is empty the row belongs in Open> |
| <item> | <call> | <citation> |
