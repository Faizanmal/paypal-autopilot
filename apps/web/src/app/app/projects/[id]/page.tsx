import Link from "next/link";

import { MilestoneActions } from "@/components/milestone-actions";
import { MilestoneForm } from "@/components/milestone-form";
import { ProjectTimeline } from "@/components/sponsors/project-timeline";
import { serverApi } from "@/lib/api/server";
import type { Customer, Invoice, ItemList, ProjectDetail } from "@/lib/api/types";

export const instant = false;

export default async function ProjectDetailPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  const [project, customers, invoices] = await Promise.all([
    serverApi<ProjectDetail>(`/api/v1/projects/${id}`),
    serverApi<ItemList<Customer>>("/api/v1/customers"),
    serverApi<ItemList<Invoice>>("/api/v1/invoices"),
  ]);
  if (!project) {
    return null;
  }
  const customer = (customers?.items ?? []).find((item) => item.id === project.customer_id);
  return (
    <section className="flex flex-col gap-6">
      <div>
        <p className="text-sm text-muted-foreground">
          <Link href="/app/projects" className="hover:underline">
            Projects
          </Link>
        </p>
        <h1 className="text-2xl font-semibold tracking-tight">{project.name}</h1>
        <p className="mt-2 text-sm text-muted-foreground">
          {project.currency_code} {project.total_amount} · {project.status}
          {customer ? ` · ${customer.name}` : ""}
          {project.starts_on ? ` · ${project.starts_on}` : ""}
          {project.ends_on ? ` to ${project.ends_on}` : ""}
        </p>
        {customer?.billing_email ? (
          <p className="text-sm text-muted-foreground">Billed to {customer.billing_email}</p>
        ) : null}
      </div>
      <dl className="grid gap-3 rounded-xl border p-4 sm:grid-cols-4">
        <div>
          <dt className="text-sm text-muted-foreground">Project total</dt>
          <dd>
            {project.progress.currency_code} {project.progress.project_total}
          </dd>
        </div>
        <div>
          <dt className="text-sm text-muted-foreground">Invoiced</dt>
          <dd>{project.progress.invoiced_amount}</dd>
        </div>
        <div>
          <dt className="text-sm text-muted-foreground">Paid</dt>
          <dd>{project.progress.paid_amount}</dd>
        </div>
        <div>
          <dt className="text-sm text-muted-foreground">Remaining</dt>
          <dd>{project.progress.remaining_amount}</dd>
        </div>
      </dl>
      <ProjectTimeline project={project} invoices={invoices?.items ?? []} />
      <section className="flex flex-col gap-2">
        <h2 className="text-lg font-semibold">Related invoices</h2>
        {(invoices?.items ?? []).filter((invoice) => invoice.project_id === project.id).length === 0 ? (
          <p className="text-sm text-muted-foreground">No invoice is linked to this project yet.</p>
        ) : (
          <ul className="flex flex-col gap-2">
            {(invoices?.items ?? [])
              .filter((invoice) => invoice.project_id === project.id)
              .map((invoice) => (
                <li key={invoice.id}>
                  <Link href={`/app/invoices/${invoice.id}`} className="text-sm underline-offset-4 hover:underline">
                    {invoice.currency_code} {invoice.amount} · {invoice.status}
                  </Link>
                </li>
              ))}
          </ul>
        )}
      </section>
      <ul className="flex flex-col gap-3">
        {project.milestones.map((milestone) => (
          <li key={milestone.id} className="flex flex-col gap-3 rounded-xl border px-4 py-3 sm:flex-row sm:items-center sm:justify-between">
            <div>
              <p className="font-medium">
                {milestone.sequence}. {milestone.name}
              </p>
              <p className="text-sm text-muted-foreground">
                {milestone.currency_code} {milestone.amount} · {milestone.status}
                {milestone.due_on ? ` · due ${milestone.due_on}` : ""}
              </p>
              {milestone.acceptance_condition ? (
                <p className="text-sm text-muted-foreground">Acceptance: {milestone.acceptance_condition}</p>
              ) : null}
              {milestone.paypal_invoice_id ? (
                <p className="text-sm text-muted-foreground">PayPal invoice {milestone.paypal_invoice_id}</p>
              ) : null}
            </div>
            <MilestoneActions milestoneId={milestone.id} status={milestone.status} />
          </li>
        ))}
      </ul>
      <MilestoneForm projectId={project.id} currencyCode={project.currency_code} />
    </section>
  );
}
