"use client";

import Link from "next/link";
import { useState } from "react";

import { StatusBadge } from "@/components/status-badge";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import type { Customer, Invoice } from "@/lib/api/types";
import { isOverdue, money } from "@/lib/money";

export function InvoiceBrowser({ invoices, customers }: { invoices: Invoice[]; customers: Customer[] }) {
  const [query, setQuery] = useState("");
  const [status, setStatus] = useState("all");
  const names = new Map(customers.map((customer) => [customer.id, customer.name]));
  const statuses = ["all", ...new Set(invoices.map((invoice) => invoice.status))];
  const visible = invoices.filter((invoice) => {
    const name = invoice.customer_id ? (names.get(invoice.customer_id) ?? "") : "";
    const haystack = `${name} ${invoice.amount} ${invoice.paypal_invoice_id ?? ""}`.toLowerCase();
    const matchesQuery = haystack.includes(query.trim().toLowerCase());
    const matchesStatus =
      status === "all" || (status === "overdue" ? isOverdue(invoice.status, invoice.due_at) : invoice.status === status);
    return matchesQuery && matchesStatus;
  });

  return (
    <div className="flex flex-col gap-4">
      <div className="grid gap-3 sm:grid-cols-[minmax(0,1fr)_12rem]">
        <div className="flex flex-col gap-1.5">
          <Label htmlFor="invoice-search">Search</Label>
          <Input
            id="invoice-search"
            value={query}
            onChange={(event) => setQuery(event.target.value)}
            placeholder="Customer, amount, or PayPal id"
          />
        </div>
        <div className="flex flex-col gap-1.5">
          <Label htmlFor="invoice-status">Status</Label>
          <select
            id="invoice-status"
            value={status}
            onChange={(event) => setStatus(event.target.value)}
            className="h-8 rounded-lg border border-input bg-transparent px-2.5 text-sm"
          >
            {statuses.map((item) => (
              <option key={item} value={item}>
                {item === "all" ? "All statuses" : item.replaceAll("_", " ")}
              </option>
            ))}
            <option value="overdue">Overdue</option>
          </select>
        </div>
      </div>
      {visible.length === 0 ? (
        <p className="text-sm text-muted-foreground">No invoices match this filter.</p>
      ) : (
        <ul className="flex flex-col gap-2">
          {visible.map((invoice) => (
            <li key={invoice.id}>
              <Link
                href={`/app/invoices/${invoice.id}`}
                className="flex flex-col gap-2 rounded-xl border px-4 py-3 transition-colors hover:bg-muted sm:flex-row sm:items-center sm:justify-between"
              >
                <span>
                  <span className="font-medium">
                    {invoice.customer_id ? (names.get(invoice.customer_id) ?? "Customer") : "No customer"}
                  </span>
                  <span className="mt-1 block text-sm text-muted-foreground">
                    {money(invoice.currency_code, invoice.amount)}
                    {invoice.paypal_invoice_id ? ` · ${invoice.paypal_invoice_id}` : " · not in PayPal"}
                    {isOverdue(invoice.status, invoice.due_at) ? " · overdue" : ""}
                  </span>
                </span>
                <StatusBadge status={invoice.status} />
              </Link>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
