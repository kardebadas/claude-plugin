# setup

Part of the `superb` plugin — invoked as **`superb:setup`**.

Installs and verifies what `superb`'s other skills depend on.

```
> /superb:setup
```

`superb:craft` is self-contained unless its optional browser UI is used.
`superb:pipeline` and `superb:bug-fix` both compose
[superpowers](https://github.com/obra/superpowers) and will not run without it.
Pipeline's standard-library state helper requires Python 3.11+. Craft's
optional browser UI has a separate Python 3.9+ floor and still falls back to
its file questionnaire when Python is unavailable.

## How it works

`check-deps.sh` does the detection and prints one fact per line — harness,
required dependencies, optional ones, and an `ACTION` command for anything that
needs fixing. It exits non-zero when a required dependency is missing, so the
skill reads a report rather than guessing.

An unsatisfied `REQUIRED pipeline-python` line has no `ACTION`. Setup reports
the Python 3.11+ limitation and stops; it never installs or upgrades a runtime.

On **Claude Code** it runs the `ACTION` lines, then re-runs the check, because
an install that printed no error has not been verified.

On **Codex** it cannot: plugins install through an interactive picker. It says
so and hands over the manual route rather than attempting a workaround.

## What it will not do

- **Write to `~/.codex/config.toml`**, or anywhere under a user's config — an
  install writing into user config is what superpowers' own porting guide
  forbids.
- **Install or upgrade a language runtime, or run `git init`.** Those actions
  have consequences past this plugin. Without Python 3.9+, Craft falls back to
  its file questionnaire; without Python 3.11+, Pipeline reports its required
  runtime as unsatisfied and stops.

## The state that catches people

A plugin can be installed **and disabled**. It looks present to anything
checking only for the name, and its skills will not load. The script reports
`DISABLED` separately from `MISSING`, and the fix is `claude plugin enable`, not
a reinstall.
