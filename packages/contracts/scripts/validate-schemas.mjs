#!/usr/bin/env node
// Compiles every canonical JSON Schema with the same validator the services use.
//
// This catches the mistakes that only show up at runtime otherwise: a $ref to a $def that was
// renamed, a typo in a keyword name, a pattern that does not compile. It runs in CI before any
// code generation, because a schema that does not compile produces plausible-looking but wrong
// generated models.
//
// Usage: node scripts/validate-schemas.mjs

import { readFileSync, readdirSync } from 'node:fs';
import { join, dirname, basename } from 'node:path';
import { fileURLToPath } from 'node:url';

import Ajv2020 from 'ajv/dist/2020.js';
import addFormats from 'ajv-formats';

const here = dirname(fileURLToPath(import.meta.url));
const commonDir = join(here, '..', 'jsonschema', 'common');

const files = readdirSync(commonDir)
  .filter((name) => name.endsWith('.schema.json'))
  .sort();

if (files.length === 0) {
  console.error('No schemas found in jsonschema/common — nothing to validate.');
  process.exit(1);
}

// The schemas carry no $id: relative $refs resolve by file name, which is what redocly,
// openapi-typescript and datamodel-code-generator all do. Registering each schema under its
// bare file name reproduces that here.
const ajv = new Ajv2020({
  strict: true,
  allErrors: true,
  validateFormats: true,
  // Defaults are documentation for consumers, not something the validator should apply.
  useDefaults: false,
  // The derived feature map in IntegratedTravelContext holds numeric, categorical and boolean
  // features side by side, which is a genuine union rather than a modelling slip.
  allowUnionTypes: true,
});
addFormats(ajv);

let failures = 0;

for (const file of files) {
  const raw = readFileSync(join(commonDir, file), 'utf8');
  let parsed;
  try {
    parsed = JSON.parse(raw);
  } catch (error) {
    console.error(`FAIL ${file}: not valid JSON — ${error.message}`);
    failures += 1;
    continue;
  }
  if (!parsed.title) {
    console.error(`FAIL ${file}: every schema needs a title; generators use it as the type name.`);
    failures += 1;
  }
  if (!parsed.description) {
    console.error(`FAIL ${file}: every schema needs a description explaining what it guarantees.`);
    failures += 1;
  }
  ajv.addSchema(parsed, basename(file));
}

// Compiling happens after all schemas are registered so cross-file $refs resolve.
for (const file of files) {
  try {
    ajv.getSchema(basename(file));
    ajv.compile(JSON.parse(readFileSync(join(commonDir, file), 'utf8')));
    console.log(`ok   ${file}`);
  } catch (error) {
    console.error(`FAIL ${file}: ${error.message}`);
    failures += 1;
  }
}

if (failures > 0) {
  console.error(`\n${failures} schema problem(s).`);
  process.exit(1);
}

console.log(`\n${files.length} schemas compiled.`);
