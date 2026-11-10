import { CreateRecordForm } from "@/components/create-record-form";
import { serverApi } from "@/lib/api/server";
import type { Contractor, ItemList } from "@/lib/api/types";

export const instant = false;

export default async function ContractorsPage() {
  const contractors = await serverApi<ItemList<Contractor>>("/api/v1/contractors");
  return (
    <section className="flex flex-col gap-6">
      <h1 className="text-2xl font-semibold tracking-tight">Contractors</h1>
      <CreateRecordForm
        endpoint="/api/v1/contractors"
        submitLabel="Add contractor"
        fields={[
          { name: "name", label: "Name" },
          { name: "email", label: "Email", type: "email" },
          { name: "paypal_email", label: "PayPal email", type: "email", required: false },
        ]}
      />
      <ul className="flex flex-col gap-2">
        {(contractors?.items ?? []).map((contractor) => (
          <li key={contractor.id} className="rounded-xl border px-4 py-3">
            <p className="font-medium">{contractor.name}</p>
            <p className="text-sm text-muted-foreground">
              {contractor.email}
              {contractor.paypal_email ? ` · PayPal ${contractor.paypal_email}` : ""}
            </p>
          </li>
        ))}
      </ul>
    </section>
  );
}
