import Link from "next/link";
import { notFound } from "next/navigation";

import { InvoiceActions } from "@/components/invoice-actions";
import { PageHeader } from "@/components/page-header";
import { StatusBadge } from "@/components/status-badge";
import { serverApi } from "@/lib/api/server";
import type { Customer, Invoice, ItemList, PaymentRecord } from "@/lib/api/types";
import { money } from "@/lib/money";

export const instant = false;

export default async function InvoiceDetailPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  const [invoice, payments, customers] = await Promise.all([
    serverApi<Invoice>(`/api/v1/invoices/${id}`),
    serverApi<ItemList<PaymentRecord>>(`/api/v1/invoices/${id}/payments`),
    serverApi<ItemList<Customer>>("/api/v1/customers"),
  ]);
  if (!invoice) {
    notFound();
  }
  const customer = (customers?.items ?? []).find((item) => item.id === invoice.customer_id);

  return (
    <section className="flex animate-in flex-col gap-8 fade-in duration-300">
      <div>
        <Link href="/app/invoices" className="text-sm text-muted-foreground hover:underline">
          Invoices
        </Link>
        <PageHeader
          title={customer?.name ?? "Invoice"}
          description={`${money(invoice.currency_code, invoice.amount)}. Provider status is shown separately from the workspace status.`}
        />
      </div>
      <div className="flex flex-wrap items-center gap-2">
        <StatusBadge status={invoice.status} />
        {invoice.provider_status ? <StatusBadge status={invoice.provider_status.toLowerCase()} /> : null}
      </div>
      <dl className="grid gap-4 rounded-xl border bg-card p-4 sm:grid-cols-2">
        <div>
          <dt className="text-sm text-muted-foreground">PayPal invoice</dt>
          <dd className="text-sm">{invoice.paypal_invoice_id ?? "Not created"}</dd>
        </div>
        <div>
          <dt className="text-sm text-muted-foreground">Due</dt>
          <dd className="text-sm">
            {invoice.due_at
              ? `${new Date(invoice.due_at).toLocaleString("en-US", { timeZone: "UTC" })} UTC`
              : "No due date stored"}
          </dd>
        </div>
        <div>
          <dt className="text-sm text-muted-foreground">Last sync</dt>
          <dd className="text-sm">
            {invoice.last_synced_at
              ? `${new Date(invoice.last_synced_at).toLocaleString("en-US", { timeZone: "UTC" })} UTC`
              : "Not synced"}
          </dd>
        </div>
        <div>
          <dt className="text-sm text-muted-foreground">Hosted invoice</dt>
          <dd className="text-sm">
            {invoice.hosted_url ? (
              <a href={invoice.hosted_url} className="underline-offset-4 hover:underline" rel="noreferrer">
                Open PayPal invoice
              </a>
            ) : (
              "PayPal has not returned a hosted link"
            )}
          </dd>
        </div>
      </dl>
      {invoice.last_provider_error ? (
        <p className="rounded-xl border border-destructive/30 bg-destructive/5 px-4 py-3 text-sm" role="alert">
          {invoice.last_provider_error}
        </p>
      ) : null}
      <InvoiceActions invoice={invoice} />
      <section className="flex flex-col gap-3">
        <h2 className="text-lg font-semibold">Payment history</h2>
        {(payments?.items ?? []).length === 0 ? (
          <p className="text-sm text-muted-foreground">
            No payment has been recorded. A missing webhook is not treated as unpaid; use Refresh from PayPal to read the provider.
          </p>
        ) : (
          <ul className="flex flex-col gap-2">
            {(payments?.items ?? []).map((payment) => (
              <li key={payment.id} className="rounded-xl border px-4 py-3 text-sm">
                <p className="font-medium">{money(payment.currency_code, payment.amount)}</p>
                <p className="text-muted-foreground">
                  {payment.source} · {payment.external_id} ·{" "}
                  {new Date(payment.received_at).toLocaleString("en-US", { timeZone: "UTC" })} UTC
                </p>
              </li>
            ))}
          </ul>
        )}
      </section>
    </section>
  );
}
