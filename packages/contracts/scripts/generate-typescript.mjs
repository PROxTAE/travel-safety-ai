#!/usr/bin/env node
// Generates the TypeScript view of the public API from the bundled OpenAPI document.
//
// The web app imports these types instead of hand-writing request and response shapes, so a
// contract change shows up as a type error in the consumer rather than as a runtime surprise.
// Nothing here may be edited by hand: CI regenerates and fails if the working tree moves.
//
// Usage: node scripts/generate-typescript.mjs   (run `npm run bundle` first)

import { mkdirSync, readFileSync, writeFileSync } from 'node:fs';
import { join, dirname } from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';

import openapiTS, { astToString } from 'openapi-typescript';

const here = dirname(fileURLToPath(import.meta.url));
const root = join(here, '..');
const bundle = join(root, 'generated', 'openapi', 'public-api.bundled.yaml');
const outDir = join(root, 'generated', 'typescript');
const outFile = join(outDir, 'public-api.d.ts');

const banner = `/**
 * GENERATED FILE — DO NOT EDIT.
 *
 * Source:    packages/contracts/openapi/public-api.yaml
 * Regenerate: cd packages/contracts && npm run generate
 *
 * Editing this file by hand makes the generated client disagree with the contract, which is the
 * exact failure this pipeline exists to prevent.
 */

`;

const ast = await openapiTS(pathToFileURL(bundle), {
  alphabetize: true,
  emptyObjectsUnknown: true,
  // A field the contract marks nullable is nullable in the generated type; silently widening
  // would hide missing data instead of forcing the consumer to handle it.
  defaultNonNullable: false,
});

mkdirSync(outDir, { recursive: true });
writeFileSync(outFile, banner + astToString(ast), 'utf8');

const lines = readFileSync(outFile, 'utf8').split('\n').length;
console.log(`generated/typescript/public-api.d.ts (${lines} lines)`);
