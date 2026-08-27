# craft UI — the test that made the Delivery section ship

`superpowers:writing-skills` says no skill change ships without a failing test
first. The craft UI is a skill change: twelve tasks of code that `SKILL.md` had
no idea existed. The test is a subagent given the skill, the path to the CLI,
and a vague product idea, and the assertion is what it does with them.

Three runs, all on "I want something like Spotify but for audiobooks", all in
throwaway directories, each with a fresh subagent and no memory of the others.

---

## RED — the current skill, before the Delivery section

**Given:** `SKILL.md` exactly as it stood at `31ecc88` (no `# 2b. Delivery`
section, no `argument-hint`), the path to `ui/craftui.py` with its four
commands named, the idea, and a working directory.

**Prompt:**

> You have the skill at `<path>/SKILL.md`. There is also a web UI at
> `<path>/ui/craftui.py` (commands: serve, wait, status, stop). Craft a
> product with me: "I want something like Spotify but for audiobooks."
> Work in `<dir>`.

### What it did, verbatim

It read `SKILL.md`. Then it ran exactly one command that touched the project:

```sh
cat > <dir>/CRAFT.md << 'CRAFTEOF'
[... 693 lines ...]
CRAFTEOF
```

It never invoked `craftui.py`. Not `serve`, not `status`, not anything. No
`.craft/` directory was created. Asked why, it said:

> I did not invoke `ui/craftui.py` (serve/wait/status/stop) — nothing in
> `SKILL.md` references a web UI, and per the skill's own workflow the
> first-round deliverable is the `CRAFT.md` questionnaire handed to the user,
> not a running UI.

That is the correct reading of the file it was given. The file was the defect.

### The artifact

`CRAFT.md`, 693 lines, 19,225 bytes. It contains:

* 11 `[REQUIRED]` question headings, plus `[IMPORTANT]`, `[PREFERENCE]` and
  `[OPTIONAL]` ones;
* 34 `**My decision**` blocks, every one of them empty;
* 59 unanswered `- [ ]` checkbox options;
* `## Assumptions`, `## Confirmed Decisions`, `## Delegated Decisions`,
  `## Open Questions` and `## Contradictions` sections.

One question, verbatim, as a sample of the shape:

```md
#### [REQUIRED] Who is this for, specifically?

**Why this matters**

"Users" for an audiobook app splits very differently depending on the
audience — a commuter who wants one book at a time is a different product
from a student who needs bookmarking/notes for textbooks, which is
different again from a parent choosing children's audiobooks.

**My decision**

>
```

**RED, by the first of the two expected failure modes: it ignored the UI
entirely and wrote the questionnaire into `CRAFT.md`.** Twelve tasks of a
working browser front-end sat unreachable a directory away.

---

## GREEN criteria for the Delivery section

1. The agent runs `craftui.py serve` before asking its first question.
2. The agent writes `.craft/round-001.questions.json` containing the round.
3. `CRAFT.md` after round 1 contains NO questionnaire — no `[REQUIRED]`
   headings, no `**My decision**` blocks, no unanswered checkbox lists.

---

## GREEN — the same scenario, with the Delivery section

**Given:** the same prompt, the same idea, a fresh subagent with no memory of
the RED run, and `SKILL.md` carrying `argument-hint: "[ui|file]"` and the new
`# 2b. Delivery — the browser, or the file`.

### What it did, verbatim

Its first line back was `**Mode: browser.**` — the one-line mode declaration
§2b asks for. Then, in order:

```sh
# 1. look at the project and the ui directory
mkdir -p <dir> && ls -la <dir> && ls -la <skill>/ui/

# 2. start the server, BEFORE any question was written
cd <dir> && python3 "<skill>/ui/craftui.py" serve --project-dir . --open

# 3. check what .gitignore covers
cd <dir> && cat .gitignore 2>/dev/null; echo "---"; ls -la

# 4. inspect the repo before asking technical questions (§1)
cd <dir> && git log --oneline -20; git status

# 5. arm the wait, in the background, and end the turn
cd <dir> && python3 "<skill>/ui/craftui.py" wait --project-dir . --round 1
```

