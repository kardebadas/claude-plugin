# Pressure / red-team — porting `bug-fix` into the `superb` plugin

Date: 2026-08-31. Scope: the design as settled in `register.md` (A2, A3, A4, D1, D2).
Nothing implemented. Every claim below cites `file:line` from a file actually read.

## 0. The two things the brief asked me to verify first

**Both REQUIRED SUB-SKILLs exist.** `superpowers` 6.3.0 ships 14 skills and both
named ones are present:

```
/home/wp3/.claude/plugins/cache/claude-plugins-official/superpowers/6.3.0/skills/writing-plans
/home/wp3/.claude/plugins/cache/claude-plugins-official/superpowers/6.3.0/skills/executing-plans
```

Frontmatter confirms the invocation names: `writing-plans/SKILL.md:2` (`name: writing-plans`)
and `executing-plans/SKILL.md:2` (`name: executing-plans`). So `superpowers:writing-plans`
and `superpowers:executing-plans` both resolve. **No dangling sub-skill.** The problem
with step 4 is not existence — it is *which one*, see F-05.

Caveat worth writing down: `README.md:148-152` already records that this machine runs
superpowers **6.3.0 under Claude Code and 6.2.0 under Codex**. This verification covers
6.3.0 only. `executing-plans` is not currently in the pipeline dependency table
(`README.md:128-133`), so it has never been exercised on the Codex side by this plugin.

**Codex.** See F-03. Short version: the shipped agent does not install there, and
step 1 has nothing to dispatch.

---

## Findings

### F-01 — Critical. The agent reference is unqualified, so on this machine it resolves to the *personal* agent, not the shipped one.

`SKILL.md:47` says: "Launch the `bug-investigator` agent (Agent tool)". Bare name, no
plugin prefix.

Claude Code namespaces plugin-shipped agents by plugin name. Evidence from the live
agent roster in this session: `feature-dev:code-architect`, `feature-dev:code-explorer`,
`feature-dev:code-reviewer`, `code-simplifier:code-simplifier` — all `plugin:agent`.
Those come from plugins that ship an `agents/` directory:

```
/home/wp3/.claude/plugins/cache/claude-plugins-official/feature-dev/*/agents
/home/wp3/.claude/plugins/cache/claude-plugins-official/code-simplifier/1.0.0/agents
/home/wp3/.claude/plugins/cache/claude-plugins-official/stripe/0.6.3/agents
```

Meanwhile the *unqualified* `bug-investigator` is also live in the same roster, because
`/home/wp3/.claude/agents/bug-investigator.md` exists (user scope, `ls` confirms it,
7901 bytes, dated Mar 9).

**Decision A4 removes `~/.claude/skills/bug-fix/` only. It does not remove
`~/.claude/agents/bug-investigator.md`.** So after the port, on the machine where the
port is developed and tested:

- `superb:bug-fix` step 1 dispatches `bug-investigator` → the *personal, WebRTC-specific*
  agent, not the genericised plugin copy.
- The genericised copy is never exercised. Every test of the new skill is a false green.
- On a fresh install, where the personal file does not exist, the bare name resolves to
  nothing or to a same-named agent the installer happens to own.

**Fix:** the skill must name `superb:bug-investigator` explicitly, and the port should
either delete/rename the personal agent too, or the test plan must prove the plugin copy
ran (e.g. the plugin copy emits a marker line the personal one does not).

### F-02 — Critical. The agent file as it stands is unshippable: it hardcodes the user's home directory and names a private project.

Reading `/home/wp3/.claude/agents/bug-investigator.md`:

- `:6` — `memory: user` frontmatter.
- `:88` — "You have a persistent Persistent Agent Memory directory at
  `/home/wp3/.claude/agent-memory/bug-investigator/`." Absolute path into one user's home.
- `:122` — `Grep with pattern="<search term>" path="/home/wp3/.claude/agent-memory/bug-investigator/"`.
- `:126` — `path="/home/wp3/.claude/projects/-home-wp3-IntellijProjects-audio-chat-app/"`.
  This **names a private project** (`audio-chat-app`) and the user's Linux username in a
  file that would be pushed to `kardebadas/claude-plugin`, which `README.md:10` documents
  as installable via `/plugin marketplace add kardebadas/claude-plugin`.
