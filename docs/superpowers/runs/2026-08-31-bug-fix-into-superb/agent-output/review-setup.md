# Adversarial review — `superb:setup` (commit 75526d7)

Method: stubbed `claude` on `PATH` plus the real binary, run against
`plugins/superb/skills/setup/check-deps.sh`. Every claim below was reproduced,
not inferred from the diff. Working tree left untouched (all probes ran in a
scratchpad; the two honesty checks ran on throwaway `tar` copies).

Baseline, real machine, from the skill directory:

```
HARNESS claude
REQUIRED superpowers OK 6.3.0
OPTIONAL python3 OK 3.11.2
OPTIONAL git-repo OK main
EXIT=0
```

Real `claude plugin list` format (4 lines per plugin, blank-separated):

```
  ❯ superpowers@claude-plugins-official
    Version: 6.3.0
    Scope: user
    Status: ✔ enabled
```

---

## 1. CRITICAL — any failure of `claude plugin list` is reported as "not installed"

`check-deps.sh:23` swallows stderr and ignores the exit status:

```sh
LIST=$(claude plugin list 2>/dev/null)
```

An empty `$LIST` falls through to the `else` at line 33 and prints
`REQUIRED superpowers MISSING not-installed` plus install ACTIONs. There is no
state that distinguishes "the CLI could not answer" from "the plugin is absent".

Reproduced with the **real** `claude` binary, no stubs, by running from a
deleted working directory (the CLI fails to start):

```
$ mkdir -p /tmp/gone; cd /tmp/gone && rmdir /tmp/gone; bash check-deps.sh
shell-init: error retrieving current directory: getcwd: ...
HARNESS claude
REQUIRED superpowers MISSING not-installed
MARKET claude-plugins-official MISSING
ACTION claude plugin marketplace add anthropics/claude-plugins-official
ACTION claude plugin install superpowers@claude-plugins-official
EXIT=1
```

superpowers 6.3.0 **is installed and enabled** on this machine. Reproduced again
with a stub returning rc=1 and empty stdout — identical output.

