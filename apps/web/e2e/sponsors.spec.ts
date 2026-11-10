import { randomUUID } from "node:crypto";
import { expect, test } from "@playwright/test";

test("financial reports and milestone timeline render with real vendor components", async ({ page }) => {
  test.setTimeout(120_000);
  const errors: string[] = [];
  page.on("pageerror", (error) => errors.push(error.message));
  const unique = randomUUID();
  const registration = await page.request.post("/api/v1/auth/register", { data: {
    email: `sponsor.qa.${unique}@example.com`, password: "sponsor-test-password-2026",
    full_name: "Sponsor integration QA", workspace_name: `Sponsor QA ${unique}`,
  } });
  expect(registration.status()).toBe(201);

  const created = await page.request.post("/api/v1/projects", { data: {
    name: "Sponsor timeline QA", currency_code: "USD", total_amount: "300.00",
    starts_on: "2026-11-01", ends_on: "2026-11-30",
  } });
  expect(created.status()).toBe(201);
  const project = await created.json();
  for (const milestone of [
    { name: "Sponsor kickoff", due_on: "2026-11-12" },
    { name: "Sponsor undated review", due_on: null },
  ]) {
    const response = await page.request.post(`/api/v1/projects/${project.id}/milestones`, { data: {
      ...milestone, amount: "100.00", currency_code: "USD", trigger_kind: "on_event",
    } });
    expect(response.status()).toBe(201);
  }

  await page.goto("/app/cash-flow");
  await expect(page.getByRole("heading", { name: "Financial reports", exact: true })).toBeVisible({ timeout: 45_000 });
  await expect(page.getByTestId("finance-studio").getByText("Invoice ledger", { exact: true })).toBeVisible({ timeout: 45_000 });
  await page.getByRole("button", { name: "Cash evidence", exact: true }).click();
  await expect(page.getByTestId("finance-studio").getByText("Projection evidence", { exact: true })).toBeVisible();
  await page.getByRole("button", { name: "Customize report", exact: true }).click();
  await expect(page.getByRole("button", { name: "Finish editing", exact: true })).toBeVisible();
  await page.getByRole("button", { name: "Finish editing", exact: true }).click();

  await page.route("**/api/v1/studio/turn", async (route) => {
    const request = route.request().postDataJSON();
    expect(request.input.length).toBeGreaterThan(0);
    expect(request.tools.length).toBeGreaterThan(0);
    await route.fulfill({ json: { id: "qa-report-turn", createdAt: Date.now(), status: "completed", output: [{
      id: "qa-message", kind: "output", type: "message", role: "assistant", status: "completed",
      content: [{ type: "text", text: "Report QA: invoice face value is not confirmed cash.", annotations: [] }],
    }] } });
  });
  await page.getByRole("button", { name: "Enable report AI", exact: true }).click();
  await expect(page.getByTestId("finance-studio").locator("textarea")).toBeVisible({ timeout: 30_000 });
  await page.getByTestId("finance-studio").locator("textarea").fill("Explain this report");
  await page.getByTestId("finance-studio").locator("textarea").press("Enter");
  await expect(page.getByText("Report QA: invoice face value is not confirmed cash.", { exact: true })).toBeVisible({ timeout: 30_000 });

  // Keep the browser test deterministic; the real SDK/local server is checked separately.
  await page.route("**/api/v1/finance/background-report", async (route) => {
    await route.fulfill({ json: { run_id: "qa-render-run", report: {
      currency: "USD", horizon_days: 30, overdue_receivables: "100.00", total_receivables: "300.00",
      overdue_percent: "33.33", planned_expenses: "0.30", projected_available: null,
      alert_count: 1, excluded_projection_count: 2, warnings: ["Opening balance is unknown."],
    } } });
  });
  await page.getByRole("button", { name: "Run background report", exact: true }).click();
  await expect(page.getByTestId("background-report-result")).toContainText("33.33%");
  await expect(page.getByTestId("background-report-result")).toContainText("Unknown — opening balance required");

  await page.goto(`/app/projects/${project.id}`);
  const timeline = page.getByTestId("project-timeline");
  await expect(timeline.locator(".b-gantt")).toBeVisible({ timeout: 45_000 });
  await expect(timeline.getByText("1. Sponsor kickoff", { exact: true }).first()).toBeVisible();
  await expect(page.getByRole("heading", { name: "Milestones without due dates" })).toBeVisible();
  await expect(page.getByText(/2\. Sponsor undated review · USD 100\.00 · Not invoiced/)).toBeVisible();
  expect(errors).toEqual([]);
});
