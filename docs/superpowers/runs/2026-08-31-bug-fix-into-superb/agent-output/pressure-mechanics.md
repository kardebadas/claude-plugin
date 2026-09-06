# Pressure test — packaging mechanics for shipping an agent inside `superb`

Date: 2026-08-31. Verification only; nothing was implemented. No file in
`/home/wp3/IntellijProjects/claude-plugin/plugins/` was modified.

All Codex CLI experiments below ran against a throwaway `CODEX_HOME` under the
session scratchpad. The user's real `~/.codex` and `~/.claude` were not mutated.

---

## 1. Claude Code — does the plugin format support bundled agents? **CONFIRMED: yes**

### 1a. Written specification (local, authoritative — Anthropic-published plugin)

`/home/wp3/.claude/plugins/marketplaces/claude-plugins-official/plugins/plugin-dev/skills/plugin-structure/SKILL.md`

```
plugin-name/
├── .claude-plugin/
│   └── plugin.json          # Required: Plugin manifest
├── commands/                 # Slash commands (.md files)
├── agents/                   # Subagent definitions (.md files)
├── skills/                   # Agent skills (subdirectories)
```

and, in the same file:

```
### Agents

**Location**: `agents/` directory
**Format**: Markdown files with YAML frontmatter
**Auto-discovery**: All `.md` files in `agents/` load automatically
```

```
## Auto-Discovery Mechanism
...
3. **Agents**: Scans `agents/` directory for `.md` files
```

Critical rules from the same file:

> 2. **Component locations**: All component directories (commands, agents,
>    skills, hooks) MUST be at plugin root level, NOT nested inside
>    `.claude-plugin/`

### 1b. The manifest key is OPTIONAL

Same file, "Component Path Configuration":

```json
{
  "name": "plugin-name",
  "commands": "./custom-commands",
  "agents": ["./agents", "./specialized-agents"],
  "hooks": "./config/hooks.json",
  "mcpServers": "./.mcp.json"
}
```

> **Important**: Custom paths supplement defaults—they don't replace them.
> Components in both default directories and custom paths will load.

So `"agents"` accepts a string or an array of strings, must be relative and
start with `./`, and is **only needed for non-default locations**. Default
`agents/` needs no key.

### 1c. Runtime proof that no key is needed

`feature-dev` ships three agents and declares **no** `agents` key:

`/home/wp3/.claude/plugins/marketplaces/claude-plugins-official/plugins/feature-dev/.claude-plugin/plugin.json`

```json
{
  "name": "feature-dev",
  "description": "Comprehensive feature development workflow with specialized agents for codebase exploration, architecture design, and quality review",
  "author": { "name": "Anthropic", "email": "support@anthropic.com" }
}
```

Its files:

```
$ ls /home/wp3/.claude/plugins/marketplaces/claude-plugins-official/plugins/feature-dev/agents/
code-architect.md
code-explorer.md
code-reviewer.md
```

The Claude Code CLI reports them as loaded components:

```
$ claude plugin details feature-dev
feature-dev
  Source: feature-dev@claude-plugins-official

Component inventory
  Skills (1)  feature-dev
  Agents (3)  code-explorer, code-reviewer, code-architect
  Hooks (0)
  MCP servers (0)
  LSP servers (0)

Per-component (rounded)
  component       always-on  on-invoke
  code-explorer         ~60       ~570
  code-reviewer         ~70       ~850
  code-architect        ~80       ~610
```

And for comparison, `superb` today:

```
$ claude plugin details superb
superb 0.5.0
Component inventory
  Skills (2)  craft, pipeline
  Agents (0)
```

Second, independent runtime proof: the live agent roster in this very session
lists plugin-provided agents, e.g. `feature-dev:code-architect`,
`feature-dev:code-explorer`, `feature-dev:code-reviewer`,
`code-simplifier:code-simplifier`. These come from plugins with **no** `agents`
manifest key. Auto-discovery is real and observable.

### 1d. Invocation name is `<plugin>:<agent-name>` — CONFIRMED

Live roster evidence, same session:

- personal agents (from `~/.claude/agents/`) appear **unqualified**:
  `bug-investigator`, `brainstorm-architect`, `claude-code-guide`
- plugin agents appear **namespaced**: `feature-dev:code-architect`,
  `code-simplifier:code-simplifier`

`feature-dev/agents/code-architect.md` frontmatter is `name: code-architect`,
and the plugin is `name: feature-dev`. So the id is
`<plugin.json name>:<agent frontmatter name>`.

