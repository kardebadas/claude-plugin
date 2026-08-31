#!/usr/bin/env bash
# Mechanical completion check for a CRAFT.md. See check-brief.py.
exec python3 "$(dirname "$0")/check-brief.py" "$@"
