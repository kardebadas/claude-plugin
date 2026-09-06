# BA2 — How craft should drive its question rounds automatically

Question: how should craft drive its question rounds with no user prompting between waves?
Verdict: **same defect class as the pipeline one — fix it in `SKILL.md`, change nothing in `craftui.py`.**

## Evidence base

| File | What it establishes |
|---|---|
| `plugins/superb/skills/craft/SKILL.md` §The loop, L225-231 | Step 2 is literally *"Run … `wait` … **as a background command**, and end your turn."* |
| Same file, L275-285 | The exit-code table: `0 SUBMITTED`, `0 FINISHED`, `2 TIMEOUT` (re-arm), `3 NOSERVER`, `1 ERROR`, `64 usage`. L282: *"Re-arm `wait` on 2, and never on 1 or 64."* |
| Same file, L9 | The skill declares itself *"for Claude Code / Codex CLI"* — two harnesses, only one of which re-invokes. |
| `craft/ui/craftui.py` `cmd_wait`, L937-1005 | `wait` is a **blocking foreground poll loop**: `POLL_S = 0.25` (L861), bounded by `deadline = time.monotonic() + args.timeout` (L951), default `--timeout 900.0` = 15 min (L1376). It writes nothing (docstring L928-935). |
| `plugins/superb/skills/pipeline/SKILL.md` L514-543 | "Who wakes you after a dispatch": re-invoking harness = completion starts a new turn; **mailbox harness = the answer only a new turn drains, and completion cannot start one → ending the turn parks the run until the user types something.** L540-543: if you cannot establish the family, treat it as a mailbox harness. |
| `superpowers/6.3.0/.../codex-tools.md` L57-60 | *"Completion mail cannot wake an idle controller (it is delivered without triggering a turn); covering that idle window is `wait_agent`'s only job."* |

## 1. Is it the same defect?

Yes, structurally identical.

The pipeline defect is: *an instruction to end the turn, on a harness where nothing but the user can start the next one.* Craft L227 issues exactly that instruction — "end your turn" — and makes the resumption depend on a **background-command completion notification**, which is a harness capability, not a property of `craftui.py`. `cmd_wait` is a plain blocking process that prints one line and exits (L937-1005); it has no channel back into an agent turn at all. Whether the agent ever wakes is therefore decided entirely outside the skill:

- **Claude Code** (re-invoking): a genuine `run_in_background` bash task re-invokes on exit, so the loop appears to work — sometimes.
- **Codex CLI** (mailbox, and L9 says craft targets it): the exit is mail; mail does not start a turn; the run parks. The user types *"already replied, next wave"* — which is precisely the reported symptom, verbatim the pipeline symptom ("stops after every task … the user pays for it, once per task, by having to type *continue*").
- Even on the re-invoking harness the instruction is fragile in a second way: "as a background command" is ambiguous between the harness's background-task mechanism and a shell `&`/`nohup`. A `&` returns instantly, the tool call succeeds, the agent ends its turn, and **nothing is ever going to wake it** — the wait is running detached with its stdout going nowhere the agent reads. That failure is indistinguishable, from the user's chair, from the mailbox failure, and it explains the "sometimes" in the report.

So: not a `craftui.py` bug, not a browser bug. An instruction that outsources the wake-up to a capability the skill cannot verify.

The fix that pipeline already landed applies unchanged: **the wait is executing, not stopping.** Never end a turn while a round is open.

## 2. Watcher subagent, or wait in your own turn?

**Wait in your own turn.** The watcher subagent is the wrong shape, for three independent reasons.

1. **It cannot do the work that follows the wait.** `wait` printing `SUBMITTED round=3` is not the useful event; the useful work is SKILL L316-331 (read `.craft/round-NNN.answers.json`, classify each answer as answered / `delegated` / `skipped` / absent), then L1136-1150 (fold into `CRAFT.md`, mark decisions confirmed, close resolved questions, find contradictions and gaps), then write a **smaller** round N+1. All of that needs the accumulated brief and the conversation the user has been having in the terminal (L151-155). A watcher has neither. It can only courier one line back — a line the parent could have got itself for one tool call.
2. **It does not fix the wake at all — it moves it.** On a mailbox harness, a finished *subagent* is the exact thing `codex-tools.md` L57-60 says cannot wake an idle controller. Spawning a watcher and ending the turn parks the run in precisely the same way, one layer deeper and harder to see. The user's suggestion is a correct diagnosis ("keep watching") with a mechanism that inherits the bug.
3. **Cost.** A watcher is a second context that must be spawned, fed the round number and project dir, and drained — per round, for a dozen rounds — to relay ~40 bytes.

The honest trade-off the other way, and it is real: an in-turn wait means the main agent is inside a tool call for up to 15 minutes, so anything the user types in the terminal is queued rather than acted on immediately. That matters because L151-155 explicitly promises *"the terminal stays mine while I answer"* and tells the user that correcting an earlier round is done there. Mitigation, and it is enough: **bound each wait at ~600 s** (`--timeout 600`) instead of the 900 s default, so the agent surfaces every 10 minutes, drains anything the user typed, folds it in as an ordinary answer per L155, and re-arms. Alternatively run the wait as a background task *and stay in the turn*, monitoring it — same guarantee, no queuing delay. What is forbidden in both variants is the same thing: ending the turn.

## 3. Termination — the exact conditions

The loop ends, and only ends, on one of these:

