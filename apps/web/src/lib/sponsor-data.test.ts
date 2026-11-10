import assert from "node:assert/strict";
import test from "node:test";

import type { Invoice, ProjectDetail } from "./api/types.ts";
import { chartAmount, invoiceAnalytics, projectTimeline } from "./sponsor-data.ts";

const invoice = {
  id: "invoice-1", project_id: "project-1", milestone_id: "milestone-1", customer_id: null,
  currency_code: "USD", amount: "1200.10", status: "sent", provider_status: "SENT",
  due_at: "2026-11-01T00:00:00Z",
} as Invoice;

test("analytics retains exact amounts and excludes foreign currency and invalid values", () => {
  const { rows, excludedCount } = invoiceAnalytics([
    invoice, { ...invoice, currency_code: "EUR" }, { ...invoice, amount: "not money" },
  ], [], "USD");
  assert.equal(rows.length, 1);
  assert.equal(rows[0].exactAmount, "1200.10");
  assert.equal(rows[0].faceValue, 1200.1);
  assert.equal(rows[0].paymentEvidence, "See invoice status");
  assert.equal(excludedCount, 2);
  assert.equal(chartAmount("999999999999999999999.00"), null);
});

test("manual payment evidence stays distinct from provider-paid status", () => {
  const { rows } = invoiceAnalytics([
    { ...invoice, status: "marked_as_paid" }, { ...invoice, status: "paid" },
  ], [], "USD");
  assert.equal(rows[0].paymentEvidence, "Manually marked paid");
  assert.equal(rows[1].paymentEvidence, "Provider reports paid");
});

test("timeline preserves due dates, separates undated work, and never invents dependencies", () => {
  const project = {
    id: "project-1",
    milestones: [
      { id: "milestone-2", sequence: 2, name: "Undated", status: "draft", due_on: null, amount: "100.00", currency_code: "USD" },
      { id: "milestone-1", sequence: 1, name: "Design", status: "accepted", due_on: "2026-11-05", amount: "1200.10", currency_code: "USD" },
    ],
  } as ProjectDetail;
  const { tasks, undated } = projectTimeline(project, [invoice], Date.parse("2026-11-09T12:00:00Z"));
  assert.equal(tasks.length, 1);
  assert.equal(tasks[0].startDate, "2026-11-05");
  assert.equal(tasks[0].attention, "Overdue invoice");
  assert.equal(tasks[0].workStatus, "accepted");
  assert.equal(tasks[0].paymentStatus, "sent");
  assert.equal(undated[0].name, "2. Undated");
  assert.equal("startDate" in undated[0], false);
  assert.equal("dependencies" in tasks[0], false);
  assert.equal(projectTimeline(project, [{ ...invoice, status: "paid" }]).tasks[0].attention, "");
});