- `:76` — "project-specific gotchas ... Pixi v8 resolution issues, cross-fiber setState
  cascades, blob URL failures, `playerSpeed` in pixels/second, and avatar URL priority
  ordering." Meaningless in any other repo; actively misleading as a checklist.
- `:9` — "TypeScript/React frontends, Go backends, and real-time WebRTC systems" (A3/A2
  already call for genericising this one; the four above are *not* covered by A2's wording,
  which only mentions dropping "the WebRTC/proximity-chat specifics").
- `:3` — all four `description` examples are proximity chat / avatars / spatial audio /
  screen share. The description is what routes the agent; shipping it as-is means the
  agent advertises itself for a video-chat app.
- `:86-131` — the whole "Persistent Agent Memory" block. This is harness-injected boilerplate
  for `memory: user` agents that has been baked into the file literally. Shipping it
  hands every installer a memory contract pointing at *this* user's directory.

This is the single largest gap between A2 as worded ("drops the WebRTC/proximity-chat
specifics") and what actually has to change. **A2's wording under-scopes the work.**

### F-03 — Critical. On Codex, `superb:bug-fix` does not work at all, and the plugin advertises Codex support.

The plugin claims both harnesses: `README.md:1-3` ("Personal Claude Code and Codex plugins"),
`plugins/superb/README.md:3` ("A personal skill collection for Claude Code and Codex"),
`plugins/superb/.codex-plugin/plugin.json:4` ("...skills for Codex").

Two independent breakages:

1. **The agent does not install.** `plugins/superb/.codex-plugin/plugin.json:8` declares
   `"skills": "./skills/"` and nothing else. Compare superpowers' own Codex manifest
   (`superpowers/6.3.0/.codex-plugin/plugin.json`): it declares `skills` and `hooks` — and
   superpowers ships **no `agents/` directory at all** (`ls` of its root confirms this;
   it is skills-only, which is exactly how it stays cross-harness). Per
   `using-superpowers/references/codex-tools.md:20`, Codex agents are **user-scope role
   files under `~/.codex/agents/`**, attached via `agent_type` — not something a plugin
   installs. So a plugin-shipped `agents/bug-investigator.md` reaches Claude Code only.
2. **Subagents are off by default.** `codex-tools.md:1-8`: "Subagent dispatch requires
   multi-agent support. Add to your Codex config (`~/.codex/config.toml`):
   `[features] multi_agent = true`."

Step 1 of the skill (`SKILL.md:45-54`) is *unconditionally* "dispatch the agent", and
`SKILL.md:89` makes it a Red Flag to investigate yourself: "About to edit code yourself
before the bug-investigator has reported → stop, dispatch it." On Codex without
`multi_agent`, the skill's first instruction is impossible and its Red Flag forbids the
only remaining path. It does not degrade — it deadlocks.

**Fix:** the skill needs an explicit degradation clause — "if no subagent facility is
available, run the same investigation protocol inline, in this session, before touching
any code" — and the investigation protocol needs to live somewhere the inline path can
read (e.g. `references/investigation.md` in the skill dir), not only inside the agent file.
That also makes the agent a performance optimisation rather than a hard dependency, which
is what A2's goal ("works on a fresh install with no personal setup") actually needs.

### F-04 — Major. Generalising the commit rule deletes the only thing stopping the harness from adding a `Co-Authored-By` trailer and a session link.

`SKILL.md:76` currently reads: "The plan's commit steps must follow repo rules
(`MIPS-XXXX` in the subject, no `Co-Authored-By`)."

A3 replaces this with "commit rules defer to the repo's own conventions". That drops
**both** halves — including the prohibition.

Why that matters: the Claude Code harness's own Bash tool instructions inject, verbatim,
"End git commit messages with: `Co-Authored-By: Claude ...`" and a
`Claude-Session: https://claude.ai/code/session_...` line, plus "End PR bodies with ...
`https://claude.ai/code/session_...`". That is a live default in this very session.
The user's global rule (`/home/wp3/.claude/CLAUDE.md`, "Commits") is absolute: **never**
any `Co-Authored-By`/attribution trailer, and **never** a session link "in commit messages,
code, docs, config, PR titles/descriptions/comments ... or any file that lands in a repo."

superpowers itself offers no counterweight: `grep -rni "co-authored|claude.ai/code/session|Generated with"`
over all 14 superpowers skills returns **zero hits**. So nothing downstream re-asserts it.

Deferring to "the repo's own conventions" means: a repo with no written convention gets
the harness default, which is the trailer and the session link. **Keep the prohibition,
drop only `MIPS-XXXX`** — and extend it to cover the session link, which the current text
does not mention.

### F-05 — Major. Step 4 hardcodes `executing-plans`, which self-declares as the *fallback for harnesses without subagents* — the exact opposite of what step 1 assumes.

`executing-plans/SKILL.md:14` (in-file line, body offset 5):

> "**Note:** Tell your human partner that Superpowers works much better with access to
> subagents (Claude Code, Codex CLI, Codex App, Copilot CLI, and Gemini CLI all qualify...).
> **If subagents are available, use superpowers:subagent-driven-development instead of this skill.**"

And `writing-plans/SKILL.md:61` writes into every plan it produces:

> "REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development **(recommended)** or
> superpowers:executing-plans"

with the same ranking at `writing-plans/SKILL.md:166` and `:170`.

`SKILL.md:78-85` picks the non-recommended one and forbids reconsidering:
"This is the user's chosen execution path — invoke it directly; do not re-prompt with
writing-plans' subagent-vs-inline choice."

Three problems:
- **Self-contradiction.** Step 1 requires subagents (F-03). Step 4 picks the skill that
  exists for when you have none.
- **"The user's chosen execution path" is a personal fact that becomes a lie on
  distribution.** A stranger installing `superb` never chose anything. This sentence is
  precisely the kind of leftover A3 is meant to remove, and A3's wording does not cover it.
- **Divergence from the sibling skill.** `superb:pipeline` uses
  `superpowers:subagent-driven-development` for its implement loop
  (`README.md:132`, `plugins/superb/skills/pipeline/README.md:82`). Two skills in one
  plugin choosing opposite execution engines for the same job needs a stated reason, or
  it reads as an accident.

### F-06 — Major. Step 4 silently pulls in worktrees and a branch-finishing flow, and the dependency table does not say so.

`executing-plans/SKILL.md` body, Step 1.1: "Ensure an isolated workspace: use
superpowers:using-git-worktrees to create one or verify the existing one." Step 3:
"REQUIRED SUB-SKILL: Use superpowers:finishing-a-development-branch."

So invoking `superb:bug-fix` on a one-line typo fix creates a git worktree and ends in a
branch/PR finishing flow. That is a real scope surprise for a skill whose entire selling
point — per `plugins/superb/skills/pipeline/SKILL.md:295` — is being the *light* path that
a single bug fix takes instead of the pipeline.

Documentation consequence: `README.md:128-133` lists the superpowers skills `superb`
depends on (brainstorming, writing-plans, subagent-driven-development,
finishing-a-development-branch). After this port that table is wrong — it must add
`executing-plans` and `using-git-worktrees` (and, if F-07 is acted on,
`systematic-debugging`). `plugins/superb/skills/pipeline/README.md:80-84` carries the same
list scoped to pipeline and is fine, but the new skill needs its own "Requires" section
matching that convention.

### F-07 — Major. Trigger collision with `superpowers:systematic-debugging`, which is already installed and which the plugin's own principle says to compose rather than duplicate.

- `bug-fix` description (`SKILL.md:3`): "Use when the user reports a bug, unexpected
  behavior, regression, or asks why something broke..."
- `systematic-debugging` description (`superpowers/6.3.0/skills/systematic-debugging/SKILL.md:3`):
  "Use when encountering any bug, test failure, or unexpected behavior, before proposing fixes"

These are the same trigger. Both will be installed (superpowers is a stated dependency,
`plugins/superb/README.md:14-15`). `systematic-debugging:9-11` states the same core
principle bug-fix states at `SKILL.md:15-17` — root cause before fix, no guessing.

`superb:pipeline`'s stated law is "**Core principle: compose, don't reimplement.** Every
stage delegates to the canonical skill for that job" (`plugins/superb/skills/pipeline/SKILL.md:16-19`).
Shipping a bug skill that never mentions `systematic-debugging` breaks that law inside the
same plugin.

**Fix:** either make step 1's investigation *be* `superpowers:systematic-debugging` (with
the agent as the dispatch vehicle), or narrow the description to the orchestration claim
("end-to-end: investigate → plan → execute") and say explicitly where systematic-debugging
fits. Leaving two skills with identical triggers is a coin-flip at routing time.

