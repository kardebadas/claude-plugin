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
| [`craft`](plugins/superb/skills/craft) | `superb:craft` | Turns a vague product idea into a clear definition of what to build. Puts a questionnaire tailored to the product in front of you — in a local browser UI, or in `CRAFT.md` — which you answer in your own time; each pass folds your answers in, records confirmed decisions, surfaces assumptions and contradictions, and gets shorter. Technical questions branch on what you are building, so a CLI is never asked about a frontend framework. Drives its own rounds without prompting, and `VISION CLEAR` is earned by a script plus a reader who never saw the conversation. Deliberately stops before planning — no tasks, no phases, no code. |
| [`pipeline`](plugins/superb/skills/pipeline) | `superb:pipeline` | Takes a settled idea to a clean, committed local feature branch. It saves the approved design and plans, tracks task-level execution in a strict `pipeline-run/v2` file, runs compatible batches within an explicit `worker_limit`, mechanically verifies every phase, and applies formal review only at approved high-risk and final boundaries. |
| [`bug-investigate`](plugins/superb/skills/bug-investigate) | `superb:bug-investigate` | Finds out **why** something is broken and stops there — no plan, no edits. The same investigation `bug-fix` runs first, split out because "why is this happening?" is a different question from "fix this", and knowing is often the whole deliverable. |
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

The exit code is the instruction: `0` satisfied, `1` actionable, **`2` could not
be determined — install nothing.** That last one matters more than it looks. A
failed `claude plugin list` is not evidence that a plugin is absent, and treating
it as such reinstalls a working dependency over the top of itself.

`DISABLED` is reported separately from `MISSING`, because an installed-but-
disabled plugin looks present to anything checking only for the name while its
skills silently fail to load.

It will not write to your config, install a language runtime, or run `git init`
to satisfy an optional dependency. Without `python3` craft falls back to its
file questionnaire. Pipeline reports an unsatisfied runtime or repository
requirement instead of silently weakening its execution guarantees.

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
> /superb:pipeline
```

Pipeline first investigates the repository and writes an approved design, a
complete master plan, and one detailed file per phase. If the user instructions,
recorded answers, approved design/plans, and repository rules do not answer a
required question, affected work stops, the question is saved, and the user is
asked. Another agent's preference is never substituted for that answer.

```
docs/superpowers/specs/<feature>-design.md
docs/superpowers/plans/<feature>-master-plan.md
docs/superpowers/plans/<feature>/phase-*.md
docs/superpowers/runs/<run-id>/progress.md
```

`progress.md` is the single mutable execution tracker and carries the strict
`pipeline-run/v2` marker. Task ownership, attempts, checkpoints, source commits
or artifact evidence, integration, phase verification, reviews, and remediation
rounds are persisted there or referenced from it. After compaction, a restart,
or an interrupted worker commit, Pipeline reconstructs the next permitted
action from those files and Git evidence before deciding whether to resume,
reconcile, or dispatch anything.

Resume is v2-only. Recognized legacy v1 state and missing, malformed, unknown,
or unsupported schemas are rejected without changing the run or creating a
replacement. Starting a new v2 run is a separate explicit decision.

Every run also records an explicit positive `worker_limit`. It is one global
ceiling across phase planners, implementers, fixers, and reviewers. Tasks are
durable recovery checkpoints, not automatic agent boundaries: compatible
ordered tasks may share an executor, while independent batches may run in
parallel only after dependencies, unresolved questions, ownership, write-scope
conflicts, and current capacity are revalidated. Multi-task batches retain a
checkpoint for each task.

The review boundary is deliberately hybrid:

```
ordinary phase (`final-only`)  -> mechanical verification, no phase reviewer
approved high-risk phase       -> mechanical verification, then one reviewer
all accepted phases            -> mandatory master review by exactly two reviewers
```

Confirmed Critical and Important findings block. Findings are consolidated
before one scoped fix batch, then verified and re-reviewed at the same gate.
The default bound is three fix/re-review rounds per gate; the initial review is
round zero. A blocked or non-converging gate reaches the user rather than
waiving defects or resetting its history.

Completion leaves the designated feature branch clean, committed, integrated,
and locally recoverable. Pipeline never pushes, publishes, creates a pull
request, or merges into `main` or `master`.

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

**`pipeline` requires Python 3.11+ and composes
[superpowers](https://github.com/obra/superpowers).** Its standard-library
Python helper validates and atomically updates the local v2 tracker; it does
not install Python. This requirement is separate from Craft's Python 3.9+ UI
support. Pipeline owns only the orchestration and persistence seams:

| Stage | Skill it invokes |
|-------|------------------|
| Discovery and approved design | `superpowers:brainstorming` |
| Master plan and per-phase expansion | `superpowers:writing-plans` |
| Independent implementation batches | `superpowers:dispatching-parallel-agents`, `superpowers:using-git-worktrees` |
| Testable implementation and debugging | `superpowers:test-driven-development`, `superpowers:systematic-debugging` |
| Required high-risk and master reviews | `superpowers:requesting-code-review`, `superpowers:receiving-code-review` |
| Skill pressure tests and final evidence | `superpowers:writing-skills`, `superpowers:verification-before-completion` |

**`bug-fix` composes superpowers too, and ships its own agent.** It needs
`superpowers:writing-plans` to plan the fix, `superpowers:systematic-debugging`
for the no-subagent investigation path, and
`superpowers:subagent-driven-development` for fixes larger than three files —
that skill is `bug-fix`'s dependency, not `pipeline`'s. Pipeline uses its own
compatible-batch controller and has no per-task formal review.
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

**They are separate installs and can drift.** Check the installed contracts in
the harness that will run Pipeline. Pipeline does not depend on an external
review command, does not use Superpowers' per-task-development orchestrator,
and does not invoke an interactive branch-finishing workflow.

### For contributors

The repository checks below run in CI and are also worth running locally:

```
python3.11 -m unittest discover -s plugins/superb/skills/pipeline/tests -v
./tools/check-plugin.sh            plugin structure — frontmatter, namespace, manifests, drift
./tools/check-plugin-mutants.sh    proves the above can still fail
./tools/test-craftui.sh            the craft UI test suite
```

`check-plugin.sh` exists because `claude plugin validate --strict` does not
catch any of what it checks — it passes on a plugin whose agent has malformed
frontmatter, which then loads with its description silently stripped.

`check-plugin-mutants.sh` is the reason to believe it. A gate that passes
everything is indistinguishable from a gate that checks nothing, so the harness
applies deliberate breakages and fails if any changed-target mutation slips
through. It works on a throwaway copy of the repository and never touches your
working tree.

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
