# Adversarial packaging review — `feat/bug-fix-into-superb`

Repo `/home/wp3/IntellijProjects/claude-plugin`, `git diff main..HEAD` (4 commits,
11 files). Scope: packaging, loading, and whether `tools/check-plugin.sh` is a real
gate. Everything below was reproduced by running it, not read off the diff.

Environment: `claude` 2.1.248, `/home/wp3/.local/bin/claude`.

All mutation work was done in a throwaway `git worktree` at
`$SCRATCH/mutwt` (detached at `0a12170`), never in the checkout. The worktree was
removed at the end; the checkout was never modified.

---

## 1. Does `superb:bug-investigator` load? — **CONFIRMED, it does**

The agent sits at `plugins/superb/agents/bug-investigator.md` with **no `agents`
key in `plugins/superb/.claude-plugin/plugin.json`**. That is correct and
sufficient.

Anthropic's own spec, `/home/wp3/.claude/plugins/marketplaces/claude-plugins-official/plugins/plugin-dev/skills/plugin-structure/SKILL.md`:

- line 140: *"**Auto-discovery**: All `.md` files in `agents/` load automatically"*
- line 345: *"**Agents**: Scans `agents/` directory for `.md` files"*
- lines 365-367: *"**Minimal manifest**: … Only specify custom paths when necessary.
  Rely on auto-discovery for standard layouts."*
- line 100: custom paths **supplement** defaults, they do not replace them.

So a manifest key would be redundant, and omitting it is the documented
best practice. Verified twice against the live CLI, not just the spec:

```
$ cd /home/wp3/IntellijProjects/claude-plugin
$ claude --plugin-dir ./plugins/superb plugin details superb
superb 0.6.0
  Description: Personal skill collection for Claude Code and Codex, invoked as superb:<skill>. …
  Source: superb@inline

Component inventory
  Skills (3)  bug-fix, craft, pipeline
  Agents (1)  bug-investigator
```

And, decisively, that it is addressable under the namespaced name the skill
insists on:

```
$ claude --plugin-dir <plugin> --model haiku -p \
  "List EXACTLY the subagent_type values available to the Agent tool, one per line…"
…
bug-investigator
superb:bug-investigator
```

Both appear. `superb:bug-investigator` resolves. The bare `bug-investigator` is
the user's personal, stack-specific agent at `/home/wp3/.claude/agents/bug-investigator.md`
(proximity chat, spatial audio, WebRTC, plus two absolute `/home/wp3/.claude/agent-memory/`
paths). **The collision the skill warns about at `bug-fix/SKILL.md:42-44` and
`:114-116` is real and live** — I reproduced both names coexisting in one session.
The warning is correctly worded and correctly placed.

Description integrity was checked as a control, because YAML with an em-dash and
a `file:line` colon is exactly where a parser bites:

```
$ claude --plugin-dir <plugin> --model haiku -p "Quote verbatim the description text shown for subagent_type superb:bug-investigator…"
Use when a bug, regression, or unexpected behaviour needs its root cause traced to
specific code before any fix is designed. Investigates only — never edits files.
Returns a structured report citing file:line evidence.
```

Intact. `claude plugin validate --strict` also passes on the marketplace manifest,
on the plugin manifest, and on the plugin directory (exit 0 for all three).

**Verdict: no defect. The agent loads, and it loads under the right name.**

---

## 2. Is `tools/check-plugin.sh` a real gate? — partly. 9 of 18 fresh mutants survived

Baseline: `bash tools/check-plugin.sh` → `check-plugin: PASS`, exit 0, 12 `ok`
lines, 0 `FAIL`.

The four mutation classes the commit message claims (brief drift, version drift, a
reintroduced `/home/…` path, frontmatter/directory mismatch, malformed JSON) do
hold up — I re-derived brief drift and file-rename kills below. What follows is
**fresh** mutants the script does not test for.

Method: for each mutant, `git reset --hard && git clean -fdq` in the worktree,
apply the mutation, run `tools/check-plugin.sh`, record exit code, reset.

