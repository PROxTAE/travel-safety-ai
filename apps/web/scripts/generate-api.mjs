import openapiTS, { astToString } from "openapi-typescript";
import { mkdir, writeFile, readFile } from "node:fs/promises";

const source = new URL(
  "../../../packages/contracts/generated/openapi/public-api.bundled.yaml",
  import.meta.url,
);
const target = new URL("../lib/api/generated/public-api.d.ts", import.meta.url);
const output =
  "// Generated from packages/contracts OpenAPI. Run pnpm generate:api; do not edit.\n" +
  astToString(
    await openapiTS(source, {
      alphabetize: true,
      emptyObjectsUnknown: true,
      defaultNonNullable: false,
    }),
  );
if (process.argv.includes("--check")) {
  if ((await readFile(target, "utf8")) !== output)
    throw new Error("Generated API types are out of date");
} else {
  await mkdir(new URL("../lib/api/generated/", import.meta.url), { recursive: true });
  await writeFile(target, output);
}
