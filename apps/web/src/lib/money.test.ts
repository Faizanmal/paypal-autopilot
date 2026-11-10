import assert from "node:assert/strict";
import test from "node:test";

import { fromCents, isOverdue, sumAmounts, toCents } from "./money.ts";

test("sums decimal invoice amounts without binary fractions", () => {
  assert.equal(toCents("10.10"), 1010);
  assert.equal(fromCents(1010), "10.10");
  assert.equal(sumAmounts(["10.10", "0.20", "1.00"]), "11.30");
});

test("treats a sent invoice past its due date as overdue", () => {
  const due = new Date("2026-01-01T00:00:00Z").toISOString();
  assert.equal(isOverdue("sent", due, Date.parse("2026-02-01T00:00:00Z")), true);
  assert.equal(isOverdue("paid", due, Date.parse("2026-02-01T00:00:00Z")), false);
  assert.equal(isOverdue("draft", due, Date.parse("2026-02-01T00:00:00Z")), false);
  assert.equal(isOverdue("sent", null), false);
});
