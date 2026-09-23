# Stage-02 Brain Proposal Template

Use once per brain index at stage 02, and only then. Dispatch exactly three
`pipeline-auto-brain` agents, one per reading assignment. Sequentially if
`worker_limit < 3`; never fewer.

There is no qid yet and no `build_payload` call: the brains propose questions,
they do not answer one. Render every placeholder from the table below **and
from nothing else** — no other brain's proposals, no count of brains, no
questions you would like to see, no stage-01 majority reading.

```
Subagent (pipeline-auto-brain):
  description: "Stage-02 proposal brain [BRAIN_INDEX] ([ASSIGNMENT_LABEL])"
  model: [MODEL — the most capable model available]
  prompt: |
    Stage-02 proposal mode. You do not answer a question: you propose the open
    decisions the run's one human gate should ask. The response shape below
    replaces the quorum answer shape. Your tools and every "must not" in your
    agent definition still hold.

    ## The request, as read

    Intent brief: [INTENT_BRIEF]
    Decisions already made: [DECISIONS_EFFECTIVE]. Every entry is settled; never
    propose one again.

    ## Your reading assignment

    You are [ASSIGNMENT_LABEL]. Start here and look hardest here:

    [ASSIGNMENT_READ — one line per entry: "<source>: <root>"]

    Other readers start from different material. Read outside your assignment
    when a proposal demands it. Every source's root, yours included:

    [READING_ROOTS — one line per entry: "<source>: <root>"]

    Write every cited path relative to the repository root, inside it.

    ## What to propose

    At most four open decisions. Each one must:

    1. Block named planning work — `stage-04-design`, `stage-05-spec`,
       `stage-06-master-plan` or `stage-07-fan-out`. Blocking nothing is an
       opinion; leave it out.
    2. Need the user. The request, the intent brief, the repository and the
       decisions record do not settle it: it turns on budget, deadline, who the
       users are, what the product is for, or which product this is. What the
       repository or a later quorum could decide is not a gate question.
    3. Pass the options test: blank the question, keep the options, and a reader
       can still tell what is being decided. Options are named alternatives
       (`PostgreSQL`, `SQLite`), never adjectives (`scalable`, `simple`) and
       never a conclusion with its reason attached.
    4. Be one decision, not several wearing one coat.

    Proposing nothing is a valid answer. Never pad to four.

    ## Your response

    One JSON object, exactly these two keys:

    {
      "proposals": [
        {
          "axis": "session-store",
          "question": "Where do user sessions live?",
          "options": [
            {"key": "postgres", "label": "Existing PostgreSQL instance"},
            {"key": "redis", "label": "New Redis service"}
          ],
          "blocks": ["stage-05-spec"],
          "blast_radius": "run",
          "why_the_user": "Adding Redis is a paid external service; the brief is silent on cost.",
          "evidence": [{"path": "db/engine.py", "line": 12, "quote": "PostgresEngine"}]
        }
      ],
      "blocker": null
    }

    | Key | Rule |
    | --- | --- |
    | `axis` | lowercase hyphenated id, stable, never `new` |
    | `question` | one sentence, one decision |
    | `options` | 2–4 objects, each exactly `key` and `label`, keys distinct |
    | `blocks` | non-empty; only the four stage names above |
    | `blast_radius` | exactly one of `task`, `phase`, `run`, `contract` (`contract`: changes a public interface or the spec) |
    | `why_the_user` | what only the user knows that decides it; never "unclear" |
    | `evidence` | `path`/`line`/`quote` citations of what you read that leaves it open; may be empty only when the gap is an absence |
    | `blocker` | `null`, or a short reason you cannot propose (for example the intent brief is missing) |

    No other key, at either level. No confidence, no ranking, no answer to
    your own proposal. You are one of several readers; you will not see their
    proposals and they will not see yours.

    Return the JSON object and nothing else.
```

## Placeholders — these, and only these

| Placeholder | Source |
| --- | --- |
| `[BRAIN_INDEX]`, `[ASSIGNMENT_LABEL]` | `READING_ASSIGNMENTS[i]` index and `label` — the same three as the quorum |
| `[ASSIGNMENT_READ]` | that assignment's `read` sources with their roots |
| `[READING_ROOTS]` | every source's root. A source with no artifact yet (`spec`, `phase-plan` before stages 05–07) renders `none yet`; never substitute another file |
| `[INTENT_BRIEF]` | the published stage-01 brief's path, repository-root-relative |
| `[DECISIONS_EFFECTIVE]` | `decisions-effective.md` path, repository-root-relative |
| `[MODEL]` | the most-capable-model policy |

**Never render a count** of brains or of proposals wanted beyond "at most four".

## After dispatch

| Situation | Do |
| --- | --- |
| Response missing | Re-send that index's identical prompt. Not a retry. |
| First response invalid (extra or missing key, bad `blast_radius`, `blocks` outside the four, fewer than two options) | **One** retry with the byte-identical prompt. Never "fix that field". |
| Second invalid response | That brain contributes no proposals; record it for the terminal report. Never dispatch a fourth. |
| `blocker` set | Record it for the terminal report; merge the other brains' proposals. Never re-dispatch to get past it. |

## Merge — ranking and cutting are routing

1. Drop any proposal failing the four rules above. Never repair one.
2. Dedupe: same `axis`, or the same decision under different words (option
   sets name the same alternatives). Keep the version whose options pass the
   options test most concretely; union the `blocks`; keep the widest
   `blast_radius`.
3. Rank by `blast_radius`: `contract`, `run`, `phase`, `task`. Proposals made by
   more brains break ties; agreement never lifts a proposal past a wider radius.
4. Unresolved stage-01 conflicts take the first slots (`Origin: intent-conflict`).
   Cut the rest to fill **four** in total.
5. Write each kept one as a `## Questions` row: `ID` = `axis`,
   `Origin: synthesis`, next `Slot`, `State: proposed`, `Decision: -`.

Answer none, add none of your own, reword none beyond merging duplicates.
Stage 03 asks exactly these ([../references/planning.md](../references/planning.md)).
