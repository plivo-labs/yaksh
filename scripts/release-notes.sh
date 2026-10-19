#!/usr/bin/env bash
# Prints the section of CHANGELOG.md for one tag, such as v0.2.0, without its heading.
set -euo pipefail

tag="$1"
notes=$(awk -v tag="$tag" '
  /^## / { if (found) exit; if ($2 == tag) { found = 1; next } }
  found { print }
' CHANGELOG.md)
if [ -z "$(printf '%s' "$notes" | tr -d '[:space:]')" ]; then
  echo "CHANGELOG.md has no section for $tag" >&2
  exit 1
fi
printf '%s\n' "$notes"
