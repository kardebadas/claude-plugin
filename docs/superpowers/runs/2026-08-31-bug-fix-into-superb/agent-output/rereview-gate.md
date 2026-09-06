# Re-review — `tools/check-plugin.py` gate (commits `9321fe5`, `6770d01`)

Independent adversarial re-verification. Every result below was produced by
mutating the working tree, running `./tools/check-plugin.sh`, recording the exit
code, then reverting. Baseline: **PASS, exit 0**. Sanity check that the gate can
fail at all: corrupting `plugin.json` to `garbage` → **exit 1**, one `FAIL` line.
The gate is not a no-op.

Harness: `scratchpad/mutate.sh` — refuses to run on a dirty tree, reverts with
`git reset && git checkout -- . && git clean -fd` after each mutant.

---

## Verdicts

### F-011 (Critical) — malformed agent frontmatter — **STILL OPEN (narrowed)**

The `head -1 | grep '^---$'` bug is genuinely gone. `frontmatter()` now finds the
block between the first two `---` lines and rejects anything that is not a
`key: value` pair. The original mutant dies:

| Mutant | Result |
| --- | --- |
| `description: …` → `description …` in `agents/bug-investigator.md` | killed — `line 3: not a 'key: value' pair` |
| delete the closing `---` (agent) | killed — `frontmatter opened but never closed` |
| delete the closing `---` (`craft/SKILL.md`, which has a later `---` at line 23) | killed — `line 6: not a 'key: value' pair -> '# Crafting Skill'` |
| `name:` present but empty | killed — `frontmatter name '' != filename` |
| `name: bug: investigator` | killed (accidentally — the value mismatches, not because the YAML is invalid) |

But the parser is a line regex, **not a YAML parser**, so frontmatter that a real
YAML loader rejects still passes. Both of these are exactly F-011's symptom — the
agent loads as "Agent from superb plugin" with its description stripped:

| Mutant | PyYAML | Gate |
| --- | --- | --- |
| **N18** — insert a **tab-indented** continuation line into the agent frontmatter | `ScannerError` | **SURVIVED, exit 0** |
| **N19** — `color: *undefined_anchor` (undefined YAML alias) | `ComposerError` | **SURVIVED, exit 0** |

Verified with PyYAML 6.x in a scratch venv. Both are well-formed *lines* and
malformed *YAML*. F-011's class is narrowed, not eliminated.

Related false positive in the same parser: `name: "bug-fix"` — perfectly valid
YAML, quoting a scalar — is **rejected** (`frontmatter name '"bug-fix"' != directory
(namespace would be superb:"bug-fix")`). So does `name: bug-fix # comment`. The
parser strips no quotes and honours no comments.

### F-012 — name checks scoped to the frontmatter block — **CLOSED**

Every variant dies: deleting `SKILL.md` line 1 (`no frontmatter: first line is not
'---'`), emptying `SKILL.md` outright, deleting the `name:` line
(`frontmatter name None != directory`), whitespace-only `description:`
(`frontmatter has no description — it will never trigger`). The whole-file scan
is gone; parsing is confined to the block.

### F-013 — namespace prefix guarded — **CLOSED**

| Mutant | Result |
| --- | --- |
| `superb`→`superbb` in **both** plugin manifests | killed — `not a plugin in the marketplace manifest (['superb'])` |
| marketplace entry name → `superbz`, manifests untouched | killed — `name 'superb' is not a plugin in the marketplace manifest (['superbz'])` |
| `git mv plugins/superb plugins/superbq` | killed |
| rename in **3 of 4** places (both manifests + marketplace, not the directory) | killed — `does not match a directory under plugins/` |
| `plugins` array emptied / `plugins` key removed | killed |

Four-way agreement (claude manifest ↔ codex manifest ↔ marketplace entry ↔
directory) is real.

### F-014 — wired to something — **CLOSED (with an unguarded caveat)**

- `.github/workflows/checks.yml` exists, is **tracked** (`git ls-files` mode
  `100644`), triggers on `push: [main]` and all `pull_request`.
- **YAML is valid** — parsed with PyYAML 6.x, clean load. (`on:` deserialises to
  the key `true` under YAML 1.1 boolean coercion; that is expected and GitHub's
  own parser handles it. Not a defect.)
