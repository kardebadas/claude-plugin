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
| [`craft`](plugins/superb/skills/craft) | `superb:craft` | Turns a vague product idea into a clear definition of what to build. Puts a questionnaire tailored to the product in front of you — in a local browser UI, or in `CRAFT.md` — which you answer in your own time; each pass folds your answers in, records confirmed decisions, surfaces assumptions and contradictions, and gets shorter. Deliberately stops before planning — no tasks, no phases, no code. |
| [`pipeline`](plugins/superb/skills/pipeline) | `superb:pipeline` | Takes a settled idea to a finished branch: brainstorm, pressure-test, design gate, master plan, phase expansion, plan gate, then an autonomous per-phase implement/review/fix loop. Keeps its state on disk so a compaction or a crash cannot lose the run, and runs independent tasks as parallel implementers in separate worktrees. |

The two are meant to run in order: `superb:craft` decides *what* the product is,
`superb:pipeline` decides *how* it gets built and then builds it. Crafting
reaching `CRAFT STATUS: VISION CLEAR` is the signal that the pipeline has
enough to work from — it is not an instruction to start building.

`pipeline` composes the [superpowers](https://github.com/obra/superpowers)
skills, so install that plugin too.

## Dependencies

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

Install it per harness — the two are separate installs from the same upstream,
and **they drift**: this machine currently runs **6.3.0** under Claude Code and
**6.2.0** under Codex. `pipeline` uses only the four skills above, whose
interfaces have been stable, but a version gap is worth knowing about before
blaming the pipeline for a difference in behaviour between harnesses.

```sh
# Claude Code
claude plugin marketplace add anthropics/claude-plugins-official
claude plugin install superpowers@claude-plugins-official

# Codex — see the superpowers README for the current install path
```

**`pipeline` also expects a `/review` skill in the target repository.** Stage 4
calls it after every phase. If your repo has no `/review`, that step has nothing
to invoke — supply one, or expect the review half of the loop to be skipped.

### For contributors

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
  skills/<skill>/references/        read at the stage that needs them
  skills/<skill>/templates/         copied into a run directory, never edited
```
