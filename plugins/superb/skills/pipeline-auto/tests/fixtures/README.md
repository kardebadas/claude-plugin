# pipeline-auto/v1 state fixtures

`valid-progress.md` is the single fully-populated valid tracker. It is external
truth, not a convenience: it carries every column of every section, so a change
to a header constant in `pipeline_auto_state.py` that drops a column fails the
byte round-trip instead of silently losing a cell on every future write. Edit it
only when the schema genuinely changes, and change the module in the same commit.

Invalid input is built by surgery on these bytes inside the test that needs it,
so each rejection test states exactly which byte made it invalid.

Rejection tests compare the file's bytes before and after the attempted parse or
transition. An invalid or foreign tracker must be byte-identical afterwards: a
read-only stop that rewrites the file into a guessed state is not a stop.

`plugins/superb/skills/pipeline/tests/fixtures/valid-v2-progress.md` and
`legacy-v1-progress.md` are read by the foreign-schema tests and are never
copied here and never modified. They belong to `superb:pipeline`, which this
skill does not interoperate with and never migrates from.
