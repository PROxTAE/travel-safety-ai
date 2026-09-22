import { test, expect } from "./fixtures";

test("keeps the trip planner panels and preview controls responsive", async ({ page }) => {
  await page.setViewportSize({ width: 1672, height: 941 });
  await page.goto("/trips/new");

  const form = await page.locator(".trip-form").boundingBox();
  const preview = await page.locator(".route-preview").boundingBox();
  const options = await page.locator(".route-options").boundingBox();

  expect(form).not.toBeNull();
  expect(preview).not.toBeNull();
  expect(options).not.toBeNull();
  expect(form!.x + form!.width).toBeLessThanOrEqual(preview!.x);
  expect(preview!.x + preview!.width).toBeLessThanOrEqual(options!.x);
  expect(
    await page.locator(".trip-form").evaluate((element) => element.scrollWidth),
  ).toBeLessThanOrEqual(Math.ceil(form!.width));

  const mapButton = page.getByRole("button", { name: "Map", exact: true });
  const listButton = page.getByRole("button", { name: "List", exact: true });
  await expect(mapButton).toBeVisible();
  await expect(listButton).toBeVisible();
  await listButton.click();
  await expect(page.locator(".route-preview-list")).toBeVisible();
  await mapButton.click();
  await expect(page.locator(".trip-map")).toBeVisible();

  await page.setViewportSize({ width: 390, height: 844 });
  await expect(mapButton).toBeVisible();
  await expect(listButton).toBeVisible();
  const mobilePreview = await page.locator(".route-preview").boundingBox();
  const listControl = await listButton.boundingBox();
  expect(listControl!.x + listControl!.width).toBeLessThanOrEqual(
    mobilePreview!.x + mobilePreview!.width,
  );
});

test("creates and updates a trip from real geocoding, then reports the unavailable assessment dependency", async ({
  page,
}) => {
  await page.goto("/trips/new");

  const from = page.getByRole("combobox", { name: "From" });
  await from.fill("Bangkok");
  const originOption = page.getByRole("option").first();
  await expect(originOption).toContainText("Bangkok", { timeout: 30_000 });
  await originOption.getByRole("button").click();
  await page.getByRole("button", { name: "Confirm this pin" }).click();

  const to = page.getByRole("combobox", { name: "To" });
  await to.fill("Chiang Mai");
  const destinationOption = page.getByRole("option").first();
  await expect(destinationOption).toContainText("Chiang Mai", { timeout: 30_000 });
  await destinationOption.getByRole("button").click();
  await page.getByRole("button", { name: "Confirm this pin" }).click();

  const created = page.waitForResponse(
    (response) =>
      response.request().method() === "POST" &&
      response.url().includes("/api/backend/api/v1/trips") &&
      !response.url().includes("/assessments"),
  );
  const assessment = page.waitForResponse(
    (response) => response.request().method() === "POST" && response.url().includes("/assessments"),
  );
  await page.getByRole("button", { name: "Find safe routes" }).click();

  const createdResponse = await created;
  expect(createdResponse.status()).toBe(201);
  const createdBody = await createdResponse.json();
  expect(createdBody.data.origin.provider).toBe("open_meteo_geocoding");
  expect(createdBody.data.origin.confirmed_by_user).toBe(true);
  expect(createdBody.data.destination.confirmed_by_user).toBe(true);
  expect((await assessment).status()).toBe(202);

  // M03 has no runtime service yet. The public API records the real run and emits a terminal,
  // retryable dependency error rather than fabricating route options. Once M03 is available this
  // assertion is replaced by the required recommendation/route-options assertion.
  await expect(
    page.getByRole("alert").filter({ hasText: "request could not be completed" }),
  ).toContainText("request could not be completed", { timeout: 60_000 });
  await expect(
    page.getByText(/No route options are available|Route options will appear/),
  ).toBeVisible();

  const updated = page.waitForResponse(
    (response) =>
      response.request().method() === "PATCH" &&
      response.url().includes(`/api/backend/api/v1/trips/${createdBody.data.trip_id}`),
  );
  const reassessment = page.waitForResponse(
    (response) => response.request().method() === "POST" && response.url().includes("/assessments"),
  );
  await page.getByRole("checkbox", { name: "Lower cost" }).check();
  await page.getByRole("button", { name: "Find safe routes" }).click();
  expect((await updated).status()).toBe(200);
  expect((await reassessment).status()).toBe(202);
});
