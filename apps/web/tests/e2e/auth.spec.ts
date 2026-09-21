import { test, expect } from "./fixtures";
test("real profile, HttpOnly session, and logout", async ({ page, context }) => {
  await expect(page.getByText("Hello, Web Test!")).toBeVisible();
  const profile = await page.request.get("/api/backend/api/v1/me");
  expect(profile.status()).toBe(200);
  const body = await profile.json();
  expect(body.data.display_name).toBe("Web Test");
  expect(body.data.user_id).toMatch(/^[0-9a-f-]{36}$/);
  const publicSession = await (await page.request.get("/api/auth/session")).json();
  expect(JSON.stringify(publicSession)).not.toMatch(
    /accessToken|refreshToken|access_token|refresh_token/,
  );
  expect(
    (await context.cookies())
      .filter((cookie) => cookie.name.includes("session-token"))
      .every((cookie) => cookie.httpOnly),
  ).toBe(true);
  expect(await page.evaluate(() => Object.keys(localStorage))).toEqual([]);
  await page.getByRole("button", { name: "Sign out" }).click();
  await expect
    .poll(async () => (await page.request.get("/api/backend/api/v1/me")).status(), {
      timeout: 30_000,
    })
    .toBe(401);
  await page.goto("/dashboard");
  await expect(page).toHaveURL(/\/login\?/, { timeout: 30_000 });
  await page.goto("/emergency");
  await expect(page).toHaveURL(/\/emergency$/);
});