### F-08 — Major. `AskUserQuestion` is Claude-Code-only, and no other skill in either plugin uses it.

`SKILL.md:28`, `:39` (the dot graph), `:64-66` ("If yes, ask with `AskUserQuestion`") and
`:91` all name the tool.

Measured: `grep -rn "AskUserQuestion"` over all 14 superpowers 6.3.0 skills → **0 hits**.
Over `plugins/superb/skills/` → **0 hits**. Both existing superb skills ask in plain prose
(`plugins/superb/skills/pipeline/SKILL.md:36`, `:617`, `:688`).

That is not an accident. superpowers pushes the mapping to the harness — see
`superpowers/6.3.0/.kimi-plugin/plugin.json` `skillInstructions`, which translates "when a
skill says to ask the user ... call Kimi Code's `AskUserQuestion` tool". Naming the tool
inside the skill defeats that indirection and hard-codes one harness.

**Fix:** phrase step 2 as "ask the user, one question at a time, with 2-4 concrete options
and your recommendation first" and let the harness pick the mechanism — the convention the
two existing superb skills already follow.

### F-09 — Major. Three live cross-references break the moment A4 deletes the directory.

1. `plugins/superb/skills/pipeline/SKILL.md:295` — "**When NOT to use:** a single bug fix
   (use `bug-fix`)". Unqualified. Once the skill is namespaced this should read
   `superb:bug-fix`. Note the sibling convention: `plugins/superb/skills/craft/README.md:93`
   links `[superb:pipeline](../pipeline)` — namespaced name plus a relative link. Also
   `plugins/superb/skills/pipeline/README.md:74-76` explicitly documents that the prefix
   "only matters for disambiguation" — and with a personal `bug-fix` gone but a *plugin*
   `bug-fix` present, disambiguation is exactly what is needed here.
