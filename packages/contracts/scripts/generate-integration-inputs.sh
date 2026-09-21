#!/usr/bin/env bash
# Generate selected integration input models from the canonical JSON Schemas.
set -euo pipefail
export PYTHONUTF8=1
export PYTHONIOENCODING=utf-8

here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
root="$(dirname "$here")"
output="$root/generated/python/smart_travel_contracts/integration_inputs"
temporary="$(mktemp -d)"
trap 'rm -rf -- "$temporary"' EXIT
models="$temporary/models"
generator_input="$root/jsonschema/common"
generator_output="$models"
if command -v cygpath >/dev/null 2>&1; then
  generator_input="$(cygpath -w "$generator_input")"
  generator_output="$(cygpath -w "$generator_output")"
fi

uvx --python 3.12 --from datamodel-code-generator==0.28.5 datamodel-codegen \
  --input "$generator_input" \
  --input-file-type jsonschema \
  --output "$generator_output" \
  --output-model-type pydantic_v2.BaseModel \
  --target-python-version 3.12 \
  --disable-timestamp \
  --use-standard-collections \
  --use-union-operator \
  --field-constraints

mkdir -p "$output"
for name in __init__.py primitives_schema.py enums_schema.py geojson_schema.py \
  source_provenance_schema.py data_quality_schema.py weather_schema.py \
  transport_status_schema.py disaster_event_schema.py emergency_poi_schema.py \
  route_candidate_schema.py; do
  cp "$models/$name" "$output/$name"
done
