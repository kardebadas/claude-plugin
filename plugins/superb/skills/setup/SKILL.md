---
name: setup
description: Use when superb's skills need their dependencies installed or checked — "set up superb", "install the dependencies", "why does pipeline say superpowers is missing", after a fresh plugin install, or on a new machine. Also use when a skill fails complaining that a superpowers sub-skill cannot be found.
argument-hint: "[check]"
---

# Setup

## Overview

Gets `superb`'s dependencies in place, and says plainly what it could not do.

`superb:craft` needs nothing. `superb:pipeline` and `superb:bug-fix` both
compose [superpowers](https://github.com/obra/superpowers) and do not run
without it.

**Run `./check-deps.sh` from this skill's directory first, always.** It reports
one fact per line and exits non-zero when a required dependency is missing, so
you read its output rather than guessing at the state of the machine.

```
HARNESS   claude | codex | unknown
REQUIRED  <name>  OK | MISSING | DISABLED | UNKNOWN   <detail>
OPTIONAL  <name>  OK | MISSING                        <detail>
MARKET    <name>  OK | MISSING
ACTION    <the command that would fix the line above it>
```

If `check` was passed as the argument, report and stop. Otherwise continue.

## On Claude Code — install it

Run the `ACTION` lines in the order they were printed. The order matters: a
marketplace has to exist before a plugin can be installed from it.

```
claude plugin marketplace add anthropics/claude-plugins-official
claude plugin install superpowers@claude-plugins-official
```

**`DISABLED` is not `MISSING`.** An installed-but-disabled plugin looks present
to anything that only checks for the name, and its skills will not load.
`claude plugin enable superpowers` is the fix, and reinstalling is not.

**Then re-run `check-deps.sh` and report its output**, not your expectation of
it. An install that printed no error has not been verified; the second run is
the verification.

## On Codex — say what you cannot do

Codex installs plugins through an interactive picker, so nothing here can run
it. Do not attempt a workaround, and do not write to `~/.codex/config.toml` —
an install writing into a user's config is exactly what superpowers' own porting
guide forbids.

Report the state, then hand over the manual route:

> Open `/plugins`, search for `superpowers`, and select Install Plugin.

`superb:pipeline` and `superb:bug-fix` both degrade rather than break when a
subagent mechanism is absent, so this is a limitation to state, not an error to
resolve.

## Optional, and genuinely optional

| Dependency | Used by | Without it |
| ---------- | ------- | ---------- |
| `python3` | `superb:craft`'s browser UI | Falls back to the `CRAFT.md` questionnaire; nothing is lost but the browser |
| a git repository | `superb:pipeline`'s parallel waves | Waves need worktrees; a non-repo directory runs tasks one at a time |

Report these as information. **Never install a language runtime or initialise a
repository to satisfy them** — both are decisions with consequences well past
this plugin, and neither blocks anything.

## Red flags — STOP

- About to report success without re-running `check-deps.sh` → the second run is
  the only evidence you have.
- About to reinstall a plugin the script called `DISABLED` → enable it.
- About to edit `~/.codex/config.toml`, or any file under a user's config → not
  yours to write.
- About to run `git init` or install a runtime → out of scope, and not asked for.
- About to say "dependencies installed" on Codex → you could not check, let
  alone install. Say that instead.
