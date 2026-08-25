#!/usr/bin/env bash
# Runs the whole craft UI suite. Every task must leave this green.
set -euo pipefail
cd "$(dirname "$0")/../plugins/superb/skills/craft/ui"
python3 -m unittest discover -s tests -t . "$@"