**Consequence:** a `bug-investigator.md` shipped in `plugins/superb/agents/`
becomes **`superb:bug-investigator`**. The skill body at
`/home/wp3/.claude/skills/bug-fix/SKILL.md` currently says:

> ### 1. Investigate — dispatch the bug-investigator agent
>
> Launch the `bug-investigator` agent (Agent tool) ...

That unqualified name will keep resolving on this machine **only because the
personal copy at `/home/wp3/.claude/agents/bug-investigator.md` exists**. On a
fresh install it would not. The skill must say `superb:bug-investigator`.

### 1e. Agent frontmatter — documented fields, and the one that is not

`/home/wp3/.claude/plugins/marketplaces/claude-plugins-official/plugins/plugin-dev/skills/agent-development/SKILL.md`

| Field | Required | Format |
|-------|----------|--------|
| name | Yes | lowercase-hyphens, 3–50 chars, start/end alphanumeric, no underscores |
| description | Yes | 10–5,000 chars, triggering conditions |
| model | Yes | `inherit` / `sonnet` / `opus` / `haiku` |
| color | Yes | `blue`, `cyan`, `green`, `yellow`, `magenta`, `red` |
| tools | No | array of tool names |

Observed frontmatter keys across all 33 agent files in installed plugins on this
machine:

```
33 name:
33 description:
23 model:
22 tools:
21 color:
 7 effort:
 1 initialPrompt:
```

**`memory:` appears in zero of them.** It appears only in the user's two
personal agents:

```
$ grep -rn '^memory:' /home/wp3/.claude/agents/ /home/wp3/.claude/plugins/marketplaces/*/plugins/*/agents/
/home/wp3/.claude/agents/brainstorm-architect.md:6:memory: user
/home/wp3/.claude/agents/bug-investigator.md:6:memory: user
```

`memory` is **not documented** in `agent-development/SKILL.md` (grep for
`memory` in that skill directory returns nothing). Two other observed fields,
`effort:` and `initialPrompt:`, are likewise undocumented but *are* used by
shipped Anthropic plugins, so they are evidently tolerated.

**Verdict on `memory: user` — UNVERIFIED.** It is real enough that Claude Code
accepts it in a personal agent, but there is no evidence on this machine of any
plugin shipping it, and no documentation of its semantics in a plugin context.
Also note its meaning is user-scoped memory — semantically questionable in a
distributed plugin. Safest: drop it from the shipped copy.

Also note `color: purple` in `bug-investigator.md` is **not** in the documented
color set (`blue`, `cyan`, `green`, `yellow`, `magenta`, `red`). Likely
tolerated, but `magenta` is the documented equivalent.

### 1f. What `claude plugin validate` actually checks — a warning

`claude plugin validate --help` claims it validates "a plugin or marketplace
manifest, or the skills, agents, and commands in a directory". In practice,
pointed at a plugin root it validates **the manifest only**:

```
$ claude plugin validate <staged-copy-of-superb-with-agents/> --strict
Validating plugin manifest: .../.claude-plugin/plugin.json
✔ Validation passed
```

I then planted a deliberately invalid agent file in that same staged copy:

```
agents/broken.md
---
name: BAD_NAME!!
description: x
bogusfield: 1
---
body
```

Re-running the same command still printed `✔ Validation passed`. **So
`claude plugin validate` is not a safety net for agent frontmatter.** Do not
rely on it to catch a malformed shipped agent. `claude plugin details <name>`
on an installed plugin (the "Agents (N)" line) is the real check.

---

## 2. Codex — does `.codex-plugin/plugin.json` support bundled agents?

### 2a. There is no `agents` manifest key. **CONFIRMED (negative).**

