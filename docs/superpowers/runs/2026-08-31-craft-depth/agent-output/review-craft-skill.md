# Adversarial review — `superb:craft` depth changes (`feat/craft-depth`, 7 commits)

Reviewed `git diff main..HEAD`. Everything below was executed, not reasoned about.
Fixtures were built under the session scratchpad; the repo tree is unmodified.

---

## F1 — CRITICAL — the traceability predicate is dead code for every real session

`check-brief.py:68`

```python
if q.get("importance") not in ("required", "important"):
    continue
```

`ui/schema.py:9` is the authority on what a round file may contain:

```python
IMPORTANCES = ("REQUIRED", "IMPORTANT", "PREFERENCE", "OPTIONAL")
```

and `schema.py:153` rejects any other spelling. `SKILL.md:345` documents the same
uppercase set. So every question in every round file the server will accept fails
`check-brief.py`'s lowercase membership test and is `continue`d past. The loop body
— the entire "every REQUIRED/IMPORTANT question resolves to exactly one place in
the brief" check — never runs.

**Reproduction.** A schema-valid round whose two REQUIRED/IMPORTANT question ids
appear *nowhere* in `CRAFT.md`:

```json
{"round":1,"questions":[
 {"id":"Q1","importance":"REQUIRED","title":"Which auth provider?","type":"text"},
 {"id":"Q2","importance":"IMPORTANT","title":"Which host?","type":"text"}]}
```

```
$ cd plugins/superb/skills/craft && ./check-brief.sh <proj>
PASS structure
PASS nothing-open
PASS traceability        <-- Q1 and Q2 are in no section of the brief
PASS concreteness

check-brief: PASS
exit=0
```

Confirmed the round is genuinely valid, not skipped for another reason:

```
$ python3 -c "import json,schema; print(schema.validate_round(json.load(open(...)),1))"
[]
```

The same brief with `"importance": "required"` (lowercase — a shape the server
would refuse) correctly fails. The predicate only fires on files the system cannot
produce.

**Impact.** `SKILL.md:439-446` makes exit 0 half of what earns `CRAFT STATUS:
VISION CLEAR`. One of the four predicates backing that is inert.

---

## F2 — CRITICAL — the bundled agent's output shape cannot be merged into a round

`agents/architecture-discovery.md:28-42` specifies the return format:

```json
{ "id": "tech-db-engine", "importance": "required",
  "options": ["PostgreSQL", "MySQL", "SQLite", "MongoDB"] }
```
> `importance` is `required`, `important` or `nice`.

Two independent violations of the round-file schema:

| Agent emits | Round-file requires | Enforced at |
| --- | --- | --- |
| `"importance": "required"` (lowercase) | `REQUIRED`/`IMPORTANT`/`PREFERENCE`/`OPTIONAL` | `schema.py:153`, `SKILL.md:345` |
| `"importance": "nice"` | no such level exists | `schema.py:9` |
| `"options": ["PostgreSQL", ...]` (strings) | list of **objects** each with a non-blank string `value` | `schema.py:172-176`, `SKILL.md:348` |

`schema.py:173`:
```python
if not isinstance(option, dict) or not isinstance(option.get("value"), str):
    errors.append("{}.options[{}]: needs a string value".format(where, j))
```

`SKILL.md:229-230` asserts the opposite of what the agent file says:

> It returns candidate questions **in the round-file shape, ready to merge** with
> the ones you wrote.

