# craft

Part of the `superb` plugin — invoked as **`superb:craft`**.

Turns a vague product idea into a clear representation of what you actually
want. "Let's craft an application similar to Spotify" does not mean *build
Spotify* — it means *help me define what my version of this should be*.

## How it runs

It does not interrogate you in chat. It puts a questionnaire in front of you —
tailored to the product being discussed, so a Spotify-like app gets questions
about queues, shuffle and playlist collaboration while an Airbnb-like app gets
availability, cancellation and pricing. You answer as many as you like and send
them back. Each pass folds your answers in, marks decisions confirmed, closes
resolved questions and adds only useful follow-ups, so every round is
**shorter and sharper** than the last rather than a regenerated form.

Questions carry a weight — `REQUIRED`, `IMPORTANT`, `PREFERENCE`, `OPTIONAL` —
so a long questionnaire still tells you what actually matters.

## Two ways to answer

The skill decides once, at the start of a session, and says which mode it is
in. `/superb:craft ui` forces the browser, `/superb:craft file` forces the
file, and with no argument it tries the browser and falls back to the file.
Everything else — the question design, the challenging, the boundaries, the
end statuses — is identical either way. Only the surface changes.

**Browser.** A local, offline, single-file web UI on `127.0.0.1`, started with
`ui/craftui.py serve`. It gives you one question per card with real radio
buttons, checkboxes and text fields, a running sidebar of decisions,
assumptions, contradictions and delegated decisions, a **you decide** button on
questions you would rather hand over, a free-text note beside any answer, and
autosave so a closed tab loses nothing. Send when you have had enough for one
round; Finish when you are done. The agent waits in the background and wakes
when you send. In this mode **`CRAFT.md` holds only the accumulated brief** —
the questions live in `.craft/round-NNN.questions.json` and never appear in the
brief, so you are never asked the same thing twice in two places.

**File.** The original mode, and the fallback: the questionnaire is written
into `CRAFT.md` itself, with `[REQUIRED]`-style headings and a **My decision**
block under each question. You open the file, answer as many as you like, save,
and ask for a review. No Python, no server, no browser.

Falling back is never treated as a failure. No `python3`, a server that will
not start, or another craft session already holding the project — the skill
says so in one line and carries on in file mode.

## What it records

- **Confirmed decisions**, with their source, so downstream agents have an
  authoritative answer rather than a guess.
- **Assumptions**, visibly, each with its impact if wrong. An assumption is
  never silently promoted into a requirement.
- **Delegated decisions** — the ones you deliberately want another skill to
  make. This is a real answer, and recording it stops the next agent reading an
  unanswered question as an oversight.
- **Contradictions**, surfaced rather than quietly resolved: offline-only plus
  mandatory server state, anonymous users plus cross-device personalisation.

## It challenges you

Say "anyone can collaboratively edit playlists" and it asks about invitations,
ownership, removing collaborators, conflicting edits and abuse. Say "music
should be downloadable" and it asks about expiry, device limits and licensing.
The point is to expose the decisions, not to make them for you.

## What it will not do

No implementation. No plan, phases, tickets, task lists, estimates or coding
sequence. Naming a technical consequence is in scope — "cross-device queue sync
needs server-side state" — designing the service is not.

## Finishing

Each pass ends with one of:

```
CRAFT STATUS: VISION CLEAR
CRAFT STATUS: MORE CLARIFICATION NEEDED
CRAFT STATUS: BLOCKED BY CONTRADICTION
```

`VISION CLEAR` means another skill could now plan the architecture from
`CRAFT.md` alone, without the original conversation. It does **not** mean
building should start automatically — that is still your call, and
[`superb:pipeline`](../pipeline) is the skill that takes it from there.
