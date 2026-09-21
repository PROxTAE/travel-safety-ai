import { spawn } from "node:child_process";
import { randomBytes } from "node:crypto";
import { fileURLToPath } from "node:url";
const cwd = fileURLToPath(new URL("../", import.meta.url));
const env = { ...process.env, PHASE2_PASSWORD: randomBytes(32).toString("hex") };
function compose(args) {
  return new Promise((resolve, reject) => {
    const child = spawn("docker", ["compose", "-f", "compose.phase2-test.yaml", ...args], {
      cwd,
      env,
      stdio: "inherit",
    });
    child.on("error", reject);
    child.on("exit", (code) =>
      code === 0 ? resolve() : reject(new Error(`Docker command failed (${code})`)),
    );
  });
}
try {
  await compose(["build", "web", "api"]);
  await compose(["run", "--rm", "--no-deps", "checks"]);
  await compose([
    "up",
    "-d",
    "--wait",
    "--wait-timeout",
    "300",
    "postgres",
    "redis",
    "keycloak",
    "api",
    "web",
  ]);
  await compose(["run", "--rm", "browser"]);
} catch (error) {
  // Keep useful startup evidence; browser traces and credential payloads are never captured.
  await compose(["logs", "--tail=40", "web", "api", "keycloak"]);
  throw error;
} finally {
  // Only this isolated project's containers are removed; shared stack and volumes are untouched.
  await compose(["down"]);
}
