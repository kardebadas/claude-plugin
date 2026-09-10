# Pipeline v2 macOS volume-identity correction plan

**Scope:** Correct only the remaining backing-volume identity defect in
`_macos_filesystem()` on `feat/pipeline-rebuild-v2`, starting from reviewed
commit `eb5c587b4807c40bb3bcd86a6e892faf0b3a2c28`. Preserve the existing
`df -P` probe, Pipeline v2 architecture, earlier focused corrections,
remediation history, and native-verification limitations. This task is executed
directly with individual Superpowers skills; `superb:pipeline` does not
orchestrate its own correction.

## Verified root cause

The helper parses the containing filesystem and mount from `df -P`, then asks
`diskutil info -plist` for that mount. It correctly cross-checks the reported
mount, filesystem type, and device identifier, but additionally requires the
physical mount path to be a lexical parent of the resolved logical path. Apple
documents that `df` reports the Data volume mounted at
`/System/Volumes/Data` for logical writable paths such as `/etc/...`; those
paths need not be lexical children of that physical mount because macOS maps
them through the System/Data volume arrangement.

## Task — Bind df and diskutil by device identity

**Files:**

- Modify `plugins/superb/skills/pipeline/tests/test_pipeline_state.py`
- Modify `plugins/superb/skills/pipeline/scripts/pipeline_state.py`
- Modify `plugins/superb/skills/pipeline/README.md`
- Modify `plugins/superb/skills/pipeline/references/persistence.md`

**Red:** Add actual-helper tests using realistic `df -P` and `diskutil
info -plist` results. Prove that a logical path backed by the Data volume is
rejected only by the old lexical containment predicate. Retain controls for an
ordinary nested path, a mount with spaces, mismatched device identity, and
malformed/missing/failed probes.

**Green:** Parse the `df` filesystem-source field and require it to identify the
same volume as `diskutil`'s `DeviceIdentifier` while retaining the existing
exact mount-point and filesystem-type validation. Remove only the invalid
lexical-parent requirement. Reject missing, malformed, non-device, or
inconsistent evidence.

**Verification:** Run the focused macOS classifier tests during TDD. Commit only
this plan and the four intended implementation/test/reference files with
explicit staging paths. On that committed state,
run the full Pipeline unit suite, plugin validation, mutation harness,
`py_compile`, and `git diff --check`. Obtain one independent focused review;
reuse exact-state integrated evidence unless the reviewer identifies a reason
to rerun it. Report Linux simulation separately from unavailable native macOS
verification. Do not push, publish, create a PR, or merge.