2. `/home/wp3/.claude/skills/execute-plan-phases/SKILL.md:24` — "A single, isolated bugfix
   or feature → use `bug-fix` / `feature-dev` instead." This is a *different* personal
   skill that A4 does not touch, pointing at the skill A4 deletes.
3. `/home/wp3/IntellijProjects/block-combat-game/CLAUDE.md:91` — "a single isolated bug fix
   — the skill itself routes that last one to `bug-fix`." A checked-in project instruction
   file in a different repo.

(2) and (3) are outside `claude-plugin`, so a port that only edits this repo leaves two
dangling routes. They need to be listed as follow-up work even if not fixed in this run.

### F-10 — Major. Plugin conventions the port must satisfy, several of which the settled decisions do not mention.

`plugins/superb/README.md:17-27` and `README.md:173-185` state the repo's own rule for
adding a skill. D2 covers only the version bump. Also required:

- **A `README.md` in the skill directory.** Both siblings have one:
  `plugins/superb/skills/craft/README.md` (93 lines),
  `plugins/superb/skills/pipeline/README.md` (91 lines). Each opens with the same line —
  "Part of the `superb` plugin — invoked as **`superb:<skill>`**." A skill dir with no
  README breaks the only structural convention the plugin has.
- **A row in two tables:** `plugins/superb/README.md:6-9` and `README.md:28-31`.
- **Three prose descriptions that enumerate the skills**, all of which currently list only
  craft and pipeline and will be wrong:
  - `plugins/superb/.claude-plugin/plugin.json:4`
  - `plugins/superb/.codex-plugin/plugin.json:4` (plus `interface.longDescription:12` and
    `interface.defaultPrompt:19-22`, which offer two prompts, neither about bugs)
  - `.claude-plugin/marketplace.json:12` — a **third** copy of the description, in a file
    D2 does not name. `README.md:184` says to "mention the skill in their descriptions",
    which is easy to read as the two plugin.json files only.
