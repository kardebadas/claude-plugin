# craft UI — design

**Date:** 2026-08-25
**Status:** approved (brainstorming complete, ready for planning)
**Affects:** `plugins/superb/skills/craft/`

---

## Problem

`superb:craft` turns a vague product idea into a decision-rich brief by writing a
tailored questionnaire into `CRAFT.md`, having the user answer it in the file,
then folding the answers back in so the questionnaire shrinks with every pass.

The file is a poor answering surface. Multiple-choice questions are checkbox
lists the user edits by hand. There is no way to see the brief accumulating
while answering it. Contradictions and unconfirmed assumptions are prose the
user scrolls past. Nothing distinguishes *"I did not get to this question"* from
*"I do not care, you decide"* — both look like an empty answer.

The user wants a browser front-end: the agent launches a local web app, posts a
round of questions, watches for replies, folds them in, and posts the next round
— continuing until the vision is clear or the user presses Finish.

## Non-goals

- Not a hosted or multi-user service. One local user, `127.0.0.1`.
- Not a replacement for `CRAFT.md`. The file remains the artifact of record.
- Not a planning or implementation surface. Every strict boundary in
  `craft/SKILL.md` holds unchanged — no phases, tickets, estimates or code.
- No build step, no package manager, no dependency tree.

## Decisions taken during brainstorming

| # | Decision | Rejected alternatives |
|---|----------|----------------------|
| D1 | **JSON rounds on the wire, `CRAFT.md` as the brief.** The agent writes questions as JSON; the UI posts answers as JSON; the agent folds them into `CRAFT.md`, which the UI renders read-only. The server never parses markdown. | A UI that parses `CRAFT.md` directly (needs a strict markdown grammar; a hand-edit that drifts breaks the UI). A UI-owned session store with `CRAFT.md` as a final export (no readable brief mid-session). |
| D2 | **Python 3 stdlib, zero dependencies.** One server file plus one HTML file, `http.server` only. | Node with zero deps (needs node on PATH; python3 is already guaranteed). Node with Express/Vite/React (`node_modules` in a plugin repo, a build step, and permanent dependency upkeep for a tool that renders a form). |
| D3 | **One skill, two front-ends.** `superb:craft` keeps its single body of guidance and gains a `# Delivery` section. `/superb:craft ui` and `/superb:craft file` force either. | A thin second skill delegating to `craft` (cross-skill references quietly stop being followed). A standalone second skill (two copies of 1100+ lines that diverge). |
| D4 | **Autosave per answer, agent wakes on Send.** Every change persists immediately; the agent only runs when the user presses "Send to Claude". | Waking the agent on every answer (page mutates while the user types; expensive). Strict rounds with no autosave (closing the tab loses the round). |
| D5 | **Sidebar layout.** Questions carry the page; the brief and the ledger sit permanently to the right. | Focused single column with the brief folded away (hides the thing that makes the UI worth having). Three-pane with a round-history rail (most to build, tightest on a laptop, for history rarely revisited). |
| D6 | **The UI shows all four extras:** rendered brief, decisions/assumptions/contradictions ledger, per-question "you decide", importance filter. | — |

---

## Architecture

Three pieces. The server is deliberately stupid: it never parses markdown, never
decides anything, never contacts a model. It moves JSON between the agent and
the browser and renders `CRAFT.md` read-only.

```
agent  ──writes questions JSON──▶  .craft/  ──served──▶  browser
agent  ◀──reads answers JSON────   .craft/  ◀──posted──  browser
agent  ──writes brief──────────▶  CRAFT.md ──rendered──▶ browser (read-only)
```

### Shipped files

```
plugins/superb/skills/craft/
  SKILL.md            # + argument-hint, + "# Delivery" section
  README.md
  ui/
    craftui.py        # server + CLI, stdlib only
    app.html          # the entire UI
    tests/
      test_craftui.py # stdlib unittest
      smoke.sh        # end-to-end over real HTTP
```

### Session directory

Created in the user's project, beside `CRAFT.md`:

```
<project>/
  CRAFT.md                       # the brief. Agent owns it. Server only reads it.
  .craft/                        # session state, gitignored
    server-info                  # JSON: port, url, session key, pid
    round-001.questions.json     # agent writes
    round-001.draft.json         # server writes on every change
    round-001.answers.json       # server writes on Send / Finish
    round-002.questions.json
    ...
```

The skill adds `.craft/` to the project's `.gitignore` if it is not already
covered, and says so in one line.

**Round discovery:** the server serves the highest-numbered
`round-NNN.questions.json` present. There is no `push` command — the agent
writing the file *is* the push. One fewer thing to fall out of sync.

