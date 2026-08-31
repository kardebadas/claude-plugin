# Codex & Claude Plugin

Personal [Claude Code](https://claude.com/claude-code) and Codex plugins.

## Install

### Claude Code

```
/plugin marketplace add kardebadas/claude-plugin
/plugin install superb@kardebadas-claude-plugin
```

### Codex

Add the repository's local marketplace, then install `superb` from it:

```
codex plugin marketplace add /path/to/claude-plugin
codex plugin add superb@personal
```

## The `superb` namespace

One plugin, many skills. The prefix comes from the plugin name, so every skill
inside it is invoked as `superb:<skill>`:

| Skill | Invoke as | What it is |
| ----- | --------- | ---------- |
| [`setup`](plugins/superb/skills/setup) | `superb:setup` | Installs and verifies the dependencies the other skills need. Detects the harness, reports one fact per line, and on Claude Code runs the installs itself — then re-runs the check, because an install that printed no error has not been verified. On Codex, where plugins install through an interactive picker, it says so rather than attempting a workaround. |
| [`craft`](plugins/superb/skills/craft) | `superb:craft` | Turns a vague product idea into a clear definition of what to build. Puts a questionnaire tailored to the product in front of you — in a local browser UI, or in `CRAFT.md` — which you answer in your own time; each pass folds your answers in, records confirmed decisions, surfaces assumptions and contradictions, and gets shorter. Deliberately stops before planning — no tasks, no phases, no code. |
| [`pipeline`](plugins/superb/skills/pipeline) | `superb:pipeline` | Takes a settled idea to a finished branch: brainstorm, pressure-test, design gate, master plan, phase expansion, plan gate, then an autonomous per-phase implement/review/fix loop. Keeps its state on disk so a compaction or a crash cannot lose the run, and runs independent tasks as parallel implementers in separate worktrees. |
| [`bug-fix`](plugins/superb/skills/bug-fix) | `superb:bug-fix` | Carries a reported bug from symptom to a regression-tested fix. Dispatches an investigator into its own context, and refuses to plan a fix until the root cause is proven with `file:line` evidence — a plausible fix for an unproven cause closes the ticket and leaves the bug live. Not done until a test that failed before the fix passes after it. |

`craft` and `pipeline` are meant to run in order: `superb:craft` decides *what*
the product is, `superb:pipeline` decides *how* it gets built and then builds it.
`superb:bug-fix` is for afterwards, when something built has gone wrong. Crafting
reaching `CRAFT STATUS: VISION CLEAR` is the signal that the pipeline has
enough to work from — it is not an instruction to start building.

`pipeline` and `bug-fix` both compose the
[superpowers](https://github.com/obra/superpowers) skills, so install that
plugin too.

## What a session looks like

### `superb:setup`

```
> /superb:setup
```

```
HARNESS   claude
REQUIRED  superpowers  MISSING   not-installed
MARKET    claude-plugins-official  OK
ACTION    claude plugin install superpowers@claude-plugins-official
OPTIONAL  python3      OK        3.11.2
```

It runs the `ACTION` lines in order, then **re-runs the check** — the second run
is the verification, since an install that printed no error has not been proven.

`DISABLED` is reported separately from `MISSING`, because an installed-but-
disabled plugin looks present to anything checking only for the name while its
skills silently fail to load.

It will not write to your config, install a language runtime, or run `git init`
to satisfy an optional dependency. Without `python3` craft falls back to its
file questionnaire; outside a git repository pipeline runs tasks one at a time.

### `superb:craft`

```
> /superb:craft I want something like Spotify but for audiobooks

Mode: browser. Your questions are at
http://127.0.0.1:45893/?key=d3603afb…  ← open this, the key is part of the link

Round 1 is up — 15 questions. 5 REQUIRED, 7 IMPORTANT, 2 PREFERENCE, 1 OPTIONAL.
I'll wait; answer them whenever, and press Send when you're done.
```

You answer in the page. Each question says *why it matters* — "this decides
onboarding, account recovery and every piece of identity infrastructure you will
own for the life of the product" — so you know what you are choosing between.
Every question takes a free-text note beside the options, which is where
*"magic links, but I want passkeys later"* goes. And **you decide** hands a
question back: it gets recorded as a Delegated Decision and is never asked again.

Your brief grows in the sidebar as you answer. Press **Send to agent** and the
next round lands in the same page — smaller than the last one, because the
settled questions are gone and only what your answers opened up remains.

It ends one of two ways: you press **Finish**, or it runs out of things to ask.
Either way you are left with `CRAFT.md` — vision, scope, confirmed decisions,
delegated decisions, open questions, contradictions — and a status line:

```
CRAFT STATUS: VISION CLEAR
```

That is the signal there is enough to plan from. It is *not* an instruction to
start building.

If `python3` is missing or the server cannot start, it says so in one line and
puts the same questionnaire in `CRAFT.md` instead. Nothing is blocked by the UI.

### `superb:pipeline`

```
> /superb:pipeline build what CRAFT.md describes
```

It asks until nothing is ambiguous — there is no cap on question rounds, and
"use your judgment" changes the *format* of the questions, never whether an
unknown gets asked. Then two gates, and they are the only two:

```
GATE 1 — the design.   A spec, after two agents have tried to break it.
GATE 2 — the plan.     Phases, tasks, and which of them can run at once.
```

At GATE 2 you see the shape of the build before it starts:

```
Phase A — schema, renderer, session   deps: none
  W1  T1 session paths    T3 validation    T4 renderer     ← 3 at once
  W2  T2 session lock                                      ← needs T1
Phase B — the HTTP surface            deps: A
```

Tasks share a wave only when neither depends on the other **and** they touch no
file in common; each one then runs in its own git worktree. Phases with no
dependency between them run as concurrent lanes.

After that it runs on its own: implement, review, fix, next phase — stopping
only for a genuine unknown, a blocked subagent, or the finished branch. Every
task is reviewed by an agent that did not write it, and anything touching a
security or data-integrity boundary gets a second reviewer whose only job is to
prove it wrong.

The run's state lives on disk, so a compaction or a crash resumes from the
tracker rather than from memory.

### `superb:bug-fix`

```
> /superb:bug-fix uploads over ~5MB fail silently since Tuesday
```

It does not start editing. It dispatches an investigator into its **own
context** — the separate context is what stops the conductor reasoning about
implementation detail it will later have to judge — and waits for evidence:

```
## BUG INVESTIGATION

Reported symptom:  uploads over ~5MB fail silently
Root cause:        api/upload.ts:71 — the multipart limit is read from
                   MAX_UPLOAD_MB, unset in prod, so it falls back to 5
Execution path:    POST /upload -> parseMultipart -> limit=5 -> BREAKS AT
                   silent 413 swallowed by the catch on :88
Introduced by:     pre-existing; exposed by 4f2a1c9 raising the client cap
```

If it cannot pin a cause, it says what it ruled out and asks you for better
repro detail. **It will not plan a fix on a hypothesis** — that is the whole
point of the skill. A plausible fix for the wrong cause consumes the report,
closes the ticket, and leaves the bug live.

Then it asks only what is genuinely yours — two viable fixes, ambiguous intended
behaviour, a blast radius past this repo — and plans the rest. The plan carries
a **regression test that fails before the fix**, and the bug is not done until
that test passes, the original reproduction is gone, and the repo's own gates
are green. Re-running the repro by hand proves the symptom is gone today; the
test is what stops it coming back.

Commit conventions are read from the repository being fixed, not carried in from
somewhere else.

## Dependencies

**`superb:setup` installs and checks all of this for you** on Claude Code, and
tells you what it cannot do on Codex. The rest of this section is what it is
checking, for when you would rather know than run it.

**`craft` has none.** It is self-contained: the browser UI is Python 3.9+ using
only the standard library — no pip, no npm, no build step. If `python3` is
missing, or the server cannot start, it falls back to the `CRAFT.md`
questionnaire and keeps working.

**`pipeline` composes [superpowers](https://github.com/obra/superpowers) and
will not run without it.** It deliberately reimplements none of these — it owns
only the seams between them:

| Stage | Skill it invokes |
|-------|------------------|
| 1 — brainstorm | `superpowers:brainstorming` |
| 2, 3 — master plan, per-phase expansion | `superpowers:writing-plans` |
| 4 — the autonomous implement/review/fix loop | `superpowers:subagent-driven-development` |
| 5 — finish | `superpowers:finishing-a-development-branch` |

**`bug-fix` composes superpowers too, and ships its own agent.** It needs
`superpowers:writing-plans` to plan the fix, `superpowers:systematic-debugging`
for the no-subagent investigation path, and
`superpowers:subagent-driven-development` for fixes larger than three files.
The investigator itself is bundled — `plugins/superb/agents/bug-investigator.md`
— so there is nothing extra to install for it.

On Codex, `multi_agent = true` in `~/.codex/config.toml` enables the subagent
path. Without it `bug-fix` still runs, investigating inline under the same
evidence bar, because Codex has no `agents` manifest key and its agent roles are
TOML rather than markdown — so the bundled agent is not assumed to load there.

Both harnesses install it from the same upstream — `obra/superpowers` — through
their own plugin marketplace:

**Claude Code**

```sh
claude plugin marketplace add anthropics/claude-plugins-official
claude plugin install superpowers@claude-plugins-official
```

**Codex CLI** — open the plugin search interface with `/plugins`, search for
`superpowers`, and select *Install Plugin*.

**They are separate installs and they drift.** This machine currently runs
**6.3.0** under Claude Code and **6.2.0** under Codex. `pipeline` uses only the
four skills above, whose interfaces have been stable — but a version gap is
worth ruling out before blaming the pipeline for behaving differently in one
harness than the other.

**`pipeline` also expects a `/review` skill in the target repository.** Stage 4
calls it after every phase. If your repo has no `/review`, that step has nothing
to invoke — supply one, or expect the review half of the loop to be skipped.

### For contributors

Two gates, both run by CI on every push and pull request, and both worth running
before you push:

```
./tools/check-plugin.sh            plugin structure — frontmatter, namespace, manifests, drift
./tools/check-plugin-mutants.sh    proves the above can still fail
./tools/test-craftui.sh            the craft UI test suite
```

`check-plugin.sh` exists because `claude plugin validate --strict` does not
catch any of what it checks — it passes on a plugin whose agent has malformed
frontmatter, which then loads with its description silently stripped.

`check-plugin-mutants.sh` is the reason to believe it. A gate that passes
everything is indistinguishable from a gate that checks nothing, so the harness
applies 33 deliberate breakages and fails if any of them slips through. It works
on a throwaway copy of the repository and never touches your working tree.

The craft UI's test suite (`tools/test-craftui.sh`, 778 tests plus an
end-to-end smoke test) needs `python3` and nothing else to run. Two layers
**skip cleanly** when their runtime is absent, and are worth having:

- `node` — runs the page's `answerState` against `schema.answer_state` over
  1,049 cases, which is what keeps the two implementations of the four answer
  states from drifting apart.
- `chromium` — drives the real page in a real browser. It is the only layer
  that catches a broken page; the source lints pass against a page with a
  deliberate syntax error.

A green suite on a machine without them is a weaker green than it looks.

## Adding a skill to the namespace

Drop it in and it is namespaced automatically — no manifest edit is needed for
the skill itself:

```
plugins/superb/skills/<new-skill>/SKILL.md
```

The `name:` in that file's frontmatter is what follows the colon, so a skill
whose frontmatter says `name: foo` is invoked as `superb:foo`. Bump the
version in both plugin manifests and mention the skill in their descriptions
and in the table above.

## Layout

```
.claude-plugin/marketplace.json     the marketplace manifest
.agents/plugins/marketplace.json    the Codex local-marketplace manifest
plugins/superb/
  .claude-plugin/plugin.json        the plugin manifest — "name": "superb" sets the prefix
  .codex-plugin/plugin.json         the Codex plugin manifest
  skills/<skill>/SKILL.md           one directory per skill
  agents/<agent>.md                 subagents, auto-discovered by Claude Code
  skills/<skill>/references/        read at the stage that needs them
  skills/<skill>/templates/         copied into a run directory, never edited
```