- Both referenced scripts **exist and are executable in git**, not just on disk:
  `100755 tools/check-plugin.sh`, `100755 tools/test-craftui.sh`. A fresh CI
  checkout will be able to run `./tools/check-plugin.sh` and `./tools/test-craftui.sh`.
- Root `README.md` §*For contributors* names both gates and says CI runs them.
- No git hook exists, and `plugins/superb/README.md` still never mentions the gate.
  The finding's substance ("no CI, no README mention") is fixed.

**Caveat, and it is not small:** the wiring is unguarded by the very gate it wires.
Deleting `.github/workflows/checks.yml` (**N33**) leaves the gate green, and
renaming `tools/test-craftui.sh` (**N35**) leaves it green while the workflow now
points at a script that does not exist. F-014 can silently regress.

### F-016 — the nine further mutants — **CLOSED**

All die cleanly:

| Mutant | FAIL message |
| --- | --- |
| empty skill README | `bug-fix/README.md is effectively empty` |
| missing skill README | `craft has no README.md` |
| skill missing from **plugin** README | `bug-fix missing from the plugin README` |
| skill missing from **root** README | `bug-fix missing from the root README` |
| marketplace *plugin entry* description drops a skill | `bug-fix missing from the marketplace description` |
| version drift (`0.6.0` vs `0.6.1`) | `version drift or missing` |
| version key removed from one manifest | `version drift or missing: claude='0.6.0' codex=None` |
| bogus codex `skills` path | `'./nope/' does not exist` |
| both `superb:` prefix reverts | see F-013 |
| skill dir with only a README | `ghost has no SKILL.md` |
| brief drift between agent and reference | `brief has drifted` |
| brief emptied on **both** sides | `SHARED BRIEF block is empty` |
| `SHARED BRIEF: begin` with no matching `end` | `no SHARED BRIEF markers in …` |
| personal path / `MIPS-123` in a `.md` | `personal paths or foreign conventions: …:63` |

"Version drift vs README" is moot — no README carries the plugin version any more.

### F-017 — the fifth surface — **STILL OPEN (data fixed, surface ungated)**

The *data* is fixed: `keywords` now contains `bug-fix`, `debugging`, `root-cause`.
The *surface* is not guarded, so the regression can recur silently. The gate checks
three per-skill surfaces (root README, plugin README, marketplace entry description)
and **neither plugin manifest's own description nor `keywords`**:

- **S1** — strip `bug-fix`, `debugging`, `root-cause` from `.claude-plugin/plugin.json`
  `keywords` → **SURVIVED, exit 0**. This is F-017 reintroduced verbatim.
- **S2** — replace the Claude manifest `description` with `"Personal skill collection."`,
  erasing all three skills → **SURVIVED, exit 0**.
- **N36** — replace the codex manifest `description` *and* `interface.longDescription`
  → **SURVIVED, exit 0**.

`README.md:246-249` explicitly instructs contributors to "mention the skill in
their descriptions" (both plugin manifests). Nothing enforces it.

---

## Surviving mutants — full list

Every one leaves `check-plugin: PASS`, exit 0.

