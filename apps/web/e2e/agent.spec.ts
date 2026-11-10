import { randomUUID } from "node:crypto";
import { expect, test } from "@playwright/test";

test.beforeEach(async ({ page }) => {
  // Include registration and a cold development-server compile in the budget.
  test.setTimeout(120_000);
  const unique = randomUUID();
  const response = await page.request.post("/api/v1/auth/register", { data: {
    email: `agent.${unique}@example.com`, password: "agent-test-password-2026",
    full_name: "Workflow QA", workspace_name: `Workflow QA ${unique}`,
  } });
  expect(response.status()).toBe(201);
});

test("preview stays inert and confirmation creates the project exactly once", async ({ page }) => {
  const customer = await page.request.post("/api/v1/customers", { data: { name: "Acme", email: "acme.qa@example.com" } });
  expect(customer.status()).toBe(201);
  await page.goto("/app/agent");
  await page.getByLabel("Instruction", { exact: true }).fill(
    "Create a $3,000 project called Website Redesign with three payment milestones for Acme.",
  );
  await page.getByRole("button", { name: "Preview plan", exact: true }).click();
  await expect(page.getByText("Status: pending_confirmation", { exact: true })).toBeVisible();
  const before = await page.request.get("/api/v1/projects");
  expect((await before.json()).items).toHaveLength(0);
  await expect(page.getByText("3000.00", { exact: true })).toBeVisible();
  await expect(page.getByTestId("milestone-preview")).toHaveCount(3);
  for (let index = 0; index < 3; index += 1) {
    await expect(page.getByTestId("milestone-preview").nth(index)).toContainText(`Milestone ${index + 1} · USD 1000.00`);
  }

  await page.getByRole("button", { name: "Edit plan", exact: true }).click();
  await expect(page.getByRole("button", { name: "Confirm plan", exact: true })).toHaveCount(0);
  await page.getByLabel("Revised instruction").fill(
    "Create a $6,000 project called Website Redesign with three payment milestones for Acme.",
  );
  await page.getByLabel("Step 1 amount", { exact: true }).fill("6000.00");
  for (const sequence of [2, 3, 4]) {
    await page.getByLabel(`Step ${sequence} amount`, { exact: true }).fill("2000.00");
  }
  await page.getByRole("button", { name: "Save revised preview", exact: true }).click();
  await expect(page.getByText("User-reviewed plan", { exact: true })).toBeVisible();
  expect((await (await page.request.get("/api/v1/projects")).json()).items).toHaveLength(0);

  const confirmation = page.waitForResponse((response) =>
    response.url().endsWith("/confirm") && response.request().method() === "POST");
  await page.getByRole("button", { name: "Confirm plan", exact: true }).click();
  expect((await confirmation).status()).toBe(200);
  await expect(page.getByText("Status: completed", { exact: true })).toBeVisible({ timeout: 10_000 });
  await expect(page.getByRole("button", { name: "Confirm plan", exact: true })).toHaveCount(0);
  const projects = await (await page.request.get("/api/v1/projects")).json();
  expect(projects.items).toHaveLength(1);
  const detail = await (await page.request.get(`/api/v1/projects/${projects.items[0].id}`)).json();
  expect(detail.milestones).toHaveLength(3);
  expect(detail.total_amount).toBe("6000.00");
  const runs = await (await page.request.get("/api/v1/agent/runs")).json();
  expect((await page.request.post(`/api/v1/agent/runs/${runs.items[0].id}/confirm`)).status()).toBe(409);
  await page.getByText("Step result", { exact: true }).first().click();
  await expect(page.getByText(projects.items[0].id, { exact: false }).first()).toBeVisible();
});

test("waiting workflows refresh to show completion without reloading", async ({ page }) => {
  const run = {
    id: randomUUID(), instruction: "Wait for client payment", status: "waiting", provider: "test",
    provider_label: "Deterministic browser fixture", explanation: null, error_code: null,
    clarifications: [], steps: [],
  };
  await page.route("**/api/v1/agent/plans", (route) => route.fulfill({ status: 201, json: run }));
  let refreshes = 0;
  await page.route(`**/api/v1/agent/runs/${run.id}`, (route) => {
    refreshes += 1;
    return route.fulfill({ json: { ...run, status: "completed" } });
  });
  await page.goto("/app/agent");
  await page.getByRole("button", { name: "Preview plan", exact: true }).click();
  await expect(page.getByText("Status: waiting", { exact: true })).toBeVisible();
  await expect(page.getByText("Status: completed", { exact: true })).toBeVisible({ timeout: 15_000 });
  expect(refreshes).toBe(1);
});
