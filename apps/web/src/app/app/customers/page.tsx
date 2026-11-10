import { ArchiveCustomerButton } from "@/components/archive-customer-button";
import { CreateRecordForm } from "@/components/create-record-form";
import { CustomerEditor } from "@/components/customer-editor";
import { serverApi } from "@/lib/api/server";
import type { Customer, ItemList } from "@/lib/api/types";

export const instant = false;

export default async function CustomersPage() {
  const customers = await serverApi<ItemList<Customer>>("/api/v1/customers");
  return (
    <section className="flex flex-col gap-6">
      <h1 className="text-2xl font-semibold tracking-tight">Customers</h1>
      <CreateRecordForm
        endpoint="/api/v1/customers"
        submitLabel="Add customer"
        fields={[
          { name: "name", label: "Name" },
          { name: "email", label: "Email", type: "email" },
          { name: "company_name", label: "Company", required: false },
          { name: "billing_email", label: "Billing email", type: "email", required: false },
          { name: "billing_address", label: "Billing address", required: false },
        ]}
      />
      <ul className="flex flex-col gap-2">
        {(customers?.items ?? []).map((customer) => (
          <li key={customer.id} className="flex flex-col gap-3 rounded-xl border px-4 py-3 sm:flex-row sm:items-center sm:justify-between">
            <div>
              <p className="font-medium">{customer.name}</p>
              <p className="text-sm text-muted-foreground">{customer.email}</p>
              {customer.billing_email ? (
                <p className="text-sm text-muted-foreground">Billing {customer.billing_email}</p>
              ) : null}
              {customer.billing_address ? (
                <p className="text-sm text-muted-foreground">{customer.billing_address}</p>
              ) : null}
            </div>
            <div className="flex flex-col items-start gap-2">
              <CustomerEditor customer={customer} />
              <ArchiveCustomerButton customerId={customer.id} archived={customer.archived_at !== null} />
            </div>
          </li>
        ))}
      </ul>
    </section>
  );
}
