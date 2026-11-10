"use client";

import { useRouter } from "next/navigation";
import { useState } from "react";

import { Button } from "@/components/ui/button";
import { ApiError, api } from "@/lib/api/client";
import type { Invoice } from "@/lib/api/types";

export function InvoiceActions({ invoice }: { invoice: Invoice }) {
  const router = useRouter();
  const [error, setError] = useState<string | null>(null);
  const [pending, setPending] = useState(false);
  const closed = ["paid", "marked_as_paid", "cancelled", "refunded"].includes(invoice.status);

  async function run(path: string) {
    setPending(true);
    setError(null);
    try {
      await api(path, { method: "POST" });
      router.refresh();
    } catch (caught) {
      setError(caught instanceof ApiError ? caught.message : "PayPal did not accept that invoice action.");
    } finally {
      setPending(false);
    }
  }

  return (
    <div className="flex flex-col gap-3">
      <div className="flex flex-wrap gap-2">
        <Button
          type="button"
          variant="outline"
          disabled={pending || !invoice.paypal_invoice_id || invoice.status !== "draft"}
          onClick={() => void run(`/api/v1/invoices/${invoice.id}/send`)}
        >
          Send invoice
        </Button>
        <Button
          type="button"
          variant="outline"
          disabled={pending || !invoice.paypal_invoice_id || closed}
          onClick={() => void run(`/api/v1/invoices/${invoice.id}/remind`)}
        >
          Send reminder now
        </Button>
        <Button
          type="button"
          variant="outline"
          disabled={pending || !invoice.paypal_invoice_id}
          onClick={() => void run(`/api/v1/invoices/${invoice.id}/sync`)}
        >
          Refresh from PayPal
        </Button>
      </div>
      {!invoice.paypal_invoice_id ? (
        <p className="text-sm text-muted-foreground">
          Send and remind stay disabled until PayPal has accepted this invoice.
        </p>
      ) : null}
      <p className="text-sm text-muted-foreground">
        Reminders sent today: {invoice.reminders_sent}. PayPal allows two reminders per invoice per day.
        A seven-day reminder is scheduled from the AI workspace, not from this form.
      </p>
      {error ? (
        <p className="text-sm text-destructive" role="alert">
          {error}
        </p>
      ) : null}
    </div>
  );
}