The authoritative Codex manifest spec on this machine is
`/home/wp3/.codex/.tmp/plugins/.agents/skills/plugin-creator/references/plugin-json-spec.md`
(shipped inside OpenAI's own `openai/plugins` repo checkout). Its "Top-level
fields" guide lists exactly:

`name`, `version`, `description`, `author`, `homepage`, `repository`,
`license`, `keywords`, `skills`, `hooks`, `mcpServers`, `apps`, `interface`.

> - `skills`, `hooks`, and `mcpServers` are supplemented on top of default
>   component discovery; they do not replace defaults.

No `agents`. Corroborated empirically across every Codex plugin on this machine
— 168 plugins in the openai/plugins checkout:

```
$ for f in */.codex-plugin/plugin.json; do python3 -c "print keys" ; done | sort | uniq -c
    168 version
    168 name
    168 license
    168 keywords
    168 interface
    168 description
    168 author
    167 repository
    165 homepage
    145 apps
     57 skills
      2 mcpServers
```

Zero occurrences of a top-level `agents` key. (A grep hit on `openai-developers`
was `"agents"` inside its `keywords` array, not a key.)

The Codex scaffolder confirms the same surface list — `plugin-creator/SKILL.md`
"Supports optional creation of: `skills/`, `hooks/`, `scripts/`, `assets/`,
`.mcp.json`, `.app.json`" and flags `--with-skills --with-hooks --with-scripts
--with-assets --with-mcp --with-apps --with-marketplace`. **There is no
`--with-agents`.**

### 2b. A plugin-level `agents/` directory does exist in the wild — and survives install

`/home/wp3/.codex/.tmp/plugins/README.md` (openai/plugins repo root):

> Each plugin lives under `plugins/<name>/` with a required
> `.codex-plugin/plugin.json` manifest and optional companion surfaces such as
> `skills/`, `.app.json`, `.mcp.json`, plugin-level `agents/`, `commands/`,
> `hooks.json`, `assets/`, and other supporting files.

14 of the 168 plugins ship one (`figma`, `notion`, `zoom`, `vercel`, `expo`,
`render`, `airtable`, `heygen`, `atlassian-rovo`, `build-web-apps`,
`build-ios-apps`, `build-macos-apps`, `build-web-data-visualization`,
`test-android-apps`).

I verified installation preserves the directory. Scratch `CODEX_HOME`, local
marketplace built from a copy of `figma`:

```
$ CODEX_HOME=<scratch> codex plugin marketplace add <scratch>/mkt
Added marketplace `agenttest` from .../mkt.
$ CODEX_HOME=<scratch> codex plugin add figma@agenttest
Added plugin `figma` from marketplace `agenttest`.
Installed plugin root: <scratch>/plugins/cache/agenttest/figma/2.0.7
$ ls <scratch>/plugins/cache/agenttest/figma/2.0.7/agents/
design-parity-review-agent.md
design-system-rules-agent.md
figma-code-connect-agent.md
figma-implementation-agent.md
openai.yaml
```

codex-cli 0.150.1. The `agents/` dir is copied verbatim.

### 2c. But there is no evidence Codex *registers* those files as agent roles. **UNVERIFIED — treat as "does not work".**

Four independent pieces of negative evidence:

1. **Codex agent roles are TOML, configured in `config.toml`, not markdown in a
   plugin.** Strings extracted from the codex binary
   (`/usr/lib/node_modules/@openai/codex/node_modules/@openai/codex-linux-x64/vendor/x86_64-unknown-linux-musl/bin/codex`):

   ```
   struct AgentRoleToml with 3 elements
   description  config_file  nickname_candidates
   struct RawAgentRoleFileToml
   agents.<name>.description
   agents.<name>.config_file
   agents.<name>.nickname_candidates
   agents.<name>.config_file must point to a file:
   agents.<name>.config_file must point to an existing file at
   duplicate agent role name `...` declared in config
   duplicate agent role name `...` discovered in ...
   failed to deserialize agent role file at ...
   failed to parse agent role file at ...
   agent-roles/src/discovery.rs
   agent-roles/src/loader.rs
   ```

   The role model is a `[agents.<name>]` TOML table pointing at a `config_file`,
   plus directory discovery. Nothing links it to a plugin's `agents/` dir.

2. **The figma `agents/*.md` files have no frontmatter and are not TOML.**
   `figma/agents/figma-implementation-agent.md` begins directly with prose
   (`You are the Figma Implementation Agent for this plugin.`). It cannot
   deserialize as `RawAgentRoleFileToml`.

3. **Nothing in figma references them.** `grep -rn 'agents/'` and
   `grep -rn 'agent_type\|spawn_agent'` across `figma/skills`, `figma/commands`
   and `figma/.codex-plugin` return nothing. They are inert documentation.

4. **Codex's own system text enumerates a plugin's callable surface without
   agents.** From the binary:

   > Relationship to capabilities: Plugins are not invoked directly. Use their
   > underlying **skills, MCP tools, and app tools** to help solve the task.

Separately, `/home/wp3/.claude/plugins/cache/claude-plugins-official/superpowers/6.3.0/skills/using-superpowers/references/codex-tools.md` line 19–20:

> On Codex 0.145+, role files under `~/.codex/agents/` attach to isolated forks
> via `agent_type`.

That is a **user-level home directory**, not a plugin directory. And
`/home/wp3/.codex/agents/` does not exist on this machine (`ls` → No such file
or directory), so no role file is loaded here today.

Also relevant, from superpowers' own porting guide
(`.../superpowers/6.3.0/docs/porting-to-a-new-harness.md`):

> a port **must not** reach into a user's global or personal config ... to
> inject anything. The harness owns what it loads; your install artifact is the
> only thing you get to write.

So writing into `~/.codex/agents/` from an install step is explicitly ruled out
by the convention this repo follows.

**Verdict: shipping `plugins/superb/agents/bug-investigator.md` will be carried
into a Codex install but there is no evidence it becomes a dispatchable
`agent_type`. Do not depend on it. I could not run a live Codex session to
falsify this definitively — hence UNVERIFIED rather than CONFIRMED-negative.**

---

## 3. Fallback so `superb:bug-fix` works on a fresh install on both harnesses

The skill body is the portable artifact — that is the whole design of the
superpowers porting model (skills describe *actions*, harness tool-mapping is
separate). Concrete options, in order of evidence strength:

**Option A (recommended). Ship the agent for Claude Code, and write the skill so
the investigation phase degrades to an inline/generic subagent elsewhere.**
- `plugins/superb/agents/bug-investigator.md` → gives Claude Code
  `superb:bug-investigator`. CONFIRMED to load (§1c).
- The skill's step 1 says: dispatch `superb:bug-investigator` **if available**;
  otherwise dispatch a general-purpose subagent with the investigator's brief
  inlined (or, on a harness with no subagents at all, run the investigation
  procedure inline).
- This is the same pattern superpowers uses for cross-harness action vocabulary.
  Zero dependency on Codex loading plugin agents.

**Option B. Put the investigator's system prompt in the skill itself, as a
reference file, and dispatch a generic subagent with it.**
- e.g. `plugins/superb/skills/bug-fix/references/investigator-brief.md`; step 1
  spawns a general subagent whose instructions are that file's content.
- Works identically on both harnesses. **No** platform-specific agent
  registration needed at all.
- Cost: loses the Claude Code niceties (auto-dispatch on user phrasing, its own
  model/tools/colour, the "Agents (N)" inventory line).

**Option C. Ship both — the agent file for Claude Code *and* the reference brief
for everyone else.** Two copies of the same prose, which will drift. Only worth
it if the auto-dispatch behaviour on Claude Code is considered valuable enough
to pay maintenance for. If chosen, the agent file should be generated from the
reference, not hand-maintained twice.

Option A or B satisfy "works on a fresh install with no personal setup"
(register entry A2). Option C does too but adds a drift surface.

Note also: this run's A4 removes `~/.claude/skills/bug-fix/` after backup, so
after the change the *only* copy of the skill is the plugin's. That means the
personal `~/.claude/agents/bug-investigator.md` is the only thing that would
still satisfy an unqualified `bug-investigator` reference — and it is not being
removed by A4. **This will mask a broken reference on this machine.** Verify the
namespaced name works, not just that the flow runs.

---

## 4. Exact manifest changes required

### `plugins/superb/.claude-plugin/plugin.json` (current version: **`0.5.0`**)

Required:
- `"version"`: `0.5.0` → **`0.6.0`** (minor: new skill + new agent, additive,
  no breaking change to `craft`/`pipeline`). Repo rule, `plugins/superb/README.md`
  line 26–27: "Bump `version` in both plugin manifests and add a row to the
  table above."
- `"description"`: extend to mention `bug-fix`. Repo rule, root README line
  183–185: "Bump the version in both plugin manifests and mention the skill in
  their descriptions and in the table above."

Not required:
- **No `"agents"` key.** `agents/` at plugin root is auto-discovered (§1a/§1b/§1c).
  Adding `"agents": "./agents"` would be harmless but redundant; the docs say
  "Keep `plugin.json` lean … Only specify custom paths when necessary."

Optional/nice:
- `"keywords"`: add `"bug-fix"`, `"debugging"`, `"root-cause"`. The array
  currently reads `["product-discovery","requirements","design","pipeline","orchestration","planning","code-review","subagents","parallel","autonomous"]`.

### `plugins/superb/.codex-plugin/plugin.json` (current version: **`0.5.0`**)

Required:
- `"version"`: `0.5.0` → **`0.6.0`** — must match the Claude manifest.
- `"description"`: extend to mention `bug-fix`.
- `"interface.longDescription"`: currently *"Craft turns a vague product idea
  into a decision-rich brief. Pipeline takes an approved brief through planning,
  implementation, review, and fixes."* — mention `bug-fix` here too, this is the
  string the Codex plugin UI shows.

Consider:
- `"interface.defaultPrompt"`: currently two entries. The spec caps it at 3;
  a third bug-fix starter prompt fits (≤128 chars, ideally ~50).

Not available:
- **No `"agents"` key exists in the Codex manifest schema (§2a).** Do not invent
  one; an unrecognised key is at best ignored.

### `.claude-plugin/marketplace.json` (repo root)

- Has no `version` field for the plugin entry (versions live in
  `plugins/superb/.claude-plugin/plugin.json`). Its `plugins[0].description` is a
  **third** copy of the description text and currently already differs from both
  manifests — update it if `bug-fix` should appear in marketplace listings.
- Note `claude plugin tag` exists and "validat[es] that plugin.json and any
  enclosing marketplace entry agree" — worth running after the bump.

### `.agents/plugins/marketplace.json` (repo root, Codex)

- No change needed. It carries only `name`, `source`, `policy`, `category` —
  no version, no description.

---

## 5. Fields expected to stay in sync between the two `plugin.json` files

| Field | Claude manifest | Codex manifest | Must match? | Drift risk |
|---|---|---|---|---|
| `name` | `superb` | `superb` | **Yes** — it is the invocation prefix on both (`superb:<skill>`). | Low, but a mismatch silently changes the namespace on one harness only. |
| `version` | `0.5.0` | `0.5.0` | **Yes**, by explicit written repo rule (both READMEs). Nothing enforces it. | **High.** The repo's own README already documents superpowers drifting 6.3.0 vs 6.2.0 across harnesses. Nothing in `tools/` checks this; `tools/` contains only `test-craftui.sh`. A one-sided bump would be silent. |
| `description` | long, lists skills | short, Codex-flavoured | No, deliberately different in tone — but **both must mention every skill**, by repo rule. | **High and already live.** They are already different strings; adding `bug-fix` to one and forgetting the other is the exact failure mode. There is also a *third* copy in `.claude-plugin/marketplace.json`, and a fourth-ish in `interface.longDescription`. **Four places** to keep truthful. |
| `author.name` | `kardebadas` | `kardebadas` | Yes, cosmetically. | Low. |
| `keywords` | present (10) | absent | No — Codex spec allows it but the file omits it. | Low. |
| `interface.*` | n/a | present | Codex-only. | n/a, but `longDescription` and `defaultPrompt` are a second content surface that must not go stale. |
| `agents` key | not needed (auto-discovery) | does not exist | n/a | n/a |

**The silent-drift field to guard is `version`, followed by the four
description surfaces.** Neither has any automated check in this repo.

---

## Commands run (reproducible)

```sh
cat /home/wp3/IntellijProjects/claude-plugin/.claude-plugin/marketplace.json
cat /home/wp3/IntellijProjects/claude-plugin/plugins/superb/.claude-plugin/plugin.json
cat /home/wp3/IntellijProjects/claude-plugin/plugins/superb/.codex-plugin/plugin.json
cat /home/wp3/IntellijProjects/claude-plugin/.agents/plugins/marketplace.json

claude plugin details feature-dev
claude plugin details superb
claude plugin validate <staged-superb-copy> --strict     # manifest only; misses agents/

ls /home/wp3/.claude/plugins/marketplaces/claude-plugins-official/plugins/feature-dev/agents/
cat /home/wp3/.claude/plugins/marketplaces/claude-plugins-official/plugins/feature-dev/.claude-plugin/plugin.json
cat .../plugin-dev/skills/plugin-structure/SKILL.md
cat .../plugin-dev/skills/agent-development/SKILL.md
grep -rn '^memory:' /home/wp3/.claude/agents/ /home/wp3/.claude/plugins/marketplaces/*/plugins/*/agents/

cat /home/wp3/.codex/.tmp/plugins/README.md
cat /home/wp3/.codex/.tmp/plugins/.agents/skills/plugin-creator/references/plugin-json-spec.md
find /home/wp3/.codex/.tmp/plugins/plugins -maxdepth 2 -type d -name agents
strings <codex-rust-binary> | grep -E 'AgentRoleToml|agent role file|agent-roles/src'

CODEX_HOME=<scratch> codex plugin marketplace add <scratch>/mkt
CODEX_HOME=<scratch> codex plugin add figma@agenttest
ls <scratch>/plugins/cache/agenttest/figma/2.0.7/agents/

curl -sS https://anthropic.com/claude-code/marketplace.schema.json   # 301, no schema body
```

Tool versions: `claude` CLI as installed in this session; `codex-cli 0.150.1`.
The `$schema` URL in `marketplace.json` returns HTTP 301 to a Cloudflare page
and serves **no schema document** — it could not be used as evidence.
