import { test as base, expect } from "@playwright/test";
import { randomUUID, randomBytes } from "node:crypto";

export const test = base.extend<{ signedIn: void }>({
  signedIn: [
    async ({ page, request, baseURL }, runTest) => {
      const browserErrors: string[] = [];
      page.on("pageerror", (error) => browserErrors.push(error.message));
      page.on("requestfailed", (request) => {
        if (request.url().includes("/_next/"))
          browserErrors.push(`${request.url()}: ${request.failure()?.errorText || "failed"}`);
      });
      page.on("response", (response) => {
        if (response.url().includes("/_next/") && response.status() >= 400)
          browserErrors.push(`${response.url()}: HTTP ${response.status()}`);
      });
      const kc = process.env.KEYCLOAK_BASE_URL || "http://localhost:8080";
      const password = process.env.PHASE2_PASSWORD;
      if (!password) throw new Error("Real OIDC tests require the isolated test:docker stack.");
      const getAdminAuthorization = async () => {
        const response = await request.post(`${kc}/realms/master/protocol/openid-connect/token`, {
          form: { grant_type: "password", client_id: "admin-cli", username: "admin", password },
        });
        expect(response.ok()).toBeTruthy();
        return { Authorization: `Bearer ${(await response.json()).access_token}` };
      };
      await expect
        .poll(
          async () => {
            try {
              return (
                await request.get(`${kc}/realms/smart-travel/.well-known/openid-configuration`)
              ).status();
            } catch {
              return 0;
            }
          },
          { timeout: 120000 },
        )
        .toBe(200);
      const authorization = await getAdminAuthorization();
      const admin = `${kc}/admin/realms/smart-travel`;
      const clients = await request.get(`${admin}/clients?clientId=web`, {
        headers: authorization,
      });
      const client = (await clients.json())[0];
      // This fixture is confined to the isolated test realm, never the developer's realm.
      expect(new URL(kc).hostname).toBe("keycloak");
      expect(
        (
          await request.put(`${admin}/clients/${client.id}`, {
            headers: authorization,
            data: {
              ...client,
              redirectUris: [`${baseURL}/api/auth/callback/keycloak`],
              webOrigins: [baseURL],
            },
          })
        ).ok(),
      ).toBeTruthy();
      const username = `web-test-${randomUUID()}`;
      const userPassword = randomBytes(24).toString("hex");
      const created = await request.post(`${admin}/users`, {
        headers: authorization,
        data: {
          username,
          enabled: true,
          email: `${username}@example.invalid`,
          emailVerified: true,
          firstName: "Web",
          lastName: "Test",
          requiredActions: [],
          credentials: [{ type: "password", value: userPassword, temporary: false }],
        },
      });
      expect(created.status()).toBe(201);
      const userUrl = created.headers().location;
      try {
        await expect
          .poll(
            async () => {
              try {
                return (await request.get(`${baseURL}/api/health`)).status();
              } catch {
                return 0;
              }
            },
            { timeout: 120000 },
          )
          .toBe(200);
        await page.goto("/dashboard");
        await expect(page).toHaveURL(/\/login\?/);
        await page.getByRole("button", { name: "Sign in with Keycloak" }).click();
        await page.locator("#username").fill(username);
        await page.locator("#password").fill(userPassword);
        await page.locator("#kc-login").click();
        await expect(page).toHaveURL(/\/dashboard$/, { timeout: 60000 });
        await page.waitForTimeout(1_000);
        expect(browserErrors, "dashboard browser errors").toEqual([]);
        // The authenticated profile copy is intentionally visually hidden at the mobile breakpoint.
        // Waiting for it in the DOM still proves the real /me request completed before a test proceeds.
        await expect(page.getByText("Hello, Web Test!")).toBeAttached({ timeout: 60_000 });
        await runTest();
      } finally {
        // The admin access token is intentionally short-lived and can expire during a browser test.
        const removed = await request.delete(userUrl, { headers: await getAdminAuthorization() });
        expect(removed.ok()).toBeTruthy();
      }
    },
    { auto: true },
  ],
});
export { expect };
