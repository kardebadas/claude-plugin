# Quorum Brain Dispatch Template

Use once per brain index when a quorum opens (and at stage 02). Dispatch exactly
three, one per index, each rendered from
`build_payload(qid, brain_index, run_dir=<run>)` **and from nothing else**.

Every placeholder below is a payload key. The payload is a whitelist: there is
no slot for the adoption floor, a rung value, the drift budget, elapsed time,
cost, the raiser, the raiser's preferred answer, or another brain's answer. If
you want a placeholder the payload does not carry, the answer is no.

**Check a rendered prompt, not this template:** every root in
`[READING_ASSIGNMENT.read]` and `[DECISIONS_EFFECTIVE]` must be
repository-root-relative (for example
`docs/superpowers/runs/<run-id>/decisions-effective.md`, never the bare file
name). A citation that does not resolve demotes silently to
`engineering-judgement`, so a wrong root makes every quorum escalate while
looking cautious.

```
Subagent (pipeline-auto-brain):
  description: "Quorum [QID] brain [BRAIN_INDEX] ([READING_ASSIGNMENT.label])"
  model: [MODEL — the most capable model available; never downgraded because
         a question looks easy]
  prompt: |
    Answer one question in writing, from evidence you can cite.

    ## The question

    [QUESTION]

    Axis: [AXIS]
    Question id: [QID]

    [If OPTIONS is non-empty:]
    Named options. Your `answer_key` must be exactly one of them:
    [OPTIONS — one `key` per line, nothing else]

    [If OPTIONS is empty:]
    No options were named. Answer in prose, leave `answer_key` empty, and make
    your `consequences` precise — they are how answers are compared.

    ## Your reading assignment

    You are [READING_ASSIGNMENT.label]. Start here and look hardest here:

    [READING_ASSIGNMENT.read — one line per entry: "<source>: <root>"]

    Other readers start from different material. That biases each of you toward
    a source, never toward an answer. Read outside your assignment when the
    question demands it and say so in your evidence; an answer that never
    touched your assignment is weak.

    Write every cited path relative to the repository root, inside it.

    ## Decisions already made

    Read [DECISIONS_EFFECTIVE]. Every entry is settled. Do not re-litigate one.
    If every answer you can construct contradicts a decision with
    `Provenance: human`, set `blocker` and name it.

    ## Select a rung; never write a number

    [RUNGS — the names, in the payload's order, one per line]

    The list is strongest first. Select the rung that honestly describes your
    grounding and cite what it requires. You are not told what any rung is worth
    or which is good enough; do not try to work it out. Every citation is
    checked against the line it names: one that does not resolve, or does not
    contain your claim, reprices your answer downward. Overclaiming lowers your
    weight; it cannot raise it.

    ## Your response

    [RESPONSE_SCHEMA]

    Every key is required; no other key is allowed. `alternatives` must name a
    real rejected option with a reason. There is no field for raising a question
    of your own: if something else must be decided first, or the question needs
    what only the user knows, or it is several decisions in one, set `blocker`
    and stop. A blocker is never held against you.

    You are one of several readers. You will not see their answers and they will
    not see yours. Nothing is won by agreeing or lost by standing alone.

    Return the JSON object and nothing else.
```

## Placeholders — these, and only these

| Placeholder | Source |
| --- | --- |
| `[QID]` | `qid` |
| `[QUESTION]` | `question` — verbatim, identical for all three brains |
| `[AXIS]` | `axis` |
| `[OPTIONS]` | `options` — `key` values only |
| `[READING_ASSIGNMENT.label]`, `[READING_ASSIGNMENT.read]` | `reading_assignment` |
| `[DECISIONS_EFFECTIVE]` | `decisions_effective` |
| `[RUNGS]` | `rungs` — names only; the payload carries no values |
| `[RESPONSE_SCHEMA]` | `response_schema` |
| `[BRAIN_INDEX]` | the index passed to `build_payload` (description line only) |
| `[MODEL]` | not from the payload: the most-capable-model policy |

`you_are_one_of_several` renders as the fixed sentence "You are one of several
readers." **Never render a count.** A reader who knows the panel size can reason
about what wins a plurality.

## After dispatch

| Situation | Do |
| --- | --- |
| Response missing (brain died, context lost) | Recovery: re-send that index's **persisted** payload, checked against `open.json`'s digest. Not a retry. |
| First response schema-invalid (includes empty `alternatives`, out-of-enum rung) | **One** retry with that index's full, byte-identical payload. Never "fix that field", never its answer pinned. The quorum waits. |
| Second invalid response | Non-response. Quorum incomplete: escalate. |
| A valid response | Never re-dispatched. |

"Identical" means identical to that index's own payload; the three payloads
differ by construction.

**Never re-dispatch a brain to reconsider** — not its rung, answer or
confidence. A request to think again moves the number without moving the
evidence. If you want a different answer, you want an escalation. Adoption rules
are in [../references/quorum.md](../references/quorum.md).
