import { CreateRecordForm } from "@/components/create-record-form";
import { EmptyState } from "@/components/empty-state";
import { InvoiceBrowser } from "@/components/invoice-browser";
import { PageHeader } from "@/components/page-header";
import { serverApi } from "@/lib/api/server";
import type { Customer, Invoice, ItemList } from "@/lib/api/types";

export const instant = false;

export default async function InvoicesPage() {
  const [invoices, customers] = await Promise.all([
    serverApi<ItemList<Invoice>>("/api/v1/invoices"),
    serverApi<ItemList<Customer>>("/api/v1/customers"),
  ]);
  const items = invoices?.items ?? [];
  const active = (customers?.items ?? []).filter((customer) => customer.archived_at === null);

  return (
    <section className="flex animate-in flex-col gap-8 fade-in duration-300">
      <PageHeader
        eyebrow="Receivables"
        title="Invoices"
        description="Creating an invoice calls the PayPal sandbox. If PayPal does not return an id, the row stays local and is marked with the provider error."
      />
      {active.length === 0 ? (
        <EmptyState title="Add a customer first" detail="An invoice needs a customer in this workspace." />
      ) : (
        <CreateRecordForm
          endpoint="/api/v1/invoices"
          submitLabel="Create invoice"
          fields={[
            {
              name: "customer_id",
              label: "Customer",
              type: "select",
              options: active.map((customer) => ({ value: customer.id, label: customer.name })),
            },
            { name: "amount", label: "Amount" },
            { name: "currency_code", label: "Currency", defaultValue: "USD" },
            { name: "description", label: "Description", defaultValue: "Services" },
          ]}
        />
      )}
      {items.length === 0 ? (
        <EmptyState title="No invoices" detail="Invoices you create, or that an accepted milestone prepares, are listed here." />
      ) : (
        <InvoiceBrowser invoices={items} customers={customers?.items ?? []} />
      )}
    </section>
  );
}
