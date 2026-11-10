import { expect, test } from "@playwright/test";

test("register page is keyboard reachable and can switch theme", async ({ page }) => {
  await page.goto("/register");
  await expect(page.getByRole("heading", { name: "Create a workspace" })).toBeVisible();
  await page.keyboard.press("Tab");
  await expect(page.getByRole("link", { name: "Skip to content" })).toBeFocused();
  await page.keyboard.press("Enter");
  await expect(page.locator("#content")).toBeInViewport();
  await expect(page.getByRole("button", { name: "Create workspace" })).toBeEnabled();

  const toggle = page.getByRole("button", { name: "Dark mode" });
  await toggle.click();
  await expect(page.locator("html")).toHaveClass(/dark/);
  await expect(page.getByRole("button", { name: "Light mode" })).toHaveAttribute(
    "aria-pressed",
    "true",
  );
});

test("workspace routes require a session", async ({ page }) => {
  for (const path of ["/app", "/app/invoices"]) {
    await page.goto(path);
    await expect(page).toHaveURL(/\/login$/);
    await expect(page.getByRole("heading", { name: "Sign in" })).toBeVisible();
  }
});

test("registration opens the workspace", async ({ page }) => {
  await page.goto("/register");
  await page.getByLabel("Your name").fill("Ada Lovelace");
  await page.getByLabel("Workspace name").fill("Ledger Studio");
  await page.getByLabel("Email").fill(`ada.e2e.${Date.now()}@example.com`);
  await page.getByLabel("Password").fill("correct-horse-battery");
  const submit = page.getByRole("button", { name: "Create workspace" });
  await expect(submit).toBeEnabled();
  await submit.click();
  await expect(page.getByRole("heading", { name: "Overview" })).toBeVisible({ timeout: 20_000 });
});