Consequence per `SKILL.md:33` ("Run the `ACTION` lines in the order they were
printed"): the agent adds a marketplace and reinstalls a plugin that was already
present, on the basis of a transient CLI failure. `MARKET ... MISSING` is
produced by the same blind pattern (line 34), so a network blip or an auth
prompt yields a full spurious install sequence.

## 2. CRITICAL — exits 0 while a REQUIRED dependency is unverified

The script's own contract (`check-deps.sh:5-6`) and `SKILL.md:18` both say it
"exits non-zero when a required dependency is missing". The Codex/unknown branch
at `check-deps.sh:45-49` never sets `MISSING=1`:

```
$ env -i PATH=<no claude, no codex> bash check-deps.sh
HARNESS unknown
REQUIRED superpowers UNKNOWN cannot-check-on-unknown
ACTION manual: open /plugins, search superpowers, install
EXIT=0
```

Same with codex-only on `PATH` (`EXIT=0`). Anything gating on the exit status —
CI, a wrapper, an agent told the exit code means "satisfied" — concludes the
dependencies are in place when nothing was checked at all. `UNKNOWN` is the one
state where the exit code is actively misleading, and it is the default state on
every harness that is not Claude Code.

## 3. MAJOR — a second plugin matching `superpowers@` poisons both Version and Status

`check-deps.sh:26-27`:

```sh
VER=$(printf '%s' "$LIST" | grep -A2 "superpowers@" | sed -n 's/ *Version: *//p' | head -1)
if printf '%s' "$LIST" | grep -A3 "superpowers@" | grep -q "disabled"; then
```

`grep -A` emits **every** matching block. The `disabled` test is an OR across all
of them and `head -1` takes whichever sorts first — neither is scoped to the
plugin being reported. Reproduced with a stale fork installed alongside the real
one (both ids literally contain `superpowers@`, both are legal installs from two
marketplaces):

fixture
```
  ❯ superpowers@abandoned-fork
    Version: 0.0.1
    Scope: user
    Status: ✘ disabled

  ❯ superpowers@claude-plugins-official
    Version: 6.3.0
    Scope: user
    Status: ✔ enabled
```

output
```
HARNESS claude
REQUIRED superpowers DISABLED 0.0.1
ACTION claude plugin enable superpowers
EXIT=1
```

Both fields are wrong. Worse, the ACTION cannot fix it: the plugin the user
cares about is already enabled, so `claude plugin enable superpowers` is a no-op
(and ambiguous — `claude plugin enable --help` confirms it takes a bare name and
a `--scope`, with no way to disambiguate two marketplaces). `SKILL.md:45` then
mandates a re-run, which reports `DISABLED` again. The skill has no exit from
this loop and no instruction covering "the ACTION ran and the state did not
change".

Note the *ordering* attack (`-A3` leaking a later plugin's `disabled`) does
**not** fire on the current 4-line block format — I tried it; `-A3` stops
exactly at `Status:`. That is luck, not design: the window is hard-coded to one
output layout, and the real machine happens to list `telegram@... ✘ disabled`
immediately after superpowers, one blank line outside the window.

## 4. MAJOR — the scraping is unnecessary; `claude plugin list --json` exists

```
$ claude plugin list --help
Options:
  --available  Include available plugins from marketplaces (requires --json)
  --json       Output as JSON

$ claude plugin list --json
[ { "id": "superpowers@claude-plugins-official", "version": "6.3.0",
    "scope": "user", "enabled": true, "installPath": "...", ... }, ... ]
```

`id`, `version` and a boolean `enabled` are exactly the three facts the script
scrapes out of prose. A `--json` parse keyed on `id == "superpowers@..."` (or
`id.split("@")[0] == "superpowers"`) removes findings 3 and 7 entirely and makes
the check immune to a future change in the human-readable layout. The
human-readable path is the fallback, not the primary.

## 5. MAJOR — `OPTIONAL git-repo` reports the plugin's own directory, never the user's project

`check-deps.sh:59-60` asks `git rev-parse` about the **current working
directory**, and `SKILL.md:17` mandates that directory: *"Run `./check-deps.sh`
from this skill's directory first, always."* The skill's directory is inside the
plugin installation, not the user's project, so the answer is structurally
incapable of being about the thing the line claims to measure — whether
`superb:pipeline` can cut worktrees for the work at hand.

Both error directions are reachable on this machine:

```
$ ls -d ~/.claude/plugins/marketplaces/kardebadas-claude-plugin/.git   # exists
  -> running from there reports: OPTIONAL git-repo OK <plugin repo branch>

$ cd ~/.claude/plugins/cache/kardebadas-claude-plugin/superb && git rev-parse --abbrev-ref HEAD
  fatal: not a git repository
  -> running from there reports: OPTIONAL git-repo MISSING  (even inside a repo project)
```

False `OK` is the damaging one: `superb:pipeline` is told worktrees are
available when the user's directory is not a repo. The check needs an explicit
project directory argument, not `$PWD`.

## 6. MAJOR — `HARNESS unknown` has no instructions, and gets Codex-only advice

`SKILL.md` has exactly two branches: *"On Claude Code — install it"* (line 31)
and *"On Codex — say what you cannot do"* (line 49). `check-deps.sh:45` routes
**everything that is not Claude Code** into the Codex branch, so an unknown
harness prints (verified, case 4b above):

```
REQUIRED superpowers UNKNOWN cannot-check-on-unknown
ACTION manual: open /plugins, search superpowers, install
```

Two problems. The agent is handed `cannot-check-on-unknown` with no section
telling it what to do, and the most likely reading — the Codex section, because
it is the only non-Claude one — makes it tell the user to open Codex's
`/plugins` picker on a harness that may have neither. And `SKILL.md:26`
documents `ACTION` as *"the command that would fix the line above it"*, but
`manual: open /plugins, search superpowers, install` is prose, not a command; an
agent following `SKILL.md:33` literally would try to execute it.

`SKILL.md:23` does list `UNKNOWN` in the output grammar, so the state is
acknowledged — it just has no handler.

On `argument-hint: "[check]"`: the no-argument case *is* specified, at
`SKILL.md:29` — *"If `check` was passed as the argument, report and stop.
Otherwise continue."* No finding, but note the skill never references
`$ARGUMENTS` or any other mechanism for reading the argument, and no other
`superb` skill establishes that convention.

## 7. MINOR — a missing `Status:` line is reported as OK (fail-open)

```
fixture: superpowers@x with Version: but no Status: line
output:  REQUIRED superpowers OK 6.3.0     EXIT=0
```

The disabled test is a positive match for the string `disabled`; absence of the
field is indistinguishable from `enabled`. Every unparseable variant of the
block defaults to "fine". A blank `Version:` value likewise yields
`REQUIRED superpowers OK unknown` rather than flagging that the output was not
understood. Fail-open is the wrong default for the one dependency without which
two of three skills do not run.

## 8. MINOR — no timeout, and a partial report on hang

```
$ stub: claude() { sleep 300; }
$ timeout 6 bash check-deps.sh
HARNESS claude
(exit 124 — still hanging)
```

`SKILL.md:17` makes this the first thing the skill does, so a `claude plugin
list` that blocks (auth prompt, lock contention, a nested CLI invocation) hangs
the skill after emitting one line of a report the agent is instructed to read.
`timeout 20 claude plugin list` would bound it, and a timeout is precisely the
`UNKNOWN` case finding 1 lacks.

## 9. MINOR — dead code at line 24, and its pattern is wrong anyway

```sh
if ! printf '%s' "$LIST" | grep -q "^Configured\|superpowers@"; then :; fi
```

Verified dead: deleting the line leaves output and exit status byte-identical
across all three fixtures (present / two-match / empty). Under `set -uo
pipefail` (line 12, note no `-e`) it cannot affect control flow — the body is
`:`. It hides nothing, but it advertises a sanity check on the CLI's output that
the script does not perform, which is the check finding 1 needs.

It is also matching the wrong header: `^Configured` is the first line of
`claude plugin marketplace list` ("Configured marketplaces:"). `claude plugin
list` prints "Installed plugins:". So the guard, had it ever been wired up,
would have accepted an empty plugin list as valid output.

## 10. Honesty claims — both verified TRUE

The commit message claims "34 mutants, zero survivors" and a gate that catches a
lost `+x`. Both re-run from scratch rather than trusted.

**Mutants** — `./tools/check-plugin-mutants.sh`, full log, 40 lines:

```
baseline (unmutated copy must PASS):
  ok    clean copy passes
...
  killed    skill script loses +x          <- line 13, the new mutant
...
killed=34 survived=0
check-plugin-mutants: PASS   (exit 0)
```

**Gate** — verified independently on a throwaway `tar` copy, not via the mutant
harness:

```
$ W=$(mktemp -d); tar -C <repo> --exclude=.git -cf - . | tar -C $W -xf -
$ cd $W && ./tools/check-plugin.sh   -> PASS
$ chmod -x $W/plugins/superb/skills/setup/check-deps.sh
$ cd $W && ./tools/check-plugin.sh
  FAIL  setup: plugins/superb/skills/setup/check-deps.sh is not executable — the skill cannot run it
check-plugin: FAIL
exit=1
```

Both claims hold. One observation on scope: `check-plugin.py:155` uses
`d.rglob("*.sh")`, so it requires `+x` on **every** `.sh` under a skill,
including `plugins/superb/skills/craft/ui/tests/smoke.sh` (currently `0755`, so
the gate passes). A sourced helper or a fixture shell script added later would
be failed by the gate for lacking an execute bit it does not need. Not a defect
today; a constraint worth knowing.

---

## Tree state

All probes ran under the session scratchpad and on `mktemp -d` copies. The two
honesty checks used `tar` copies; `check-plugin-mutants.sh` documents that it
never writes to the working tree, and it did not. Only this review file was
added, under the untracked run directory.