| # | Condition | Signal | What the agent does |
|---|---|---|---|
| T1 | User pressed **Finish** | `wait` exit 0, line `FINISHED round=N` (`cmd_wait` L963-966: `payload.get("finished") is True`) | Final fold, then judge the brief on its merits per §Ending L336-339: unanswered REQUIRED → `CRAFT STATUS: MORE CLARIFICATION NEEDED`; otherwise `VISION CLEAR`. Then `stop` (L347-350). **Terminal.** |
| T2 | **Agent judges the vision clear** first | Convergence test below | Write a closing round: empty `questions`, a `note` that is the whole page (L340-345). Then `stop`. **Terminal.** |
| T3 | **Unrecoverable error** | exit 1 `ERROR …`, or exit 64 usage | L282: never re-arm on 1 or 64. Exit 1 from `cmd_wait` L974-981 means the answers file exists and is not a round of answers — a state no further wait can change. Fix it, or say so in one line and fall back to file mode (L157-160). **Terminal for the browser loop.** |
| T4 | **Server gone after a quiet stretch** | exit 3 `NOSERVER` (`cmd_wait` L989-993, 8 consecutive dead looks ≈ 1.75 s) **and** this round has already timed out at least once with nothing sent | The 4-hour idle shutdown, i.e. the user walked away. L297-303: report it, offer to bring it back, **stop there — do not `serve` unprompted.** This is the one legitimate place the loop hands the turn back. **Terminal.** |
| T5 | **Server gone while the user is plainly here** | exit 3, no prior timeout on this round | `serve` again, give the **new** URL (a new key is minted, the old URL 403s — L304-310), re-arm the wait. **Not terminal.** |
| T6 | **No progress** | A round comes back with every question `skipped` or absent (L326-331), i.e. the fold produces zero new confirmed decisions and zero delegated decisions | One re-ask is legitimate ("still open. Ask it again next round"). **Two consecutive zero-yield rounds is the stop:** name the still-open REQUIRED/IMPORTANT questions, report `MORE CLARIFICATION NEEDED`, `stop`. Re-asking a third time is the machine arguing with a human who has decided not to answer. **Terminal.** |
| — | `TIMEOUT` (exit 2) | L277, `cmd_wait` L991-1002 | **Not a termination.** Heartbeat. Re-arm in the same turn. |

Note that T1/T2 already both run `stop` (L347-350), so the browser says "session finished" rather than sitting there — the loop's exit is also the server's.

## 4. What stops it being infinite or expensive

Four bounds, in order of which fires first in practice.

1. **Convergence rule (primary, and it is already written).** §Second pass L1150: *"The questionnaire should become smaller and more precise with every pass."* Make it operational: the loop's continuation predicate is **"at least one REQUIRED or IMPORTANT question is still open"** (§Decision importance L456-472; `status` already counts open REQUIRED questions — L206-210 refers to exactly that field). Zero open REQUIRED/IMPORTANT ⇒ T2 closing round. PREFERENCE/OPTIONAL questions never justify another round on their own.
2. **Zero-yield rule (T6).** Two consecutive rounds that add no confirmed decision and no delegated decision ⇒ stop. This is the guard the convergence rule cannot supply, because a user who skips everything leaves REQUIRED questions open for ever.
3. **A hard round cap of 12.** Concrete, and generous: with the required shrinkage, a real craft converges in 3-6 rounds. Hitting 12 means the shrinkage is not happening — report the state and stop rather than continue. The cap is a bug detector, not a budget.
4. **The server's own clock, which the agent cannot override.** `serve --idle-timeout-minutes` defaults to **240.0** (craftui.py L1361, consumed L575). Four hours of complete silence and the server exits; the next `wait` returns `NOSERVER` and lands in T4, which forbids an unprompted `serve`. So even a maximally broken agent cannot loop past four hours of a human's absence.

Token cost is not the binding constraint and should not be modelled as one: each `wait` re-arm returns **one line** (`cmd_wait` prints exactly one, by design — docstring L940-944). The expensive step is the fold, which happens once per round and is bounded by (1)-(3).

## 5. Does `craftui.py` need to change?

**No. This is entirely a `SKILL.md` instruction problem.** The CLI already provides everything an automatic loop needs:

- It **blocks** — `cmd_wait` L957-1005 is a `while True` with `time.sleep(POLL_S)` (L1003) — so there is nothing to poll from the agent side and no busy-wait to invent.
- It is **bounded** — `deadline` L951, default 900 s L1376, and `--timeout` is already a first-class flag (`_timeout_seconds`, L1244).
- Its exit codes **already distinguish every case the loop must branch on**, and deliberately so: `64` exists specifically so a malformed command is not mistaken for a heartbeat (`CraftParser`, L1328-1351 — *"argparse exits 2 for 'you called me wrong', and this CLI documents 2 as TIMEOUT"*).
- `status` exits 0 and writes nothing (L288-291), so the loop can re-check state at any point for free.

The one line to change is `SKILL.md` L226-228. Replace *"as a background command, and end your turn. Do not poll in a loop"* with the pipeline's rule, adapted:

> Run `wait` with `--timeout 600` and **stay in your turn**. On exit 2, re-arm it immediately — that is the whole loop, and it is executing, not stopping. **Never end your turn while a round is open**: on a harness whose background completions do not start a new turn, ending it parks the craft until I type "next wave" — which is not a thing I should ever have to type. The only place you hand the turn back is the four-hour timeout of *Restarting*, or one of the endings in §Ending.

Keep the existing "do not poll in a loop" intent by pinning it to what it actually meant: do not stack short `--timeout` values; `wait` is already a poll loop internally at 0.25 s and a long timeout wakes exactly as fast as a short one (same argument as pipeline L532-535 and codex-tools L44-56).

Optional, non-blocking follow-ups if the loop is ever formalised further: a `--timeout` default of 600 rather than 900 would make the terminal-drain cadence the default rather than a flag the agent must remember. Not required for correctness.
