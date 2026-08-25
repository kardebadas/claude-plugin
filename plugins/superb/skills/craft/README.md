# craft

Part of the `superb` plugin — invoked as **`superb:craft`**.

Turns a vague product idea into a clear representation of what you actually
want. "Let's craft an application similar to Spotify" does not mean *build
Spotify* — it means *help me define what my version of this should be*.

## How it runs

It does not interrogate you in chat. It writes **`CRAFT.md`**: a questionnaire
tailored to the product being discussed — a Spotify-like app gets questions
about queues, shuffle and playlist collaboration; an Airbnb-like app gets
availability, cancellation and pricing. You answer as many as you like, save,
and ask for a review. Each pass folds your answers in, marks decisions
confirmed, closes resolved questions and adds only useful follow-ups, so the
file gets **shorter and sharper** every round rather than regenerating.

Questions carry a weight — `REQUIRED`, `IMPORTANT`, `PREFERENCE`, `OPTIONAL` —
so a long file still tells you what actually matters.

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
[`superb:superpipeline`](../superpipeline) is the skill that takes it from there.
