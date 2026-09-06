# Assumptions Register

## Operating mode

**Brain-Agent mode: ON.** Declared 2026-08-31, in answer to a direct question
in this session (register A1), verbatim as the option selected:

> **Brain Agents decide.** Each open question goes to a dedicated subagent with
> full context; its ruling closes the register entry and is recorded. Matches
> your standing preference from 2026-08-24. The run then stops only for things
> a Brain Agent genuinely cannot settle.

Recorded as a selection from a four-option question, not free text. Every Brain
Agent ruling from here is written into the Closed table below with its date and
the reasoning that produced it, so the user can overrule any of them.

## Open

| ID | Question | Why it matters | Status |
| -- | -------- | -------------- | ------ |

_(none)_

## Closed

| ID | Question | User's answer (verbatim) | Date |
| -- | -------- | ------------------------ | ---- |
| A1 | Operating mode: user or Brain Agent? | "Brain Agents decide. Each open question goes to a dedicated subagent with full context; its ruling closes the register entry and is recorded." | 2026-08-31 |
| A2 | How to handle the `bug-investigator` agent dependency? | "Ship a genericised copy. Put a stack-neutral bug-investigator in the plugin so `superb:bug-fix` works on install with no personal setup. Keeps the evidence-driven 'never guess, cite file:line' core, drops the WebRTC/proximity-chat specifics." | 2026-08-31 |
| A3 | How far to generalise the skill's content? | "Fully generalise. Commit rules defer to the repo's own conventions; the PHI trigger becomes 'regulated data, migrations, or an external contract'. Same discipline, works in any repo." | 2026-08-31 |
| A4 | Disposition of `~/.claude/skills/bug-fix/`? | "Zip backup, then remove. Same as the superpipeline handling on 2026-08-27 — a dated .zip alongside it, then delete the directory, so there is exactly one live copy." | 2026-08-31 |
| A5 | Must `superb:bug-fix` work on Codex? | "i want a full funcionaly plugin + skill" — GATE 1 approved with it. | 2026-08-31 |

## Decided without asking (user may overrule)

| ID | Decision | Basis |
| -- | -------- | ----- |
| D1 | Skill keeps `name: bug-fix`, invoked as `superb:bug-fix`. | `plugins/superb/README.md`: "The `name:` in that file's frontmatter is what follows the colon." Written repo rule. |
| D2 | Version bumped in both `plugin.json` manifests, 0.5.0 -> 0.6.0, plus all four description surfaces. | `plugins/superb/README.md` rule, extended by pressure-mechanics findings 7 and 10. |
| D3 | Step 1 is a three-branch conditional: `superb:bug-investigator` -> generic subagent carrying `references/investigator.md` -> inline `superpowers:systematic-debugging`. | pressure-mechanics 3-6: Codex has no `agents` manifest key (0 of 168 plugins), roles are TOML, and `~/.codex/agents/` is user-scope an install must not write to. A mandatory dispatch deadlocks there. |
| D4 | Agent is referenced **namespaced** as `superb:bug-investigator`, never bare. | pressure-redteam 1 / pressure-mechanics 2: a bare name resolves to the surviving personal agent, so every local test would be a false pass. |
| D5 | The "no `Co-Authored-By` / no attribution trailer / no session link" rule stays **explicit** in the skill rather than deferring to repo conventions. | pressure-redteam 4: superpowers asserts nothing equivalent (0 grep hits across 14 skills), so deferring would let the harness default win against an absolute user rule. |
| D6 | Drop `memory: user`; `color: purple` -> `magenta`. | pressure-mechanics 10: `memory` appears in 0 of 33 shipped plugin agents; purple is not in the documented colour set. |
