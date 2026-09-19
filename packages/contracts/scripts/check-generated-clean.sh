#!/usr/bin/env bash
# Regenerates everything and fails if the working tree moved.
#
# This is the rule that makes `generated/` trustworthy: if the committed output does not match what
# the source produces, then someone edited generated code by hand or forgot to regenerate, and
# every consumer that imported it is now building against something the contract does not say.
#
# Usage (from packages/contracts):
#   ./scripts/check-generated-clean.sh

set -euo pipefail

here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
root="$(dirname "$here")"
cd "$root"

npm run --silent bundle
npm run --silent generate:ts
./scripts/generate-python.sh

if ! git diff --quiet -- generated; then
  echo
  echo "Generated contract output is out of date. Files that differ:" >&2
  git --no-pager diff --stat -- generated >&2
  echo >&2
  echo "Run 'npm run generate' in packages/contracts and commit the result." >&2
  exit 1
fi

untracked="$(git ls-files --others --exclude-standard -- generated)"
if [ -n "$untracked" ]; then
  echo
  echo "Generation produced files that are not committed:" >&2
  echo "$untracked" >&2
  exit 1
fi

echo "Generated contract output matches the source."
