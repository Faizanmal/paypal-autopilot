import type { Customer, Invoice, ProjectDetail } from "./api/types.ts";
import { isOverdue, toCents } from "./money.ts";

export function chartAmount(amount: string): number | null {
  if (!/^-?\d+(?:\.\d{1,2})?$/.test(amount)) return null;
  const cents = toCents(amount);
  return Number.isSafeInteger(cents) ? cents / 100 : null;
}

export function invoiceAnalytics(invoices: Invoice[], customers: Customer[], currency: string) {
  const names = new Map(customers.map((customer) => [customer.id, customer.name]));
  const rows = invoices.flatMap((invoice) => {
    const faceValue = chartAmount(invoice.amount);
    if (invoice.currency_code !== currency || faceValue === null) return [];
    return [{
      id: invoice.id,
      customer: invoice.customer_id ? names.get(invoice.customer_id) ?? "Unassigned customer" : "Unassigned customer",
      status: invoice.status.replaceAll("_", " "),
      providerStatus: invoice.provider_status ?? "Not available",
      currency: invoice.currency_code,
      faceValue,
      exactAmount: invoice.amount,
      dueDate: invoice.due_at?.slice(0, 10) ?? "Undated",
      paymentEvidence: invoice.status === "paid" ? "Provider reports paid"
        : invoice.status === "marked_as_paid" ? "Manually marked paid"
          : "See invoice status",
    }];
  });
  return { rows, excludedCount: invoices.length - rows.length };
}

export function projectTimeline(project: ProjectDetail, invoices: Invoice[], now = Date.now()) {
  const tasks = [];
  const undated = [];
  const relatedInvoices = invoices.filter((invoice) => invoice.project_id === project.id);
  for (const milestone of [...project.milestones].sort((a, b) => a.sequence - b.sequence)) {
    const invoice = relatedInvoices.find((item) => item.id === milestone.invoice_id || item.milestone_id === milestone.id);
    const paymentStatus = invoice?.status.replaceAll("_", " ") ?? "Not invoiced";
    const needsAttention = invoice ? isOverdue(invoice.status, invoice.due_at, now) : false;
    const row = {
      id: milestone.id,
      name: `${milestone.sequence}. ${milestone.name}`,
      amountLabel: `${milestone.currency_code} ${milestone.amount}`,
      workStatus: milestone.status.replaceAll("_", " "),
      paymentStatus,
      attention: needsAttention ? "Overdue invoice" : "",
      cls: needsAttention ? "payment-attention" : "",
      manuallyScheduled: true,
      readOnly: true,
      duration: 0,
    };
    // No artificial start date for an undated milestone, and no inferred dependencies.
    if (!milestone.due_on || !/^\d{4}-\d{2}-\d{2}$/.test(milestone.due_on)) {
      undated.push(row);
    } else {
      tasks.push({ ...row, startDate: milestone.due_on });
    }
  }
  return { tasks, undated };
}
