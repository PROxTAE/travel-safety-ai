#!/usr/bin/env node
// Validates every fixture in examples/ against the schema it names, and enforces the provenance
// rules for anything captured from a real provider.
//
// An example that drifts from its schema is worse than no example: consumers build against it and
// only find out at integration time. CI runs this on every PR.
//
// Usage: node scripts/validate-examples.mjs

import { readFileSync, readdirSync, statSync } from 'node:fs';
import { join, dirname, basename, relative } from 'node:path';
import { fileURLToPath } from 'node:url';

import Ajv2020 from 'ajv/dist/2020.js';
import addFormats from 'ajv-formats';

const here = dirname(fileURLToPath(import.meta.url));
const root = join(here, '..');
const commonDir = join(root, 'jsonschema', 'common');
const examplesDir = join(root, 'examples');

const REQUIRED_PROVENANCE = [
  'provider',
  'source_url',
  'captured_at',
  'license',
  'attribution',
  'upstream_content_hash',
  'redaction',
];

const ajv = new Ajv2020({
  strict: true,
  allErrors: true,
  validateFormats: true,
  useDefaults: false,
  allowUnionTypes: true,
});
addFormats(ajv);

for (const file of readdirSync(commonDir).filter((n) => n.endsWith('.schema.json'))) {
  ajv.addSchema(JSON.parse(readFileSync(join(commonDir, file), 'utf8')), basename(file));
}

function collect(dir) {
  const out = [];
  for (const entry of readdirSync(dir)) {
    const full = join(dir, entry);
    if (statSync(full).isDirectory()) out.push(...collect(full));
    else if (entry.endsWith('.json')) out.push(full);
  }
  return out;
}

const files = collect(examplesDir).sort();
if (files.length === 0) {
  console.error('No examples found under examples/.');
  process.exit(1);
}

let failures = 0;

for (const path of files) {
  const label = relative(root, path).replaceAll('\\', '/');
  let fixture;
  try {
    fixture = JSON.parse(readFileSync(path, 'utf8'));
  } catch (error) {
    console.error(`FAIL ${label}: not valid JSON — ${error.message}`);
    failures += 1;
    continue;
  }

  for (const key of ['target', 'kind', 'summary', 'value']) {
    if (fixture[key] === undefined) {
      console.error(`FAIL ${label}: missing "${key}". See examples/README.md for the wrapper format.`);
      failures += 1;
    }
  }
  if (failures > 0 && fixture.target === undefined) continue;

  if (!['structural', 'real-sanitized'].includes(fixture.kind)) {
    console.error(`FAIL ${label}: kind must be "structural" or "real-sanitized", got ${JSON.stringify(fixture.kind)}.`);
    failures += 1;
    continue;
  }

  const inRealFolder = label.includes('/real-sanitized/');
  if (inRealFolder !== (fixture.kind === 'real-sanitized')) {
    console.error(`FAIL ${label}: a ${fixture.kind} fixture must not live in this folder.`);
    failures += 1;
  }

  if (fixture.kind === 'real-sanitized') {
    const provenance = fixture.provenance ?? {};
    for (const key of REQUIRED_PROVENANCE) {
      if (!provenance[key]) {
        console.error(`FAIL ${label}: real-sanitized fixtures must record provenance.${key}.`);
        failures += 1;
      }
    }
  } else if (!fixture.provenance?.redaction) {
    console.error(`FAIL ${label}: structural fixtures must state provenance.redaction, even if only to say the data is synthetic.`);
    failures += 1;
  }

  // "jsonschema/common/x.schema.json" or "jsonschema/common/x.schema.json#/$defs/Y"
  const [targetFile, pointer] = String(fixture.target).split('#');
  if (!targetFile.startsWith('jsonschema/common/')) {
    console.error(`FAIL ${label}: target must point into jsonschema/common/, got "${fixture.target}".`);
    failures += 1;
    continue;
  }

  const schemaKey = basename(targetFile) + (pointer ? `#${pointer}` : '');
  let validate;
  try {
    validate = ajv.getSchema(schemaKey);
  } catch (error) {
    console.error(`FAIL ${label}: cannot resolve target "${fixture.target}" — ${error.message}`);
    failures += 1;
    continue;
  }
  if (!validate) {
    console.error(`FAIL ${label}: cannot resolve target "${fixture.target}".`);
    failures += 1;
    continue;
  }

  if (validate(fixture.value)) {
    console.log(`ok   ${label} -> ${fixture.target}`);
  } else {
    console.error(`FAIL ${label} -> ${fixture.target}`);
    for (const error of validate.errors ?? []) {
      console.error(`       ${error.instancePath || '/'} ${error.message}`);
    }
    failures += 1;
  }
}

if (failures > 0) {
  console.error(`\n${failures} example problem(s).`);
  process.exit(1);
}

console.log(`\n${files.length} examples validated.`);
