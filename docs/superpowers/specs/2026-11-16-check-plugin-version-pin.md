# Bug: check-plugin pins the release to 0.16.0

## Symptom

`./tools/check-plugin.sh` fails on `main`, so the CI job "plugin structure"
has been red since the 0.17.0 release:

```
FAIL  claude manifest must identify the release as version 0.16.0
FAIL  codex manifest must identify the release as version 0.16.0
```

`./tools/check-plugin-mutants.sh`, the last step of the same job, also fails:
its baseline ("unmutated copy must PASS") runs the same gate and exits 1.

- Reproduction: run either script from the repository root.
- Last known good: `9c44817` (PR #7). First failing: `c95ba36` (PR #8, 0.17.0).

## Root cause

`tools/check-plugin.py:458-460`, in "pipeline v2 release structure", requires
both manifests to equal a hard-coded literal:

```python
for label in ("claude", "codex"):
    if label in manifests and manifests[label].get("version") != "0.16.0":
        bad(f"{label} manifest must identify the release as version 0.16.0")
```

The gate's literal was introduced as `0.14.0` in `1f7ef45` ("test(pipeline):
validate v2 release structure"), the mutant's `0.14.0` anchor in `6ac66ab`, and
both were hand-edited on each
release (`644cfb8` to 0.15.0, `fbb8b03` to 0.16.0). Releases 0.17.0
(`e24c68d`), 0.17.1 (`ae6eee2`) and 0.18.0 (`43bf0c5`) bumped only the
manifests, so the literal went stale.

`tools/check-plugin-mutants.sh:158` carries the same literal: the mutant "one
manifest reverts to 0.13.0" asserts `version == '0.16.0'` as its baseline
anchor. Once the gate passes again, that assert reports the mutant as a NO-OP,
and any NO-OP fails the harness (`tools/check-plugin-mutants.sh:197-203`).

Nothing else references a release number: no fixture, pipeline test, README,
marketplace manifest or CI step.

## What the pin was for

The docstring (`tools/check-plugin.py:6`) scopes the gate to "the small
Pipeline v2 inventory/version/CI contract": the manifests had to identify the
Pipeline v2 release. That was a one-time baseline, not a property that should
survive version bumps. The property that should survive is that both manifests
carry a version and agree, which `tools/check-plugin.py:158-166` already
enforces ("version drift or missing").

## Fix direction

1. Delete the pin loop at `tools/check-plugin.py:458-460`. The drift check
   keeps covering a missing or mismatched version.
2. Make the mutant at `tools/check-plugin-mutants.sh:158` release-agnostic:
   anchor on "the Claude manifest has a version other than 0.13.0" instead of
   "== 0.16.0". Reverting one manifest to 0.13.0 stays killed by the drift
   check.
3. Regression test: a "release bump" step in `tools/check-plugin-mutants.sh`
   that copies the repository, sets both manifests to a version no release has
   used, and requires `check-plugin.sh` to PASS. It fails while any release
   number is pinned, and passes once none is. The harness then runs every
   mutant on that bumped copy, so a mutant anchored on a release number is
   reported as a NO-OP.
