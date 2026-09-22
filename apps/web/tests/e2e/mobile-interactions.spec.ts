import { expect, test } from "./fixtures";

const routeTimeout = 15_000;

test.describe.configure({ mode: "serial" });

test.describe("mobile shell interactions", () => {
  test.use({ viewport: { width: 390, height: 844 }, hasTouch: true, isMobile: true });

  test("keeps navigation and page actions tappable", async ({ page }) => {
    await page.goto("/safety-map");

    const navigation = page.getByRole("navigation", { name: "Primary navigation" });
    const overviewLink = navigation.getByRole("link", { name: "Overview" });
    const disclosure = page.locator(".mobile-navigation");
    const toggle = disclosure.locator("summary");

    await expect(navigation).toBeVisible();
    await expect(overviewLink).toBeVisible();
    await expect(disclosure).toHaveAttribute("open", "");
    await expect(toggle).toHaveAccessibleName("Toggle primary navigation");

    await toggle.tap();
    await expect(disclosure).not.toHaveAttribute("open", "");
    await expect(navigation).toBeHidden();

    await toggle.tap();
    await expect(disclosure).toHaveAttribute("open", "");
    await expect(navigation).toBeVisible();

    const target = await overviewLink.boundingBox();
    expect(target?.width).toBeGreaterThanOrEqual(44);
    expect(target?.height).toBeGreaterThanOrEqual(44);

    const receivesCenterTap = await overviewLink.evaluate((link) => {
      const bounds = link.getBoundingClientRect();
      const hit = document.elementFromPoint(
        bounds.left + bounds.width / 2,
        bounds.top + bounds.height / 2,
      );

      return hit === link || (hit !== null && link.contains(hit));
    });
    expect(receivesCenterTap).toBe(true);

    await overviewLink.tap();
    await expect(page).toHaveURL(/\/dashboard$/, { timeout: routeTimeout });

    await page.getByRole("link", { name: "Open Emergency Center" }).tap();
    await expect(page).toHaveURL(/\/emergency$/, { timeout: routeTimeout });

    await page.goto("/login");
    await page.getByRole("link", { name: "Continue to trip planning" }).tap();
    await expect(page).toHaveURL(/\/trips\/new$/, { timeout: routeTimeout });
  });

  test("supports keyboard activation at the mobile breakpoint", async ({ page }) => {
    await page.goto("/safety-map");

    const disclosure = page.locator(".mobile-navigation");
    const toggle = disclosure.locator("summary");
    await expect(toggle).toHaveAccessibleName("Toggle primary navigation");
    await toggle.focus();
    await expect(toggle).toBeFocused();
    await page.keyboard.press("Enter");
    await expect(disclosure).not.toHaveAttribute("open", "");
    await page.keyboard.press("Enter");
    await expect(disclosure).toHaveAttribute("open", "");

    const overviewLink = page
      .getByRole("navigation", { name: "Primary navigation" })
      .getByRole("link", { name: "Overview" });

    await overviewLink.focus();
    await expect(overviewLink).toBeFocused();
    await page.keyboard.press("Enter");
    await expect(page).toHaveURL(/\/dashboard$/, { timeout: routeTimeout });
  });
});

test.describe("desktop shell interactions", () => {
  test.use({ viewport: { width: 1280, height: 800 }, hasTouch: false, isMobile: false });

  test("keeps the desktop sidebar interactive", async ({ page }) => {
    await page.goto("/dashboard");

    await expect(page.locator(".mobile-nav")).toBeHidden();
    const sidebar = page.getByRole("complementary", { name: "Primary navigation" });
    await expect(sidebar).toBeVisible();

    await sidebar.getByRole("link", { name: "Safety Map" }).click();
    await expect(page).toHaveURL(/\/safety-map$/, { timeout: routeTimeout });
  });
});