It gave the complete URL, query string and key included:

```
http://127.0.0.1:43561/?key=a6e16619c8bef9ecd577ecb1a04bc9e6d011f5ff9f82458ecc1c4919ff7fe199
```

and it did not poll, did not ask anything in chat, and ended its turn with the
`wait` armed.

### Against the three criteria

**1. `serve` before the first question — PASS.** Command 2 of 5. The round file
was not written until after it, and the server-info file on disk predates
`round-001.questions.json` by 39 seconds.

**2. `.craft/round-001.questions.json` containing the round — PASS.** 10,839
bytes, 15 questions. Validated against the real validator rather than by eye:

```
schema.validate_round(obj, 1) -> []
round field: 1
importance: REQUIRED 5, IMPORTANT 7, PREFERENCE 2, OPTIONAL 1
types: single 10, multi 2, longtext 2, text 1
15 of 15 carry a `why`; 1 marked delegable
ledger: all four sections present as lists
```

The first question, as written:

```json
{
  "id": "content-source",
  "importance": "REQUIRED",
  "title": "Where does the audiobook content come from?",
  "why": "This is the single biggest fork in the product. A licensed commercial
          catalogue is a marketplace/streaming-rights business ... Each implies
          a completely different data model, legal posture, and scope.",
  "type": "single",
  "options": [ {"value": "Licensed commercial catalogue — publishers/rightsholders
                          provide the audio, like Audible or Spotify Audiobooks"},
               ... ],
  "allow_other": true
}
```

**3. No questionnaire in `CRAFT.md` — PASS.**

```
grep -c '\[REQUIRED\]'      CRAFT.md -> 0
grep -c '\*\*My decision\*\*' CRAFT.md -> 0
grep -c '^- \[ \]'          CRAFT.md -> 0
```

`CRAFT.md` is 3,464 bytes against RED's 19,225: the `# Crafted Product
Definition` skeleton from *Output of the crafting process*, `## Vision` filled
in with the audiobook-versus-music framing, every other section `*(pending)*`,
and an `## Open Questions` index of round 1's ids grouped by importance. That
index is the section the skill has always required — ids and one-line
summaries, no options, no answer slots, nothing to fill in. It is a pointer at
the round file, not a second copy of it.

It also wrote `.gitignore` containing `.craft/` and said so in one line.

---

## Pressure case — "skip the UI, just ask me in chat, it's faster"

**Given:** a third fresh subagent, the same skill and the same idea. It got as
far as GREEN did — server up, round 1 written, `wait` armed — and was then
told, mid-round:

> Skip the UI, just ask me in chat, it's faster.

### What it did

It moved to chat, and it closed the browser surface on the way out rather than
leaving two open. `.craft/server.log`:

```
craftui: session ended cleanly; the project is free.
```

`CRAFT.md`'s mode line was rewritten in place, and the round file was kept as a
record rather than deleted or copied:

> **Mode:** Chat. Started in browser mode …; switched to chat partway through
> round 1 at the requester's ask ("skip the UI, just ask me in chat, it's
> faster"). The craftui server has been stopped. `.craft/round-001.questions.json`
> still holds the round-1 question set as a record of what was asked; going
> forward, questions and answers happen directly in conversation and get folded
> into this file.

**It did not inline the questionnaire.** Same greps, same answer:

```
[REQUIRED]              0
**My decision**         0
- [ ]                   0
**Possible directions** 0
```

**And it did not split the answers across two surfaces.** There is exactly one
live surface at the end of the turn: the server is stopped, the lock is
released, and the `## Open Questions` index — ids and one-line summaries, no
answer slots — points at questions that are now asked in conversation.

**PASS on both requirements.** It exercised the permitted move (chat) without
either of the two failures.

---

## What shipped against what was tested

The GREEN and pressure runs were given `SKILL.md` at one sentence short of the
committed text. The sentence added afterwards, in *What this changes about what
you write*:

> The page shows me the brief beside the questions and re-reads it every round,
> so I watch it grow as I answer — which is exactly what a questionnaire pasted
> into it would bury.

It restates the reason for a contract both runs already satisfied without it,
and adds no new instruction. Nothing else differs.
