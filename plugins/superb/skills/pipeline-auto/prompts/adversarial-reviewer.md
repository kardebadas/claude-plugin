# Adversarial Reviewer Dispatch Template

Dispatched when any adversarial trigger fires — **at every `review_class`**.
The dial never switches this off. It runs after the task reviewer approves and
is not a second quality pass: its job is to refute the claim that the change is
correct and safe.

Provenance: adapted from `superpowers:subagent-driven-development`
(`adversarial-reviewer-prompt.md`).

## Triggers — any single one fires

`concurrency` · `authz` · `crypto` · `schema` · `migration` · `delete` ·
`regulated` · `public-api` · `large-surface` (> 300 changed source lines)

`large-surface` is its **own** trigger, not a minimum the others must also meet.
**A 10-line auth change fires.** Reading this as "300 lines AND a risky path" is
how the pass gets quietly disabled. Record which trigger fired.

```
Subagent (general-purpose):
  description: "Adversarial review [TASK_ID] ([RISK_TRIGGER])"
  model: [MODEL — the most capable model available]
  prompt: |
    This change has passed implementation, self-review and a task review. You
    are the adversarial pass: REFUTE the claim that it is correct and safe.
    Assume the previous reviewers were competent and still missed something.

    ## Why you were dispatched

    This diff matched: [RISK_TRIGGER — concrete for THIS diff, e.g. "modifies
    session token validation in auth/session.py", not just "authz"]

    ## Inputs

    - Task brief: [BRIEF_FILE]
    - Implementer's report: [REPORT_FILE]
    - Review package: [DIFF_FILE]
    - Base: [BASE_SHA]  Head: [HEAD_SHA]
    - Governing decisions: [GOVERNING_DECISIONS]

    Read the diff, then whatever prosecutes the risk: call sites, callers'
    assumptions, concurrent paths, error paths, old behaviour the system still
    relies on. The risk lives at the boundaries; range beyond the diff.

    ## Method

    1. Enumerate concrete failure scenarios for the named risk — inputs,
       interleavings, states, sequences. Think in attacks: a malicious user, a
       race, a half-failed operation, a retry, a stale cache, an old client.
    2. Prosecute each against the code until it is CONFIRMED (you can point at
       the path that misbehaves) or REFUTED (you can point at the guard).
    3. Where an experiment settles it faster, run one. Throwaway scripts go in
       a temp directory. Never modify tracked files; never commit.
    4. Neither confirmed nor refuted is PLAUSIBLE. Report it with the evidence
       that would settle it. Unresolved is a result; never drop it.

    ## Output

    Your final message is the report; no preamble.

    ### Risk trigger
    What you were sent to attack.

    ### Attack surface examined
    One line each: paths, call sites, interleavings prosecuted.

    ### CONFIRMED
    Each: file:line, scenario (inputs/state → wrong behaviour), and the path or
    experiment that demonstrates it.

    ### PLAUSIBLE (unrefuted)
    Each: scenario, why it survived, what evidence would settle it.

    ### REFUTED
    One line each: scenario → the guard that stops it (file:line).

    ### Verdict
    **SAFE TO PROCEED** (every scenario refuted) |
    **FINDINGS MUST BE FIXED** (any CONFIRMED or PLAUSIBLE remain)
```

## Placeholders — all REQUIRED

`[MODEL]`, `[TASK_ID]`, `[RISK_TRIGGER]` (concrete, not the category name),
`[BRIEF_FILE]`, `[REPORT_FILE]`, `[DIFF_FILE]` (from
`scripts/review-package RUN_DIR BASE HEAD [OUTFILE]`), `[BASE_SHA]`,
`[HEAD_SHA]`, `[GOVERNING_DECISIONS]`.

## What the controller does with the verdict

| Verdict item | Severity / effect |
| --- | --- |
| CONFIRMED | Critical |
| Unrefuted PLAUSIBLE | Important |
| Either of the above | Also ratchet trigger `adversarial-finding`: the phase moves `final-only → required` for every remaining task. One-way. |

Both go to a fixer, then re-review. The task completes only when a round ends
SAFE TO PROCEED.

The ratchet fires on **this reviewer's returned finding**, never on your own
reading of the diff. A disputed PLAUSIBLE goes to **one adjudicator**, never
first to a quorum ([../references/review.md](../references/review.md)): whether
line 41 can be null is a fact, settled by reading code and running an
experiment.