| # | Mutant | Result |
|---|--------|--------|
| M1 | agent frontmatter present but **malformed YAML** (unterminated quote + tab indent + `- bad: : :`) | **SURVIVED** |
| M2 | `plugins/superb/skills/bug-fix/README.md` truncated to **empty** | **SURVIVED** |
| M3 | `SHARED BRIEF` marker pair deleted from **both** files | killed (`no SHARED BRIEF markers in …/agents/bug-investigator.md`) |
| M4 | new skill `ghost/` added with SKILL.md + README.md + a root-README row, **absent from `plugins/superb/README.md`** | **SURVIVED** |
| M5 | `"name"` deleted from **both** plugin manifests | **SURVIVED** |
| M6 | plugin renamed `superb` → `superbb` in **both** manifests (marketplace entry left at `superb`) | **SURVIVED** |
| M7 | agent frontmatter `description:` key deleted outright | **SURVIVED** |
| M8b | agent frontmatter `name:` deleted, a `name: bug-investigator` line planted **outside** the brief markers | **SURVIVED** |
| M9 | `skills/bug-fix/references/investigator.md` deleted | killed |
| M10 | Codex manifest `"skills": "./skills/"` → `"./nope/"` | **SURVIVED** |
| M11 | `.claude-plugin/marketplace.json` description reduced to `"Personal skill collection."` (bug-fix dropped) | **SURVIVED** |
| M12 | `bug-fix/SKILL.md` `description:` key deleted (skill would never trigger) | **SURVIVED** |
| M13 | `agents/bug-investigator.md` renamed to `agents/investigator.md` | killed (2 FAILs) |
| M14 | `bug-fix/SKILL.md` opening `---` deleted (no frontmatter at all) | **SURVIVED** |
| M15 | `pipeline/SKILL.md` reverted `superb:bug-fix` → bare `bug-fix` | **SURVIVED** |
| M16 | both manifests bumped to `9.9.9`, marketplace + READMEs untouched | **SURVIVED** |
| M17 | `bug-fix/SKILL.md` dispatches bare `bug-investigator` (drops the `superb:` prefix) | **SURVIVED** |
| M18 | `plugins/superb/agents/` deleted entirely, references kept | killed |

**14 survivors of 18. Ranked by what they actually cost:**

### M1 / M7 — malformed or missing agent frontmatter silently loses the description (Major)

`tools/check-plugin.sh:60` is `head -1 "$f" | grep -q '^---$'`. It reads **one
line**. Anything after it can be arbitrary garbage. And `:61`,
`sed -n 's/^name: *//p' "$f" | head -1`, scans the **whole file**, not the
frontmatter block — which is why M8b survives too.

The runtime is lenient enough that the agent still *appears*, so the naive
conclusion "it survives but nothing breaks" is wrong. Reproduced:

```
# malformed YAML applied
$ bash tools/check-plugin.sh   →  PASS
$ claude --plugin-dir <mutant> plugin details superb
  Agents (1)  bug-investigator          # still counted
$ claude --plugin-dir <mutant> -p "Quote verbatim the description text shown for subagent_type superb:bug-investigator…"
Agent from superb plugin                # ← the real description is GONE
```

Against the clean tree the same probe returns the full 214-character description.
So the failure mode is: **the agent is still listed, still dispatchable by
explicit name, and has lost every word that would make a model select it or
understand its remit** — and the gate says PASS. That is precisely the
"it looks like it worked" class of failure the branch's own SKILL.md is built to
prevent, reproduced against the branch's own gate.

The one-line fix is to parse the frontmatter block rather than `head -1`:
require a closing `---`, and require a non-empty `description:` inside it.

### M14 / M12 — a skill with no frontmatter, or no description, passes (Major)

`:50` uses the same whole-file `sed` for skills. Delete line 1 of
`bug-fix/SKILL.md` and `name: bug-fix` becomes line 1 of the body — the check
still matches it and prints `ok bug-fix: frontmatter name matches directory`.
A `SKILL.md` with no frontmatter has no description, so Claude Code can never
autonomously trigger it, which is the entire delivery mechanism for this branch.

### M6 / M5 — the namespace prefix is unguarded (Major / Minor)

`:37` compares the two manifests to each other and to nothing else. Rename the
plugin in both and it prints `ok both manifests name 'superbb'` — while
`.claude-plugin/marketplace.json` still says `superb`, every `superb:` reference
in both READMEs and all three SKILL.md files silently stops resolving, and
`bug-fix/SKILL.md`'s `superb:bug-investigator` mandate points at nothing. The
check never compares the manifest name to the marketplace entry or to the
directory name.

M5 is a logic bug rather than a coverage gap: `[ "$CN" = "$XN" ]` is **true when
both are empty**, so deleting `name` from both manifests prints
`ok both manifests name '' (the namespace prefix)` and exits 0. `:34` guards this
with `[ -n "$CV" ]` for version; `:37` has no such guard for name. Backstopped —
`claude plugin validate --strict` does catch it
(`name: Invalid input: expected string, received undefined`) — so Minor, but the
script's own stated premise (lines 4-6) is that validate is *not* the safety net.

