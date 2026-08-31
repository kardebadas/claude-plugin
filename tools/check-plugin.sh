#!/usr/bin/env bash
# Structural checks for the superb plugin. See check-plugin.py.
exec python3 "$(dirname "$0")/check-plugin.py" "$@"