- **`.agents/plugins/marketplace.json`** (the Codex local marketplace, `README.md:191`)
  carries no description or version, so it needs no edit — worth stating so the port does
  not "fix" it.
- Frontmatter: both siblings carry `argument-hint`
  (`craft/SKILL.md:4`, `pipeline/SKILL.md:4`). `bug-fix` has no arguments, so omitting it
  is correct — but that should be a decision, not an oversight.

### F-11 — Minor. The agent's Step 1 and Step 2 assume a `.codex/` journal and a bug caused by the last commit.

`bug-investigator.md:21` — "find the matching `.codex/*.md` summary file. Read it fully";
`:22` — "If no exact timestamp match, read the most recent `.codex/*.md` file";
`:26` — "Run `git diff HEAD~1..HEAD`"; `:40` — "Is there a mismatch between what the
.codex summary INTENDED and what the code ACTUALLY does?".

`.codex/*.md` is this user's personal journal convention (this very repo uses
`docs/superpowers/runs/` instead, and `.superpowers/sdd/` for task reports — no `.codex/`
anywhere). On a generic repo those steps find nothing and burn a step; `HEAD~1..HEAD` also
fails outright on a single-commit repo. And the whole framing — orient on the *last commit*
— bakes in "the last change caused it", which is false for most reported bugs. `:48` half
acknowledges this ("If the last commit is not the cause, say so"), but it is the fallback,
not the default.

A2 does not mention any of this; it only mentions the WebRTC specifics.

### F-12 — Minor. `model: sonnet` and `color: purple` are shipped preferences.

`bug-investigator.md:4-5`. Pinning a model tier for every installer is a choice worth
making deliberately; superpowers ships no agents at all and therefore pins nothing.

### F-13 — Minor / informational. `docs/superpowers/plans/` in step 3 is correct but redundant.

`SKILL.md:73-75` says the plan lands "under `docs/superpowers/plans/`". That matches
`writing-plans/SKILL.md:18` ("**Save plans to:** `docs/superpowers/plans/YYYY-MM-DD-<feature-name>.md`"),
so it is not wrong — but it restates a spec owned by another skill, which is the classic
way two documents drift. Prefer "wherever writing-plans saves it".

### F-14 — Minor. Distribution reality check on "works on a fresh install".

`README.md:10` installs from `kardebadas/claude-plugin` on GitHub, and the local cache is
keyed by version (`/home/wp3/.claude/plugins/cache/kardebadas-claude-plugin/superb/{0.2.0,0.3.0,0.4.0,0.5.0}`).
The working tree is at `0.5.0` in both manifests and the repo has uncommitted work
(`git status`: `?? docs/superpowers/runs/2026-08-31-bug-fix-into-superb/`). So A2's promise
("works on a fresh install") is only testable after the bump **and a push** — the currently
installed `0.5.0` cache entry will not pick up a same-version change. The version bump in D2
is therefore load-bearing for testing, not just for tidiness.

---

## Consequences of the settled decisions the user may not have seen

- **A2 under-scopes the genericisation** (F-02, F-11): it names only "the WebRTC/proximity-chat
  specifics", but the agent also carries an absolute home path, a private project name, a
  `.codex/` journal dependency, a last-commit-first framing, a model pin, and a memory contract.
- **A2 does not make `superb:bug-fix` work on Codex** (F-03), even though the plugin advertises
  Codex. Shipping the agent solves the Claude Code half only. The genuinely
  harness-independent fix is to put the investigation *protocol* in the skill (or a
  `references/` file) and treat the agent as the fast path.
- **A3's "defer to the repo's conventions" removes a rule the user's own global CLAUDE.md
  makes absolute** (F-04). This is the finding most likely to produce a commit the user
  would have to rewrite.
- **A4 leaves the personal agent in place** (F-01), which will shadow the shipped one on the
  development machine and make every local test a false pass; and it orphans two
  cross-references outside this repo (F-09).
- **D1/D2 are correct but incomplete** (F-10): the repo's written rule also demands a skill
  README and table rows, and there is a *third* description (`.claude-plugin/marketplace.json:12`)
  that "both plugin manifests" does not cover.