---

## Wire format

### `round-NNN.questions.json` — written by the agent

```json
{
  "round": 2,
  "status": "MORE CLARIFICATION NEEDED",
  "project": "music-app",
  "questions": [
    {
      "id": "Q-007",
      "importance": "REQUIRED",
      "area": "Accounts and authentication",
      "title": "How should users authenticate?",
      "why": "Determines onboarding behaviour, account recovery, and which identity infrastructure the application requires.",
      "type": "single",
      "options": [
        { "value": "email", "label": "Email and password", "detail": "Simplest to build. Needs password reset and storage." },
        { "value": "magic", "label": "Magic link", "detail": "No passwords to store. Requires reliable outbound email." }
      ],
      "allow_other": true,
      "delegable": true
    }
  ],
  "ledger": {
    "decisions":      [ { "id": "DEC-014", "title": "Playlist visibility", "summary": "Private by default." } ],
    "assumptions":    [ { "id": "ASSUMPTION-003", "text": "Single user, no sharing.", "needs_confirmation": true } ],
    "contradictions": [ { "id": "CON-002", "text": "Offline-first conflicts with streaming-only catalogue.", "between": ["Q-004", "DEC-009"] } ],
    "delegated":      [ { "id": "DEL-002", "title": "Database technology", "rationale": "No stated preference; downstream agent decides." } ]
  }
}
```

`importance` ∈ `REQUIRED | IMPORTANT | PREFERENCE | OPTIONAL` — the four levels
already defined in `craft/SKILL.md`.

`type` ∈ `single | multi | text | longtext`. Question design rules are unchanged:
free-form where free-form is right, and no false choices invented to make a
question multiple-choice.

Every key except `id`, `importance`, `title` and `type` is optional. `options`
is required for `single` and `multi` and ignored otherwise.

### `round-NNN.answers.json` — written by the server

```json
{
  "round": 2,
  "submitted_at": "2026-08-25T14:31:08Z",
  "finished": false,
  "answers": {
    "Q-007": { "choice": ["email"], "other": null, "note": "email now, passkeys later" },
    "Q-008": { "delegated": true },
    "Q-009": { "skipped": true },
    "Q-010": { "text": "Anyone with the link can view, only the owner can edit." }
  }
}
```

**Four answer states, kept apart deliberately:**

| State | Shape | Meaning to the agent |
|-------|-------|----------------------|
| answered | `choice` / `text` present | Fold into the brief; close the question. |
| delegated | `"delegated": true` | Record as a **Delegated Decision**. Never ask again. |
| skipped | `"skipped": true` | Still open. Ask again next round. |
| absent | key not present | Same as skipped. |

The delegated/skipped split is the point. In the file workflow an empty answer
is ambiguous — *did not care* and *did not get to it* look identical. The "you
decide" button says *record it and stop asking*; silence still means *ask me
again*.

`round-NNN.draft.json` has the same `answers` shape, no `submitted_at`, and is
rewritten on every change. **It is crash insurance, not the submission path** —
it exists so a closed tab loses nothing, and it repopulates the form on reload.
Send carries the complete answer set in the POST body, and the server writes
`answers.json` from that body, atomically (temp file in the same directory, then
`os.replace`). The draft is left in place afterwards, untouched.

Writing the answers from the POST rather than promoting the draft keeps one
failure mode out of the design: a draft that is stale or partially written when
Send arrives can never become the submitted round.

---

## CLI surface

Four commands. Invoked by the agent as `python3 <skill>/ui/craftui.py <cmd>`.

### `serve`

```
craftui.py serve [--project-dir DIR] [--open] [--port N] [--idle-timeout-minutes N]
```

Backgrounds itself, writes `.craft/server-info`, prints that JSON to stdout:

```json
{ "type": "server-started", "port": 51022, "pid": 44913,
  "url": "http://localhost:51022/?key=9f2c…" }
```

Defaults: `--project-dir .`, idle timeout 240 minutes. `--open` launches the
user's browser.

**Port selection:** if `.craft/server-info` records a port and that port is
free, reuse it; otherwise take an ephemeral one. Reuse is what lets a restarted
server be picked up by the tab the user already has open, so a crash or an idle
exit costs a reconnect rather than a new URL.

### `wait`

```
craftui.py wait --round N [--timeout SECONDS]
```

Blocks until one of three things happens, prints one line, exits:

| Outcome | stdout | exit |
|---------|--------|------|
| user pressed Send | `SUBMITTED round=2 answers=.craft/round-002.answers.json` | 0 |
| user pressed Finish | `FINISHED round=2 answers=.craft/round-002.answers.json` | 0 |
| nothing for `--timeout` | `TIMEOUT round=2` | 2 |
| server not running | `NOSERVER` | 3 |

