#!/usr/bin/env python3
"""Print one exact Phase 4 worker-stimulus section."""

from pathlib import Path
import sys


STIMULUS_IDS = ("R01", "R02", "R03", "R04")
CATALOG = Path(__file__).with_name("phase-04-worker-stimuli.md")


def extract_stimulus(stimulus_id: str) -> str:
    if stimulus_id not in STIMULUS_IDS:
        raise ValueError(f"unknown stimulus ID: {stimulus_id}")

    lines = CATALOG.read_text(encoding="utf-8").splitlines()
    heading = f"## {stimulus_id}"
    try:
        start = lines.index(heading)
    except ValueError as error:
        raise ValueError(f"missing stimulus heading: {heading}") from error

    end = next(
        (
            index
            for index in range(start + 1, len(lines))
            if lines[index] in {f"## {item}" for item in STIMULUS_IDS}
        ),
        len(lines),
    )
    return "\n".join(lines[start:end]).rstrip() + "\n"


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        print("usage: extract_phase04_stimulus.py R01|R02|R03|R04", file=sys.stderr)
        return 2
    try:
        sys.stdout.write(extract_stimulus(argv[1]))
    except (OSError, ValueError) as error:
        print(error, file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
