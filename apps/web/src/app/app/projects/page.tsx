import Link from "next/link";

import { CreateRecordForm } from "@/components/create-record-form";
import { serverApi } from "@/lib/api/server";
import type { Customer, ItemList, Project } from "@/lib/api/types";

export const instant = false;

export default async function ProjectsPage() {
  const [projects, customers] = await Promise.all([
    serverApi<ItemList<Project>>("/api/v1/projects"),
    serverApi<ItemList<Customer>>("/api/v1/customers"),
  ]);
  const activeCustomers = (customers?.items ?? []).filter((customer) => customer.archived_at === null);
  const customerName = new Map((customers?.items ?? []).map((customer) => [customer.id, customer.name]));
  return (
    <section className="flex flex-col gap-6">
      <div>
        <h1 className="text-2xl font-semibold tracking-tight">Projects</h1>
        <p className="mt-2 text-sm text-muted-foreground">
          Amounts are decimal strings. The API rejects a milestone total that exceeds the project.
        </p>
      </div>
      <CreateRecordForm
        endpoint="/api/v1/projects"
        submitLabel="Create project"
        fields={[
          { name: "name", label: "Name" },
          {
            name: "customer_id",
            label: "Customer",
            type: "select",
            required: false,
            options: activeCustomers.map((customer) => ({ value: customer.id, label: customer.name })),
          },
          { name: "currency_code", label: "Currency", defaultValue: "USD" },
          { name: "total_amount", label: "Total amount" },
          { name: "starts_on", label: "Starts", type: "date", required: false },
          { name: "ends_on", label: "Ends", type: "date", required: false },
        ]}
      />
      <ul className="flex flex-col gap-2">
        {(projects?.items ?? []).map((project) => (
          <li key={project.id} className="rounded-xl border px-4 py-3">
            <Link href={`/app/projects/${project.id}`} className="font-medium hover:underline">
              {project.name}
            </Link>
            <p className="text-sm text-muted-foreground">
              {project.currency_code} {project.total_amount} · {project.status}
              {project.customer_id ? ` · ${customerName.get(project.customer_id) ?? "Customer"}` : ""}
              {project.starts_on ? ` · ${project.starts_on}` : ""}
              {project.ends_on ? ` to ${project.ends_on}` : ""}
            </p>
          </li>
        ))}
      </ul>
    </section>
  );
}