An agent that takes that sentence literally writes a round the server refuses
outright (`SKILL.md:366`: *"A round that breaks any of this is not served: I get an
error in the browser instead of questions"*). This is the first round of the
session, so the failure lands before the user has answered anything.

Secondary: the agent file gives no `delegable` guidance while emitting `required`
questions — see F8.

---

## F3 — CRITICAL — `--timeout 600` collides with the harness's own Bash timeout

`SKILL.md:250`:
```sh
python3 "$SKILL/ui/craftui.py" wait --project-dir . --round NNN --timeout 600
```

The flag itself is fine. Verified against the parser:

```
$ python3 -c "import craftui; print(craftui._timeout_seconds('600'))"
600.0
$ python3 craftui.py wait --project-dir <proj> --round 1 --timeout 0.01
TIMEOUT round=1
exit=2
```

`--timeout` exists (`craftui.py:1376`, default 900.0), `_timeout_seconds` →
`_positive_duration` (`craftui.py:1217`) accepts any finite positive float, and
600 is legal. Exit 2 / `TIMEOUT` behaves as `SKILL.md:378` documents.

**The problem is the value, against the tool that runs it.** Claude Code's Bash
tool is documented as *"timeout is in milliseconds: default 120000, max 600000."*

* At the **default** 120 s, a 600 s `wait` is killed at 120 s and *moved to the
  background* — which is precisely the failure commit `2095b52` ("wait inside the
  turn so the round loop cannot park") exists to remove. The skill never tells the
  agent to raise the tool timeout.
* Even at the **maximum** 600 000 ms the margin is zero. `cmd_wait` checks its
  deadline *after* a `read_answers` and sleeps `POLL_S = 0.25` (`craftui.py:861`)
  between passes, so it returns at `deadline + up to 0.25 s`, on top of Python
  interpreter startup. The wait can outlive the tool call that started it.

This was reproduced incidentally during this review: a foreground Bash call in
this very session exceeded 120 s and was reported as *"moved to the background
(ID: b3itp6e2b)"*. That is the exact mechanism.

**Fix direction:** pick a bound with headroom (e.g. `--timeout 240`) and state the
harness tool-timeout requirement explicitly, or the change is a no-op on the
default configuration.

---

## F4 — MAJOR — the 600 s heartbeat's stated purpose is unreachable by construction

`SKILL.md:251` — *"Do not end your turn on it"*, reinforced at `:265`:

> **Waiting is executing, not stopping.** A wait is a tool call; your turn has not
> ended and no question is owed.

`SKILL.md:268-270` then states what the heartbeat is *for*:

> My terminal input is mine and stays mine, so surface every ten minutes, **read
> anything I typed**, fold it in like any other answer, and re-arm.

These cannot both hold. Terminal input the user types is delivered to the agent at
a turn boundary. An agent that never ends its turn never receives it. Surfacing
from `wait` inside the same turn returns control to the model, not the user, so
there is nothing new to read.

The feature `SKILL.md:151-155` sells in the opening message — *"the terminal stays
mine while I answer… telling you here is how"* — is therefore inoperative for the
whole of the round loop. Note the loop as written has **no turn boundary at all**:
`:271` says write the next round "in the same turn", `:286` says re-arm TIMEOUT "in
the same turn", and nothing anywhere ends the turn until the session ends. Up to
12 rounds × 600 s of blocking waits are specified to occur inside one turn.

---

## F5 — MAJOR — `Not applicable — ` whitelists an entire section's vagueness

`check-brief.py:13,41`:

```python
NA = re.compile(r"^Not applicable — .+", re.M)
...
if VAGUE.search(sec[h]) and not NA.search(sec[h]):
```

`NA.search` runs against the **whole section body**, not the offending line. One
`Not applicable — …` line anywhere under a heading suppresses every `TBD`, `TODO`
and `as appropriate` in it.

**Reproduction** (fixture A3) — `## Technical Direction` reduced to:

```
Not applicable — no backend at all.
- Database: TBD
- Hosting: TODO
- Auth: as appropriate
```

```
check-brief: PASS
exit=0
```

Three vague axes smuggled past the structure predicate by one escape-hatch line.
The escape is also dash-sensitive in a way nothing documents: `Not applicable - `
(hyphen) and `Not applicable – ` (en dash) both **fail**; only U+2014 em dash
works. Fixtures A6a/A6b/A6c confirm all three.

---

## F6 — MAJOR — four more `concreteness` / `structure` holes, each reproduced

| # | Fixture | Brief | check-brief says | Correct |
| - | ------- | ----- | ---------------- | ------- |
| a | A7 | `## Explicit Non-Goals` → `- No mobile app, no desktop app, etc.` | **PASS** exit 0 | fail |
| b | A7b | Core Feature ends `…uploads PDFs, DOCX, images, etc.` | **PASS** exit 0 | fail |
| c | A4 | `- Sync from https://example.com/feed on a schedule that we will tune` | **PASS** exit 0 | fail |
| d | A5 | `## Technical Direction` → `- Database:` | **PASS** exit 0 | fail |
| e | A12 | `## Core Features` → prose `We will support uploading files.`, zero bullets | **PASS** exit 0 | fail |
| f | A10 | a literal `## Core Features` inside a ``` fence, after a complete brief | **FAIL** exit 1 | pass |
| g | A2 | complete brief + a trailing empty duplicate `## Core Features` | **FAIL** exit 1 | pass |

**(a)/(b) — `etc.` is undetectable in prose.** `check-brief.py:12`:
```python
VAGUE = re.compile(r"\b(TBD|TODO|etc\.|as appropriate)\b", re.I)
```
`\b` after `\.` requires a word character to follow the period. Probed directly:

```
'- Reports, exports, etc.'   -> False
'- Reports etc. and more'    -> False
'- foo etc.foo'              -> True     # the only shape that matches
'- TBD'                      -> True
```

The most common vagueness marker in the list matches only when misspelled.

**(c) — a colon inside a URL satisfies the acceptance-sentence test.**
`check-brief.py:83`: `if ":" not in b or len(b.split(":", 1)[1].split()) < 5`.
For the A4 bullet, `b.split(":",1)[1]` is `//example.com/feed on a schedule that we
will tune` — 9 words. The predicate is satisfied by `https:`.

**(d) — a colon with no value passes.** `check-brief.py:91`:
`if line.strip().startswith("- ") and ":" not in line`. `- Database:` contains a
colon, so the axis is judged "chosen or deferred" while holding nothing. This is
exactly the state `SKILL.md:1003-1006` says must be distinguishable: *"silence and
'no preference' are different states downstream."*

**(e) — an empty bullet list vacuously passes.** `bullets()` returns `[]` for
prose, and the `for` loop over `[]` never fails. Only `Explicit Non-Goals` has an
explicit non-empty guard (`check-brief.py:88`). `Core Features` and `Domain
Behaviour` do not.

**(f)/(g) — `sections()` is a naive line scanner.** `check-brief.py:23-32` treats
any line matching `^##\s+` as a heading, including inside fenced code, and
`out[cur] = []` **resets** on a repeat, so the *last* occurrence wins. A complete
brief with a trailing empty duplicate heading fails as "empty heading"; a brief
whose first `## Core Features` is `- TBD: …` and whose second is clean passes
(A2b happens to fail here only because the *last* copy is the one inspected —
reverse the order and the vague copy is the one that survives).

Neutral result worth recording: **heading order does not matter** (A1, reverse
order → exit 0), because membership is dict-based. That is correct behaviour, not
a bug, but no test covered it.

---

## F7 — MAJOR — `text.count(qid)` is a substring count, so `Q1` collides with `Q10`

`check-brief.py:71-73`:

```python
hits = text.count(qid)
if hits == 0: return fail("traceability", "%s resolves to nothing" % qid)
if hits > 1:  return fail("traceability", "%s appears %d times" % (qid, hits))
```

**Reproduction** (fixture A9) — a *correct* brief citing each question exactly
once:

```
| DEC-001 | Postgres (Q1) | User answer |
| DEC-002 | Fly.io (Q10)  | User answer |
```
with a round declaring both `Q1` and `Q10`:
```
FAIL traceability — Q1 appears 2 times
exit=1
```

Any two-digit question id makes every matching one-digit prefix unresolvable. Ids
like `Q1`/`Q10`/`Q11` are the obvious sequential naming; the agent file's own
`"tech-db-engine"` style happens to dodge it, which is why F1 masked this in
practice — with F1 fixed, F7 fires immediately.

---

## F8 — MAJOR — `delegable` defaults `true` in the UI, `false` only in prose

The diff changed `SKILL.md:351`:

> `delegable` — optional boolean, **default true — except on a `required`
> question, where it defaults to `false`.**

and added `SKILL.md:329`:

> **`delegable` defaults to `false` on a REQUIRED question.**

Nothing implements this. `ui/app.html:227` is the only consumer:

```js
if (q.delegable !== false) {
  card.append(el("button", { class: "delegate", ... text: "you decide" }));
```

No importance is consulted. `ui/schema.py` never mentions `delegable` at all
(`grep -rn delegable plugins/` returns only `app.html:227`, `SKILL.md:329,351`, and
`ui/tests/test_server.py:3461-3480`). The existing test is explicit about the old
contract and was **not updated by this diff**:

`ui/tests/test_server.py:3467-3480`
> `allow_other` is opt-in and `delegable` is opt-out, and nothing pinned either
> direction. An agent that omits `delegable` gets "you decide" …
> `# delegable defaults to true: the button is there without the key.`

So an agent that follows `SKILL.md:329` — reading it as a statement about the
system's default and therefore omitting the key — ships every REQUIRED question
with a *you decide* button, which the same paragraph calls "a scope reduction". The
sentence must either be rewritten as an instruction ("set `delegable: false`
explicitly on every REQUIRED question") or implemented in `app.html`/`schema.py`,
with `test_server.py:3467` amended.

---

## F9 — MAJOR — "Four conditions, and nothing else" is neither exhaustive nor exclusive

`SKILL.md:275-293`.

**A fifth condition, two paragraphs later.** `SKILL.md:292` — *"A hard cap of 12
rounds exists as a bug detector"* — is a termination condition sitting outside a
table that claims to be complete. `TIMEOUT` and `NOSERVER` are explicitly carved
out at `:286` and `:288`; the cap is not.

**Nothing counts rounds.** There is no counter in `SKILL.md`, and the server
disagrees outright — `ui/server.py:162-163`:
```python
MIN_ROUND = 1
MAX_ROUND = 999
```
Round 13 is accepted by every layer. Across a resume the ambiguity is total:
`SKILL.md:215` says resume at `round + 1`, so the number on disk carries, but the
skill never says whether the cap counts absolute round numbers or rounds in this
conversation. Resuming a session at round 11 gives the agent no way to know it has
one round left, and nothing tells it to look.

**"Converged" is measured over one round, not the brief.** The signal is *"zero
open REQUIRED and zero IMPORTANT"*, which is `status`'s `open` dict
(`craftui.py` report `"open": dict((level, 0) for level in schema.IMPORTANCES)`).
`schema.py count_open` is scoped to the current round's questions only:

```python
for question in (round_obj or {}).get("questions", []):
    if answer_state(answers.get(question.get("id"))) == "skipped":
        counts[importance] += 1
```

A REQUIRED question skipped in round 3 and not re-asked in round 4 makes round 4
report `open.REQUIRED = 0`, and the agent declares convergence over an unanswered
REQUIRED. The diff *added* the exact warning for the sibling counter
(`SKILL.md:1502-1506`, "`count_answered` folds `delegated` into settled") but did
not add it for `open`, which is the one the termination condition actually reads.

**Two conditions at once, with a documented conflict.** `FINISHED` arriving with
REQUIRED questions still open matches row 1 → *"Final fold, run the merits test in
*Ending*, `stop`."* But `Ending` (`SKILL.md:455-456`) says:

> Whatever it still cannot answer becomes **round N+1**. Those are questions, not
> footnotes on a finished brief.

Round N+1 requires a live server; row 1 has just told the agent to `stop` it, and
`SKILL.md:407-409` says a fresh `serve` mints a new key and permanently 403s the
tab the user is looking at. The skill does not say which wins. It is also the most
likely real ending — `check-brief.py:47` fails `nothing-open` on any `[REQUIRED]`
line, so a FINISHED-with-gaps brief reaches this fork by design.

`FINISHED` can additionally co-occur with row 4 ("no progress"), with no
precedence rule.

---

## F10 — MINOR — `./check-brief.sh <project-dir>` contradicts the file's own cwd rule

`SKILL.md:442`:

> Run `./check-brief.sh <project-dir>` **from this skill's directory.**

`SKILL.md:125-129` establishes the opposite as the operating assumption, and gives
the absolute-path idiom used by every other command in the file:

> Below, `$SKILL` is the directory this file lives in. … **you will be running from
> my project directory, not from the skill's**, and a wrong guess looks exactly
> like the UI being unavailable.

Every other invocation is `python3 "$SKILL/ui/craftui.py" …`. This one is the only
`./`-relative command in the skill, and the required `cd` is never stated.
Executed, all four plausible readings:

```
T1  cd $SKILL && ./check-brief.sh /abs/proj      -> exit 0   check-brief: PASS      (documented form; works)
T2  cd /proj   && ./check-brief.sh .             -> exit 127 No such file or directory
T3  cd $SKILL  && ./check-brief.sh .             -> exit 2   FAIL brief — cannot read CRAFT.md
T4  cd $SKILL  && ./check-brief.sh               -> exit 2   FAIL brief — cannot read CRAFT.md
```

T1 is fine — `check-brief.sh:3` uses `exec python3 "$(dirname "$0")/check-brief.py"
"$@"`, correctly quoted, so a plugin-cache path with spaces is safe, and `+x` is
set on both files (`-rwxr-xr-x`), now guarded by the new mutant in
`tools/check-plugin-mutants.sh:52`.

T3 is the trap. `--project-dir .` is the habit every other command in this skill
trains, and `.` after the required `cd` silently checks the *skill* directory and
reports `cannot read CRAFT.md` — a message that reads as "your brief is missing"
rather than "you passed the wrong directory". `check-brief.py:96` also ignores all
argv beyond `[1]`, so `./check-brief.sh --project-dir .` treats `--project-dir` as
the project root and fails the same misleading way.

Recommend `python3 "$SKILL/check-brief.sh" <abs-project-dir>` for consistency with
the rest of the file.

---

## Additional observations (not scored)

**"Once per session" is undefined across a resume.** `SKILL.md:236` — *"Once per
session, not once per round."* Nothing on disk records that
`superb:architecture-discovery` ran: `.craft/` holds only `round-*.questions.json`
/ `round-*.answers.json`, and `status` reports `round`, `has_draft`,
`total_questions`, `answered`, `open` — no discovery marker. The `Resuming` section
(`SKILL.md:200-221`) never mentions it. Two concrete failures:

* Resume in a new conversation at round 5 → the agent has no record, and
  `:225` ("before round 1") does not obviously forbid it, so it may dispatch again
  — the duplicate the rule exists to prevent.
* A "start fresh" (`:218`, delete `.craft/round-*`) at round 1 → the agent may
  reasonably treat discovery as already done for this conversation and skip it,
  giving round 1 no technical questions at all.

Either add a `.craft/discovery.json` marker or define "session" as "this
conversation" in the text.

**No availability probe for the agent, unlike `bug-fix`.** `SKILL.md:239` says
skip discovery "when it is unavailable", but gives no way to detect that.
`bug-fix/SKILL.md:57` uses a testable predicate — *"`superb:bug-investigator`
appears in your available agent types"* — and `bug-fix/README.md:45` carries a
harness availability table plus a `references/investigator.md` fallback for Codex.
Craft has none of the three. `plugins/superb/.codex-plugin/plugin.json` declares
only `"skills": "./skills/"` and no agents key, so on Codex the agent genuinely
does not exist and the agent must infer that from a failed dispatch.
`architecture-discovery` is also absent from `plugins/superb/README.md` and the
root `README.md`, where `bug-investigator` is documented.

**Stale docstring contradicting the new loop.** `ui/craftui.py:941-943`,
`cmd_wait`'s docstring, still describes the removed contract:

> This is the seam between an agent's turn and a human's attention: the agent
> writes a round, starts this, **and stops.**

Not read at runtime, but it is the first thing anyone maintaining `wait` reads, and
it now says the opposite of `SKILL.md:251`.

**NOSERVER re-arm shortcut drops the URL warning.** The new `SKILL.md:288-290`
says on exit 3, *"If I am plainly present — I just typed — re-`serve` and re-arm"*,
without repeating what `:407-411` establishes: `serve` mints a new key and the
user's open tab 403s forever. Combined with `craftui.py:889` `DEAD_SERVER_STRIKES
= 8` at `POLL_S = 0.25`, a **2-second** liveness blip is enough to return NOSERVER.
Measured:

```
$ python3 craftui.py wait --project-dir <proj> --round 99 --timeout 2
exit=3   wall=1.8s      # NOSERVER fired before the 2s timeout
```

A two-second hiccup can cost the user their live session URL, and the new table row
does not warn about it.

**`README.md` claims the loop "drives its own rounds without prompting"** — true
only under the harness assumptions F3 and F4 break.

---

## Test-suite state

Baseline suite passes and is untouched by these findings:

```
$ python3 -m unittest discover -s plugins/superb/skills/craft/tests -p 'test_*.py'
Ran 8 tests in 0.165s
OK
```

None of the 8 existing cases in `tests/test_check_brief.py` covers: heading order,
duplicate headings, the `Not applicable` escape, `etc.`, colons in URLs, an empty
`Technical Direction` value, a bullet-less section, non-em-dash dashes, id
substring collisions, or an uppercase-`importance` round file. The adversarial
fixtures A1–A12 used above should be added; 9 of the 18 assertions currently give
the wrong verdict.

## Tree state

```
$ git status --porcelain
?? docs/superpowers/plans/2026-08-31-craft-depth.md
?? docs/superpowers/runs/2026-08-31-bug-fix-into-superb/
?? docs/superpowers/runs/2026-08-31-craft-depth/
?? docs/superpowers/specs/2026-08-31-craft-depth-design.md
```

No tracked file modified. All fixtures were written to the session scratchpad; the
only file added under the repo is this report, inside the already-untracked
`docs/superpowers/runs/2026-08-31-craft-depth/` directory.