### M4 / M2 — the plugin README is not covered at all (Minor)

`:53` is `grep -q "superb:$n" README.md` — the **root** README only. The plugin's
own README at `plugins/superb/README.md:8-10` carries a second, independently
worded skill table that nothing checks. Add a skill, register it in the root
README, forget the plugin README, and the gate passes. M2 shows the README
existence check at `:49` is presence-only: an empty file passes.

This matters more than it looks because `README.md:230-236` ("Adding a skill")
tells the next author to *"mention the skill in their descriptions and in the
table above"* — singular, root README. The plugin README is not named there
either. Two independent places both omit it.

### M11 / M16 — the four description surfaces are unguarded (Minor)

The whole premise of commit `8978e70` is that four description surfaces can drift
apart. Nothing checks any of them. Dropping `bug-fix` from the marketplace
description, or bumping both manifests to `9.9.9` while the marketplace and
READMEs stay behind, both pass clean.

### M15 / M17 — the `superb:` prefix rule is unenforced (Minor)

Commit `8978e70`'s stated fix was changing a bare `bug-fix` to `superb:bug-fix` in
`pipeline/SKILL.md:295`. Reverting that exact change passes the gate. So does
stripping the `superb:` prefix off the `bug-investigator` dispatch in
`bug-fix/SKILL.md:38` — the specific mistake that whole skill section
(`SKILL.md:42-44`, `:114-116`) exists to prevent, and the one that would silently
dispatch the user's audio-chat-app agent instead.

### M10 — Codex `skills` path not resolved (Minor)

`"skills": "./nope/"` passes. Nothing checks the manifest's declared paths exist.

### And the gate is not wired to anything (Major)

```
$ ls -a .github        →  No such file or directory
$ ls .git/hooks/ | grep -v sample   →  (nothing)
$ grep -rn "check-plugin" README.md plugins/superb/README.md  →  (no match)
```

No CI, no git hook, and **neither README mentions `tools/check-plugin.sh`**. The
only in-repo pointer to it is `skills/bug-fix/references/investigator.md:9` — a
file that ships to end users and, per finding F-008 already on the ledger, should
not be carrying packaging notes at all. `README.md:211` documents
`tools/test-craftui.sh` but not this one. A gate nobody is told to run, that no
automation runs, is a script.

---

## 3. Four description surfaces — the fifth is `keywords`

`.agents/plugins/marketplace.json` is **not** a fifth surface: it carries no
description at all (`name`, `interface.displayName`, `source`, `policy`,
`category`), and its `interface` block has no short/long description field. It is
correctly untouched — byte-identical to `main`, confirmed by the key diff in §6.

Both READMEs **were** updated, contrary to a "root README only" worry:
- `README.md:32` — full row for `superb:bug-fix`, plus `:36`, `:120-123` worked
  example, `:174-182` dependencies paragraph, `:247` `agents/` in the Layout block.
- `plugins/superb/README.md:10` — row; `:14` ordering sentence.

**The missed surface is `plugins/superb/.claude-plugin/plugin.json` `keywords`.**
Verified unchanged from `main`:

```
main: ['product-discovery','requirements','design','pipeline','orchestration',
       'planning','code-review','subagents','parallel','autonomous']
HEAD: identical
```

Ten keywords, and after this branch the plugin ships a bug-fix skill and a
bug-investigator agent, with none of `bug-fix`, `debugging`, `root-cause`,
`regression` among them. `plugin-structure/SKILL.md:84` — *"**Keywords**: Use for
plugin discovery and categorization"*. This repo's own pressure-test called it:
`pressure-mechanics.md:442` recommends adding exactly those three. It was not
done. Minor, but it is a real fifth surface and it is the one the branch's own
prior analysis flagged.

Two smaller notes on the four that *were* updated:
- `interface.shortDescription` grew to 76 chars — `pressure-mechanics.md:457`
  cites a ≤128 limit, ideally ~50. Within limits.
- `defaultPrompt` gained a third entry (`"Find out why this is broken and fix it."`),
  appended, nothing displaced.

---

## 4. Cross-references to the deleted bare `bug-fix`

`/home/wp3/.claude/skills/bug-fix/` is **gone** (only
`bug-fix.backup-2026-08-31.zip` remains). Confirmed:
`ls -d /home/wp3/.claude/skills/bug-fix` → *No such file or directory*.

**Dangling (outside this repo):**

