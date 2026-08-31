# bug-fix

Part of the `superb` plugin — invoked as **`superb:bug-fix`**.

Carries a bug from report to validated fix. It **conducts** rather than works:
investigation, planning and implementation each go to a specialist, and this
skill owns the seams and the evidence bar between them.

## The run

```
investigate (separate context, file:line evidence)
  -> decide what is genuinely the user's call
  -> plan (writing-plans, with a failing-first regression test)
  -> implement, scaled to the size of the fix
  -> verify: test fails without the fix, passes with it, repro gone, gates green
```

## What it actually enforces

**No fix is planned on an unproven cause.** The investigator must produce
`file:line` evidence. If it cannot, the skill relays what was ruled out and asks
for better repro detail rather than planning on a hypothesis — a plausible fix
for the wrong cause consumes the report, closes the ticket, and leaves the bug
live.

**The investigation happens somewhere else.** A separate context is what stops
the conductor reasoning about implementation detail it will later have to judge.

**A regression test, not a hand-run repro.** Re-running the reproduction proves
the symptom is gone today. A test that failed before the fix is what stops it
coming back.

**Someone else's conventions stay out.** Commit rules are read from the
repository being fixed. Two rules override anything the repo says, because they
belong to the user rather than the project: no attribution trailers, and no
session links anywhere.

## Portability

Step 1 is a three-way conditional, so the skill works wherever it lands:

| Harness | Investigation path |
| ------- | ------------------ |
| Claude Code | `superb:bug-investigator`, bundled in this plugin at `agents/` |
| Codex, or any harness with subagents but no bundled agent | A general subagent, given `references/investigator.md` as its brief |
| No subagent mechanism | Inline under `superpowers:systematic-debugging`, same evidence bar |

Codex has no `agents` manifest key and its agent roles are TOML, so the bundled
agent is not assumed to load there — hence the brief shipping separately as a
skill reference. `references/investigator.md` and `agents/bug-investigator.md`
share one body between `SHARED BRIEF` markers; `tools/check-plugin.sh` fails if
they drift.

## Dependencies

- **[superpowers](https://github.com/obra/superpowers)** — `writing-plans`,
  `systematic-debugging`, and `subagent-driven-development` for larger fixes.
- **Codex only, optional:** `multi_agent = true` in `~/.codex/config.toml`
  enables the subagent path. Without it the skill still works, investigating
  inline.
