import Link from "next/link";

import { EmptyState } from "@/components/empty-state";
import { PageHeader } from "@/components/page-header";
import { StatusBadge } from "@/components/status-badge";
import { serverApi } from "@/lib/api/server";
import type { AgentRun, FinanceSnapshot, ItemList, Project } from "@/lib/api/types";
import { money } from "@/lib/money";

export const instant = false;

export default async function OverviewPage() {
  const [snapshot, runs, projects] = await Promise.all([
    serverApi<FinanceSnapshot>("/api/v1/finance/snapshot"),
    serverApi<ItemList<AgentRun>>("/api/v1/agent/runs"),
    serverApi<ItemList<Project>>("/api/v1/projects"),
  ]);
  const currency = snapshot?.currency ?? "USD";
  const cards = [
    { label: "Receivables", value: snapshot ? money(currency, snapshot.outstanding_receivables) : "Unavailable", href: "/app/invoices" },
    { label: "Confirmed paid", value: snapshot ? money(currency, snapshot.total_paid) : "Unavailable", href: "/app/invoices" },
    { label: "Overdue", value: snapshot ? money(currency, snapshot.overdue_receivables) : "Unavailable", href: "/app/invoices" },
    {
      label: "Pending approvals",
      value: snapshot ? String(snapshot.pending_approval_count) : "Unavailable",
      href: "/app/approvals",
    },
    {
      label: "Upcoming obligations",
      value: snapshot ? money(currency, snapshot.pending_contractor_obligations) : "Unavailable",
      href: "/app/payouts",
    },
    { label: "Projects", value: String(projects?.items.length ?? 0), href: "/app/projects" },
  ];

  return (
    <section className="flex animate-in flex-col gap-8 fade-in duration-300">
      <PageHeader
        eyebrow="Workspace"
        title="Overview"
        description="Receivables, paid cash, and obligations come from the cash snapshot. Expected invoices are not shown here as money received."
      />
      <dl className="grid gap-3 sm:grid-cols-2 xl:grid-cols-3">
        {cards.map((card) => (
          <div key={card.label} className="rounded-xl border bg-card p-4">
            <dt className="text-sm text-muted-foreground">{card.label}</dt>
            <dd className="mt-2 text-2xl font-semibold tracking-tight">{card.value}</dd>
            <dd className="mt-3">
              <Link href={card.href} className="text-sm underline-offset-4 hover:underline">
                View
              </Link>
            </dd>
          </div>
        ))}
      </dl>
      <div className="grid gap-6 lg:grid-cols-2">
        <section className="flex flex-col gap-3">
          <h2 className="text-lg font-semibold">Insights</h2>
          {(snapshot?.insights.length ?? 0) === 0 ? (
            <p className="text-sm text-muted-foreground">No insight met the calculated thresholds.</p>
          ) : (
            <ul className="flex flex-col gap-2">
              {snapshot?.insights.slice(0, 3).map((insight) => (
                <li key={`${insight.kind}-${insight.message}`} className="rounded-xl border px-4 py-3 text-sm">
                  {insight.message}
                </li>
              ))}
            </ul>
          )}
          <Link href="/app/cash-flow" className="text-sm underline-offset-4 hover:underline">
            Open cash flow
          </Link>
        </section>
        <section className="flex flex-col gap-3">
          <h2 className="text-lg font-semibold">Recent agent actions</h2>
          {(runs?.items ?? []).length === 0 ? (
            <EmptyState title="No agent runs yet" detail="A plan appears here after you preview an instruction." />
          ) : (
            <ul className="flex flex-col gap-2">
              {(runs?.items ?? []).slice(0, 5).map((run) => (
                <li key={run.id} className="rounded-xl border px-4 py-3">
                  <div className="flex items-start justify-between gap-3">
                    <p className="text-sm">{run.instruction}</p>
                    <StatusBadge status={run.status} />
                  </div>
                </li>
              ))}
            </ul>
          )}
        </section>
      </div>
    </section>
  );
}
