#!/usr/bin/env python3
"""Validate a P01 baseline-evidence tree.

Real-agent evidence and simulated evidence live in two sibling directories and
carry two mutually exclusive class labels. This script is the mechanical step
that enforces the separation: a record whose label disagrees with its directory
fails here, before anybody reads it as proof of anything.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

STIMULUS_IDS = (
    "S01", "S02", "S03", "S04", "S05", "S06", "S07", "S08", "S09", "S10",
)
ACTUAL_CLASS = "ACTUAL_AGENT"
SIMULATED_CLASS = "SIMULATED"
CLASS_BY_DIR = {"actual-agent": ACTUAL_CLASS, "simulated": SIMULATED_CLASS}

#: Without every one of these a record cannot be re-run, and a dispatch that
#: cannot be re-run is an anecdote.
HEADER_FIELDS = (
    "Evidence class",
    "Stimulus ID",
    "Stimulus SHA-256",
    "Skill present",
    "Dispatch",
    "Agent id",
    "Agent model",
    "Recorded UTC",
)
#: Vocabulary that only ever appears in the oracle. In a record it means the
#: controller's grading was pasted in beside the agent's own words.
ORACLE_TOKENS = (
    "Correct behaviour:",
    "Fail predicate:",
    "Rationalization watchlist:",
    "GREEN predicate:",
    "ORACLE:",
    "expected-result:",
    "controller-only",
)
#: An unfilled marker means the field was never observed.
PLACEHOLDERS = ("TBD", "TODO", "<fill", "XXX")
#: An unfilled angle-bracket slot copied straight out of RECORD-TEMPLATE.md.
#: Every slot in that template has this shape -- ``<`` followed immediately by
#: a non-space character and closed by ``>`` on the same line: ``<STIMULUS_ID>``,
#: ``<sha256 of the exact prompt-borne stimulus file, 64 hex chars>``,
#: ``<YYYY-MM-DDTHH:MM:SSZ>``, ``<plain|suffix>``. None of them contains the
#: literal ``<fill``, so before this rule existed a record copied from the
#: template with every slot left unfilled validated clean and counted as a real
#: ACTUAL_AGENT baseline -- evidence that only looks like evidence.
UNFILLED_SLOT = re.compile(r"<[^\s>][^>\n]*>")
MIN_RAW_CHARS = 200
FILENAME = re.compile(r"^p01-(S(?:0[1-9]|10))-baseline-(\d{2})\.md$")


def _header_region(text: str) -> str:
    """The part of a record its author writes: everything before the transcript.

    The ``## Raw response`` body is deliberately exempt from the unfilled-slot
    rule. That body is a verbatim agent transcript, and an agent may legitimately
    emit angle brackets -- quoted XML or HTML, generics, a shell redirection, an
    ``<unknown>`` marker of its own. Rejecting those would force the recorder to
    edit a published transcript, which is the one thing a raw record may never
    do, so the rule is confined to the header/metadata region instead.

    An unfilled *body* is still caught, by a different rule: the template's body
    slot is far shorter than MIN_RAW_CHARS, so the substantive-body floor
    rejects it. A record missing the marker entirely is already an error, and
    falls back to scanning the whole text.
    """
    return text.split("## Raw response", 1)[0]


def _field(text: str, name: str) -> str | None:
    match = re.search(rf"^- {re.escape(name)}: (.+)$", text, re.MULTILINE)
    return match.group(1).strip() if match else None


def check_file(path: Path, expected_class: str) -> list[str]:
    name_match = FILENAME.match(path.name)
    if not name_match:
        return [f"{path}: filename does not match p01-S0N-baseline-NN.md"]

    errors: list[str] = []
    text = path.read_text(encoding="utf-8")

    for field in HEADER_FIELDS:
        if _field(text, field) is None:
            errors.append(f"{path}: missing required header field {field!r}")

    declared = _field(text, "Evidence class")
    if declared != expected_class:
        errors.append(
            f"{path}: Evidence class is {declared!r}, "
            f"directory requires {expected_class!r}")
    foreign = SIMULATED_CLASS if expected_class == ACTUAL_CLASS else ACTUAL_CLASS
    if foreign in text:
        errors.append(f"{path}: contains the foreign class label {foreign!r}")

    if _field(text, "Stimulus ID") != name_match.group(1):
        errors.append(f"{path}: Stimulus ID does not match the filename")
    if _field(text, "Skill present") != "none":
        errors.append(f"{path}: a RED baseline requires 'Skill present: none'")

    if "## Raw response" not in text:
        errors.append(f"{path}: missing the '## Raw response' section")
    else:
        body = text.split("## Raw response", 1)[1].strip()
        if len(body) < MIN_RAW_CHARS:
            errors.append(
                f"{path}: '## Raw response' body is under "
                f"{MIN_RAW_CHARS} characters")

    for token in ORACLE_TOKENS:
        if token in text:
            errors.append(f"{path}: oracle vocabulary {token!r} leaked into evidence")
    for token in PLACEHOLDERS:
        if token in text:
            errors.append(f"{path}: placeholder {token!r} present")
    seen_slots: set[str] = set()
    for slot in UNFILLED_SLOT.findall(_header_region(text)):
        if slot in seen_slots:
            continue
        seen_slots.add(slot)
        errors.append(f"{path}: unfilled template slot {slot!r} in the record header")

    return errors


def check_tree(root: Path) -> list[str]:
    errors: list[str] = []
    valid_actual: set[str] = set()

    for subdir, expected_class in CLASS_BY_DIR.items():
        directory = root / subdir
        if not directory.is_dir():
            errors.append(f"{directory}: required directory is missing")
            continue
        for path in sorted(directory.iterdir()):
            if path.name == ".gitkeep":
                continue
            if not path.is_file() or path.suffix != ".md":
                errors.append(f"{path}: unexpected entry in an evidence directory")
                continue
            file_errors = check_file(path, expected_class)
            errors.extend(file_errors)
            name_match = FILENAME.match(path.name)
            if expected_class == ACTUAL_CLASS and name_match and not file_errors:
                valid_actual.add(name_match.group(1))

    missing = [sid for sid in STIMULUS_IDS if sid not in valid_actual]
    if missing:
        errors.append("missing valid ACTUAL_AGENT baseline for: " + ", ".join(missing))
    return errors


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        print("usage: check_baseline_evidence.py <records-root>", file=sys.stderr)
        return 2
    errors = check_tree(Path(argv[1]))
    for error in errors:
        print(error, file=sys.stderr)
    if errors:
        return 1
    print(f"OK: {len(STIMULUS_IDS)} ACTUAL_AGENT baselines, class separation intact")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