Default timeout 900 s. The agent runs `wait` as a background command and ends
its turn; the harness wakes it when the command exits. A `TIMEOUT` is a
heartbeat, not a failure — the agent re-arms it. Its purpose is to stop a
forgotten browser tab from wedging the agent indefinitely.

Implementation: poll the session directory at ~250 ms. Simple, dependency-free,
and imperceptible against a human filling in a form.

### `status`

Prints a compact JSON summary — server alive, current round, answered/total
counts by importance, whether a draft exists. Read-only.

### `stop`

Terminates the server, leaves the session directory intact.

---

## The loop

```
agent writes round-001.questions.json
agent runs  craftui.py wait --round 1 --timeout 900   (backgrounded)
agent ends its turn
      ⋮
user answers in the browser        → draft.json after every change
user presses "Send to Claude"      → answers.json written
                                   → wait exits: SUBMITTED round=1
      ⋮
harness wakes the agent
agent reads answers, updates CRAFT.md, writes round-002.questions.json
agent runs  craftui.py wait --round 2 ...
```

**Termination.** On `FINISHED` the agent does one final fold, writes the
complete brief, and reports status. **Finish means the user has stopped
answering; it does not mean the vision is clear.** If REQUIRED questions remain
unanswered the agent says which ones, plainly, and reports
`CRAFT STATUS: MORE CLARIFICATION NEEDED`. Only a genuinely complete brief gets
`VISION CLEAR`. Conflating the two would let a half-filled brief walk into
planning wearing a green light.

The agent may also conclude the vision is clear on its own, before Finish. It
then posts a final round containing no questions and a closing note, and stops.

---

## Server behaviour

- **Binds `127.0.0.1` only.** The URL carries a session key the server requires
  on every request; anything without it gets `403`. After first load the browser
  holds the key in a cookie, so reloads and asset fetches carry it. This is the
  same
  posture as the superpowers brainstorming companion, and it exists so a stray
  tab or another machine on the LAN cannot read the user's product plans.
- **Serves three things:** `app.html`, the current round JSON, and `CRAFT.md`
  as raw text for the browser to render.
- **Accepts two things:** a draft PATCH on every change, and a submit POST
  carrying `finished: true|false`.
- **A malformed `round-NNN.questions.json` renders an error screen naming the
  file and the parse error.** It never takes the server down — the agent is the
  thing writing those files, and a crash loop between the two would be
  unrecoverable from the browser.
- **Idle timeout** exits the process after 4 hours with no requests, so a
  forgotten server does not outlive the machine's uptime.

## UI behaviour

Layout: questions carry the page, brief and ledger pinned right.

**Left — the question stream.** Grouped by `area`, importance chip on each, and
*"why this matters"* rendered always-visible rather than folded — that sentence
is most of craft's value and hiding it would reduce the page to a form. Controls
render per `type`; `allow_other` adds a free-text "Other"; `delegable` adds the
**you decide** button. Every question carries an optional note field, which is
where *"email, but I want passkeys later"* goes — the nuance a radio button
destroys.

**Header — the importance filter.** Client-side class toggling over
`REQUIRED / IMPORTANT / PREFERENCE / OPTIONAL`, no round trip. Untick the bottom
two and the page shrinks to what is blocking.

**Right — brief above, ledger below.** The brief is `CRAFT.md`, re-read from
disk and re-rendered after each round. Contradictions pin to the top of the
ledger in red with jump links to the questions involved, because
`BLOCKED BY CONTRADICTION` is one of craft's three terminal states and it must
be impossible to miss.

**Footer — Send to Claude**, sticky, with a live count: *"9 answered · 3
REQUIRED still open"*. It never blocks a partial round, but the user cannot send
one without seeing what they left. **Finish** sits apart and confirms before
firing, since it ends the session.

**Between rounds.** After Send, the page enters a *"Claude is folding your
answers in…"* state, and polls (~1 s) for a higher round number. When
`round-002.questions.json` appears the page swaps in the new round and re-reads
`CRAFT.md`, so the brief visibly grows without the user touching anything. The
poll is also how a fold that takes several minutes stays legible rather than
looking hung.

**Connection state.** If the server dies the page shows a paused overlay and
reconnects on its own when it returns — a restart on the same project directory
reuses the port, so the open tab recovers without a new URL.

