# Pipeline Auto — Completeness Proposals

<!-- pipeline-auto-completeness/v1 -->

Frozen record of what the stage-11 completeness critic classified
`MISSING-FROM-SPEC`: work the approved spec does not ask for. Nothing here is
ever turned into a task, phase, fix-round finding or quorum. The phase set has
been immutable since stage 06. The user decides each proposal.

A missed requirement is `SPEC-NOT-MET`. That is a finding for the fix loop, and
it does not belong in this file.

## Rules

- One section per proposal, appended. Sections are never edited or removed.
- The heading is `## CP-<number>`, with the **next unused** number: `CP-1` in a
  file with no proposals, otherwise one more than the highest. Write the real
  number. Never write a literal `<n>`.
- `Status` is always `Frozen`. No disposition, whether `deferred`,
  `out-of-scope`, `declined` or `closed`.
- `Classification` copies the critic's word for word.
- The file is read strictly. A heading or status line that is not exactly
  the shape below, a fence other than a column-0 backtick fence, an unclosed
  fence, a multi-line HTML comment, or a section with no status line stops
  the run instead of being skipped.
- Every ID appears in the terminal report. `next_action` becomes
  `complete-with-proposals` only after every other item is finished, including
  any open fix round.

## Section shape

Copy this block for each proposal and fill it in. The example stands for
`CP-1`.

```markdown
## CP-1

- **Statement:** <one sentence: the behaviour or coverage the spec does not ask for>
- **Evidence:** <the critic's text, verbatim>
- **Traces to:** none
- **Status:** Frozen
- **Classification:** MISSING-FROM-SPEC
```
