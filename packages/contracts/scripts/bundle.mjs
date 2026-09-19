#!/usr/bin/env node
// Bundles openapi/public-api.yaml into a single self-contained document and normalises it for
// the code generators.
//
// The entity schemas are plain JSON Schema files, so bundling drags two JSON-Schema-only keywords
// into `components.schemas`: `$schema`, and `$defs` blocks that redocly already rewrote into
// sibling components. Both are legal OpenAPI 3.1 but confuse datamodel-code-generator, which reads
// a `$schema` URL as a modular reference and refuses to write a single file. Stripping them here
// keeps one bundling step instead of a workaround in each generator.
//
// Usage: node scripts/bundle.mjs

import { execFileSync } from 'node:child_process';
import { mkdirSync, readFileSync, writeFileSync } from 'node:fs';
import { join, dirname } from 'node:path';
import { fileURLToPath } from 'node:url';

import { parse, stringify } from 'yaml';

const here = dirname(fileURLToPath(import.meta.url));
const root = join(here, '..');
const source = join(root, 'openapi', 'public-api.yaml');
const outDir = join(root, 'generated', 'openapi');
const outFile = join(outDir, 'public-api.bundled.yaml');

mkdirSync(outDir, { recursive: true });

// Spawn the CLI's JS entrypoint with this Node rather than the `npx` shim: Node 24 refuses to
// spawn a .cmd without a shell, and going through a shell would mean quoting the path by hand.
const redoclyCli = join(
  dirname(fileURLToPath(import.meta.resolve('@redocly/cli/package.json'))),
  'bin',
  'cli.js',
);

execFileSync(process.execPath, [redoclyCli, 'bundle', source, '--output', outFile], {
  cwd: root,
  stdio: ['ignore', 'ignore', 'inherit'],
});

const document = parse(readFileSync(outFile, 'utf8'));

// Refuse to strip a $defs block that something still points at, rather than silently breaking it.
const refs = new Set();
(function walk(node) {
  if (Array.isArray(node)) return node.forEach(walk);
  if (node && typeof node === 'object') {
    if (typeof node.$ref === 'string') refs.add(node.$ref);
    for (const value of Object.values(node)) walk(value);
  }
})(document);

const danglingDefsRefs = [...refs].filter((ref) => ref.includes('/$defs/'));
if (danglingDefsRefs.length > 0) {
  console.error('Bundle still contains $defs references, which would break after normalisation:');
  for (const ref of danglingDefsRefs) console.error(`  ${ref}`);
  process.exit(1);
}

let removed = 0;
(function strip(node) {
  if (Array.isArray(node)) return node.forEach(strip);
  if (node && typeof node === 'object') {
    for (const key of ['$schema', '$defs']) {
      if (key in node) {
        delete node[key];
        removed += 1;
      }
    }
    for (const value of Object.values(node)) strip(value);
  }
})(document.components ?? {});

// A component that points at a whole entity file comes back as a pair: the name we chose, holding
// only a `$ref`, plus a second component named after the source file (`consent-record.schema`)
// holding the body. The dot makes datamodel-code-generator read that name as a module path and
// refuse to emit a single file, and it leaves consumers with two names for one type. Move each body
// onto the name we chose and drop the file-derived one.
const schemas = document.components?.schemas ?? {};
const aliases = new Map();

for (const [name, schema] of Object.entries(schemas)) {
  if (name.includes('.')) continue;
  const keys = Object.keys(schema ?? {});
  if (keys.length !== 1 || keys[0] !== '$ref') continue;

  const target = schema.$ref.replace('#/components/schemas/', '');
  if (!target.includes('.') || !(target in schemas)) continue;

  schemas[name] = schemas[target];
  aliases.set(`#/components/schemas/${target}`, `#/components/schemas/${name}`);
  delete schemas[target];
}

const orphans = Object.keys(schemas).filter((name) => name.includes('.'));
if (orphans.length > 0) {
  console.error('Bundled components still carry file-derived names, which the generators cannot use:');
  for (const name of orphans) console.error(`  ${name}`);
  console.error('Give each one an explicit entry under components.schemas in openapi/public-api.yaml.');
  process.exit(1);
}

if (aliases.size > 0) {
  (function rewrite(node) {
    if (Array.isArray(node)) return node.forEach(rewrite);
    if (node && typeof node === 'object') {
      if (typeof node.$ref === 'string' && aliases.has(node.$ref)) {
        node.$ref = aliases.get(node.$ref);
      }
      for (const value of Object.values(node)) rewrite(value);
    }
  })(document);
}

const banner = `# GENERATED FILE - DO NOT EDIT.
#
# Source:     packages/contracts/openapi/public-api.yaml
# Regenerate: cd packages/contracts && npm run generate
#
# This is the self-contained form of the public contract. Both the TypeScript and the Python
# clients are generated from this file, so they cannot drift apart.

`;

writeFileSync(outFile, banner + stringify(document, { lineWidth: 100 }), 'utf8');
console.log(
  `generated/openapi/public-api.bundled.yaml (removed ${removed} JSON-Schema-only keys, ` +
    `folded ${aliases.size} duplicate component name(s))`,
);