**Accepted limitation.** Rendering `CRAFT.md` needs a markdown renderer, and
"stdlib only, no npm" means a small hand-written one: headings, bold, italic,
inline code, fenced code, lists, blockquote, horizontal rule, links. That covers
the brief's shape. It will not cover tables or anything exotic, and the brief
should not rely on them.

---

## Changes to `craft/SKILL.md`

Two edits. Small on purpose — the whole value of D3 is that one body of
guidance governs both front-ends.

1. **Frontmatter:** add `argument-hint: "[ui|file]"`.

2. **A new `# Delivery` section**, placed immediately after *§2 Create a
   crafting file*, which currently states unconditionally that the questionnaire
   goes into `CRAFT.md`. The new section makes that conditional and covers:

   - **Choose the front-end once, at session start.** `ui` and `file` force
     either; with no argument, try the UI and fall back.
   - **Fallback is silent-ish and never fatal:** if `python3` is missing or the
     server will not bind, say so in one line and continue in file mode. A
     product discovery session must not be blocked by a web server.
   - **Everything else in this file applies identically to both modes** —
     question design, the four importance levels, areas to explore, challenge my
     thinking, the strict boundaries, the three end statuses.
   - **The consequence that must be stated explicitly:** in UI mode `CRAFT.md`
     holds *only the accumulated brief*, never the questionnaire. Questions live
     in `round-NNN.questions.json`. In file mode it holds both, as today.
     Without this stated plainly the agent will helpfully write the
     questionnaire into `CRAFT.md` as well, and the user ends up answering the
     same questions in two places.
   - **The loop:** write a round, `wait` in the background, end the turn, fold,
     repeat. Do not busy-poll; do not ask the user in chat what they are
     answering in the browser.
   - **Mapping craft's concepts onto the wire format:** delegated answers become
     Delegated Decisions and are never re-asked; skipped answers stay open;
     notes are folded in as qualifiers, not discarded.

---

## Testing

**Python — `ui/tests/test_craftui.py`, stdlib `unittest`.**

| Case | Asserts |
|------|---------|
| round discovery | highest-numbered `questions.json` is served; a gap in numbering does not break it |
| round advance | writing `round-002.questions.json` while serving round 1 makes the next fetch return round 2 |
| autosave | a draft PATCH persists; a second PATCH overwrites; the draft survives a server restart |
| promote | Send writes `answers.json` atomically and the draft is left behind untouched |
| `wait` — submit | exits `0` printing `SUBMITTED` with the answers path |
| `wait` — finish | exits `0` printing `FINISHED`; `finished: true` is in the file |
| `wait` — timeout | exits `2` printing `TIMEOUT` after the given deadline |
| `wait` — no server | exits `3` printing `NOSERVER` |
| auth | a request with no key, and one with a wrong key, both get `403` |
| malformed round | a `questions.json` with a syntax error yields an error screen, and the process is still alive afterwards |
| answer states | delegated, skipped, answered and absent round-trip distinctly through the JSON |

**End-to-end — `ui/tests/smoke.sh`.** Starts a real server on an ephemeral port
in a temp directory, POSTs answers over HTTP with `urllib`, asserts `wait` exits
`SUBMITTED`, stops the server. Never touches a real project.

**The skill edit — `superpowers:writing-skills` Iron Law: no skill change
without a failing test first.**

- **RED.** Give a subagent the UI, the CLI and `craft/SKILL.md` *without* the
  Delivery section, plus a vague product idea. Record what it does. Expected
  failure modes: ignores the UI entirely and writes `CRAFT.md`, or launches the
  UI *and* duplicates the questionnaire into `CRAFT.md`.
- **GREEN.** Same scenario with the Delivery section. Must launch the UI, write
  `round-001.questions.json`, and leave the questionnaire out of `CRAFT.md`.
- **Pressure case.** *"Skip the UI, just ask me in chat, it's faster."* The
  agent may move to chat, but must still not inline the questionnaire into
  `CRAFT.md` while a UI session is live, and must not leave the session in a
  state where both surfaces hold different answers.

---

## Operational note

Development happens in a proper clone at `~/IntellijProjects/claude-plugin`.
The copy at `~/.claude/plugins/marketplaces/kardebadas-claude-plugin` is managed
by `claude plugin marketplace update`, which runs git against that directory;
it stays a consumer, and is refreshed by `marketplace update` after a push.

## Deliberate limitations

- One session per project directory at a time. Two concurrent `craft` sessions
  on one project would collide on `.craft/`; not guarded, not supported.
- No round history UI. Earlier rounds remain on disk as JSON and are readable,
  but the page shows the current round only (D5).
- No authentication beyond the session key, and no TLS. Loopback only.
- The markdown renderer covers common constructs, not tables.