| # | Mutation | Why it matters |
| - | -------- | -------------- |
| S1 | `keywords` in `.claude-plugin/plugin.json` loses `bug-fix`/`debugging`/`root-cause` | F-017, unguarded (see above) |
| S2 | Claude manifest `description` replaced, dropping every skill | the surface users see in the plugin listing |
| N36 | Codex manifest `description` + `interface.longDescription` replaced | same, on the Codex side |
| N16 | `skills` key removed outright from the codex manifest | guard is `if sk and …` — absent key skips the check entirely, so Codex loads no skills and the gate is green |
| N12 | `.agents/plugins/marketplace.json` plugin `name` → `superbz` | the Codex local marketplace is only *parsed*; its name is never compared to anything, so the four-way agreement of F-013 has a fifth manifest outside it |
| N26 | `.agents/plugins/marketplace.json` `source.path` → `./plugins/nope` | install would break |
| N42 | `.claude-plugin/marketplace.json` `source` → `./plugins/gone` | install would break |
| N18 | tab-indented continuation line in agent frontmatter | **invalid YAML** (`ScannerError`) — F-011's class |
| N19 | `color: *undefined_anchor` in agent frontmatter | **invalid YAML** (`ComposerError`) — F-011's class |
| N14 | add skill dir `bug/` with valid `SKILL.md` + README, document it nowhere | the three README/marketplace checks are `in`-substring tests; `"superb:bug"` is found *inside* the existing `superb:bug-fix`, so an undocumented skill ships green. Any new name that is a substring of an existing mention is invisible to the gate |
| N15 | append `/home/wp3/audio-chat-app … HIPAA` to `skills/craft/ui/server.py` | the leak scanner filters `p.suffix in {".md", ".json"}`; every `.py`, `.html`, `.sh` and `.txt` under `plugins/superb/` is unscanned, and `craft/ui/` is ~10 such files |
| N22 | skill README replaced with 200 literal `x` | the check is `len(strip()) < 80` — length only, no content |
| N28 | stray `plugins/evil/` directory added | `plugin_dirs` is only ever tested with `cn in plugin_dirs`; anything else under `plugins/` is unvalidated. (It is also read from disk, so an *ignored* directory counts — a leftover `plugins/superbq/` from an earlier mutant showed up in a later run's diagnostic) |
| N33 | delete `.github/workflows/checks.yml` | F-014's fix is not self-guarding |
| N35 | `git mv tools/test-craftui.sh tools/test-craft-ui.sh` | workflow now calls a missing script; gate stays green |
| N23 | duplicate frontmatter key with an identical value | low — PyYAML tolerates duplicates too |
| N39 | agent `model: sonnet` → `model: gpt-9` | low — no vocabulary check on frontmatter values |
| N13 | CRLF line endings across the frontmatter block | benign; `.strip()` absorbs the `\r`. Recorded for completeness |

## Mutants that fail, but not cleanly

| Mutant | Behaviour |
| --- | --- |
| **N10** — non-UTF8 byte (`\xe9`) in `skills/bug-fix/README.md` | exit 1, but via an **uncaught `UnicodeDecodeError` traceback** with no `FAIL` line and no `check-plugin: FAIL` banner. CI goes red for the wrong-looking reason. `path.read_text()` in `frontmatter()` and the README reads have no `errors=` handling; only the leak scanner passes `errors="ignore"` |
| **N21** — `plugins/superb/skills/` deleted | two `FAIL` lines then an uncaught `FileNotFoundError` on `(ROOT/"plugins/superb/skills").iterdir()`; the run aborts before the agent and leak sections |

## False positives

| Input | Gate |
| --- | --- |
| `name: "bug-fix"` (valid YAML, quoted scalar) | **FAIL** — `frontmatter name '"bug-fix"' != directory` |
| `name: bug-fix # comment` (valid YAML) | **FAIL** — same shape |

A contributor writing ordinary, valid YAML can be failed by the gate.

## CI and README verification

- `.github/workflows/checks.yml` — **valid YAML** (PyYAML 6.x, clean load), tracked,
  two jobs, both `actions/checkout@v4`.
- Referenced scripts: `./tools/check-plugin.sh` and `./tools/test-craftui.sh` —
  both **exist**, both **`100755` in the git index**, so a fresh checkout can execute
  them. `check-plugin.sh` is a 3-line `exec python3 …/check-plugin.py "$@"` shim.
  `test-craftui.sh` is `set -euo pipefail`, runs `python3 -m unittest discover` then
  `tests/smoke.sh`.
- **README claim — overstated.** `README.md:222-223`: *"The check is mutation-tested:
  fifteen deliberate breakages, all caught."* There is **no mutation-test harness in
  the repo** — no committed mutant list, no runner, nothing CI re-executes. The claim
  is a one-time manual assertion the tree cannot substantiate, and this re-review
  found 18 surviving mutants (13 of real consequence) drawn from the same classes.
  Recommend rewording to name the classes actually covered, or committing the harness.
- **README claim — contradicted by the gate.** `README.md:238-249`: *"Drop it in and
  it is namespaced automatically — no manifest edit is needed for the skill itself."*
  The gate requires the new skill to appear in the root README, the plugin README and
  the marketplace entry description before it will pass. The paragraph does go on to
  say so; the opening sentence reads the other way.
- **README claim — unenforced.** Same paragraph: *"mention the skill in their
  descriptions"* (both plugin manifests) — S2 and N36 prove nothing checks this.

## Tree state

`git status --porcelain` at the end shows only the pre-existing untracked
`docs/superpowers/runs/2026-08-31-bug-fix-into-superb/`. No tracked file modified.