1. `/home/wp3/.claude/skills/execute-plan-phases/SKILL.md:24` —
   *"A single, isolated bugfix or feature → use `bug-fix` / `feature-dev` instead."*
   `bug-fix` no longer resolves. Should read `superb:bug-fix`. **Confirmed dangling.**
2. `/home/wp3/IntellijProjects/block-combat-game/CLAUDE.md:91` —
   *"the skill itself routes that last one to `bug-fix`"*. **Confirmed dangling.**
3. **Not previously flagged:** the *same file*, `block-combat-game/CLAUDE.md:61` and
   `:63`, makes `/superpipeline` **mandatory** for every implementation task —
   *"Every implementation task goes through `/superpipeline`"*. That skill is also
   deleted (`/home/wp3/.claude/skills/superpipeline.backup-2026-08-27.zip`); the
   live skill list for that project offers `superb:pipeline`, not `superpipeline`.
   So the checked-in project rule that governs *all* work in that repo points at
   two dead skills, not one. Worth fixing in the same pass.
4. `/home/wp3/.claude/agents/bug-investigator.md` — **not dangling, but the live
   hazard.** Still present, still the audio-chat-app/WebRTC/proximity-chat version,
   still carrying `/home/wp3/.claude/agent-memory/bug-investigator/` absolute paths.
   Any bare `bug-investigator` dispatch lands here. Both names coexist — proved in §1.
   This is the exact scenario `bug-fix/SKILL.md:42-44` describes, so the skill text
   is right; the residual risk is the file itself, which the branch cannot delete
   and which nothing in the branch flags to the user.

**In-repo bare `bug-fix` mentions (all benign prose, no action needed):**
`README.md:40`, `:174`, `:182`; `plugins/superb/README.md:14`;
`.claude-plugin/marketplace.json:12`; `plugins/superb/.claude-plugin/plugin.json:4`;
`plugins/superb/.codex-plugin/plugin.json:4`. Each sits under or beside a table
row that already establishes `superb:bug-fix`, so none of them is an invocation.
The one invocation-shaped cross-reference, `pipeline/SKILL.md:295`, **was** fixed.
`craft/SKILL.md` contains no bug-fix cross-reference. No in-repo dangler.

---

## 5. User's absolute rules — clean

```
$ git log main..HEAD --format='%H%n%B%n%an <%ae>%n---' \
  | grep -inE 'co-authored|generated with|claude\.ai/code|session_|Claude-Session|noreply@anthropic'
NONE FOUND (clean)

$ git log main..HEAD --format='%an <%ae> | %cn <%ce>' | sort -u
kardebadas <16806320+kardebadas@users.noreply.github.com> | kardebadas <16806320+kardebadas@users.noreply.github.com>
```

All four commits authored and committed as the required noreply identity. No
`Co-Authored-By`, no attribution trailer, no session link, no session id, in any
commit message.

Added files scanned the same way. Exactly one hit:
`plugins/superb/skills/bug-fix/SKILL.md:86` —
*"**Never add a `Co-Authored-By` or any attribution trailer.**"* That is the
prohibition being stated, not a violation. `SKILL.md:87-88` states the session-link
rule alongside it. **No violation anywhere on the branch.**

---

## 6. JSON correctness — clean, nothing clobbered or reordered

All four manifests parse (`json.load`). Compared to `main` by flattening each
document to `path#ordinal → value`, so a reordered key registers as a
removal:

| file | removed/reordered | added | value-changed |
|------|-------------------|-------|---------------|
| `.claude-plugin/marketplace.json` | none | none | `.plugins[0].description` |
| `plugins/superb/.claude-plugin/plugin.json` | none | none | `.version`, `.description` |
| `plugins/superb/.codex-plugin/plugin.json` | none | `interface.defaultPrompt[2]` | `.version`, `.description`, `interface.shortDescription`, `interface.longDescription` |
| `.agents/plugins/marketplace.json` | none | none | none |

Every change is intended. `author`, `keywords`, `$schema`, `owner`, `source`,
`policy`, `category`, `capabilities`, `displayName`, `developerName` all preserved
at their original ordinal positions. `claude plugin validate --strict` passes on
the marketplace manifest, the plugin manifest and the plugin directory (exit 0).

---

## Cleanup

```
$ git worktree remove --force <worktree>; git worktree prune
$ git status --short
?? docs/superpowers/runs/2026-08-31-bug-fix-into-superb/
```

The only untracked path is the run directory this report is written into, which
was already untracked before the review began. No tracked file was modified.
