#!/usr/bin/env bash
# Generates the Python view of the public API from the bundled OpenAPI document.
#
# Python services import these Pydantic models instead of restating request and response shapes, so
# a contract change is a type error at build time rather than a 500 at runtime. Nothing under
# generated/ may be edited by hand; CI regenerates and fails if the working tree moves.
#
# Usage (from packages/contracts):
#   npm run bundle && ./scripts/generate-python.sh
#
# Requires uv (https://docs.astral.sh/uv/). The generator version is pinned below so two machines
# produce byte-identical output.

set -euo pipefail

CODEGEN_VERSION="0.28.5"
PYTHON_VERSION="3.12"

# Force UTF-8 for the generator and for the rewrite below. Without it, Python on Windows writes the
# file in the system code page, so a non-ASCII character in any schema description — an em-dash is
# enough — lands as a byte that is not valid UTF-8. CI runs on Linux and would never see it; the
# committed file would simply be undecodable for everyone else.
export PYTHONUTF8=1
export PYTHONIOENCODING=utf-8
export LC_ALL="${LC_ALL:-C.UTF-8}"

here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
root="$(dirname "$here")"
cd "$root"

bundle="generated/openapi/public-api.bundled.yaml"
package_dir="generated/python/smart_travel_contracts"
out="$package_dir/public_api.py"

if [ ! -f "$bundle" ]; then
  echo "Missing $bundle — run 'npm run bundle' first." >&2
  exit 1
fi

mkdir -p "$package_dir"

uvx --python "$PYTHON_VERSION" --from "datamodel-code-generator==${CODEGEN_VERSION}" datamodel-codegen \
  --input "$bundle" \
  --input-file-type openapi \
  --output "$out" \
  --output-model-type pydantic_v2.BaseModel \
  --target-python-version "$PYTHON_VERSION" \
  --disable-timestamp \
  --use-standard-collections \
  --use-union-operator \
  --use-schema-description \
  --use-field-description \
  --field-constraints

# datamodel-code-generator writes its own two-line header; replace it with one that says where the
# contract lives and how to regenerate, which is what a reader of this file actually needs.
python_header=$(cat <<'EOF'
"""GENERATED FILE - DO NOT EDIT.

Source:     packages/contracts/openapi/public-api.yaml
Regenerate: cd packages/contracts && npm run bundle && ./scripts/generate-python.sh

Editing this file by hand makes the models disagree with the contract, which is the exact
failure this pipeline exists to prevent.
"""
EOF
)

tmp="$(mktemp)"
{
  printf '%s\n\n' "$python_header"
  tail -n +3 "$out"
} > "$tmp"
mv "$tmp" "$out"

cat > "$package_dir/__init__.py" <<'EOF'
"""Generated contract models for the Smart Travel Assistant public API.

Produced from packages/contracts/openapi/public-api.yaml. Do not edit by hand.
"""

from . import public_api

__all__ = ["public_api"]
EOF

cat > "$package_dir/py.typed" <<'EOF'
EOF

echo "$out ($(wc -l < "$out" | tr -d ' ') lines)"
