# claude-plugin

Personal [Claude Code](https://claude.com/claude-code) plugins.

## Install

```
/plugin marketplace add kardebadas/claude-plugin
/plugin install superpipeline@kardebadas-claude-plugin
```

## Plugins

| Plugin | What it is |
| ------ | ---------- |
| [`superpipeline`](plugins/superpipeline) | Takes a feature from idea to finished branch: brainstorm, pressure-test, design gate, master plan, phase expansion, plan gate, then an autonomous per-phase implement/review/fix loop. Keeps its state on disk so a compaction or a crash cannot lose the run, and runs independent tasks as parallel implementers in separate worktrees. |

`superpipeline` composes the [superpowers](https://github.com/obra/superpowers)
skills, so install that plugin too.

## Layout

```
.claude-plugin/marketplace.json     the marketplace manifest
plugins/<name>/
  .claude-plugin/plugin.json        the plugin manifest
  skills/<name>/SKILL.md            the skill itself
  skills/<name>/references/         read at the stage that needs them
  skills/<name>/templates/          copied into a run directory, never edited
```
