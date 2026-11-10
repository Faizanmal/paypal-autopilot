import Link from "next/link";

import { EmptyState } from "@/components/empty-state";
import { PageHeader } from "@/components/page-header";
import { ScheduleControls } from "@/components/schedule-controls";
import { StatusBadge } from "@/components/status-badge";
import { serverApi } from "@/lib/api/server";
import type { ItemList, ScheduledAction, WorkflowRecord } from "@/lib/api/types";

export const instant = false;

export default async function AutomationsPage() {
  const [workflows, actions] = await Promise.all([
    serverApi<ItemList<WorkflowRecord>>("/api/v1/workflows"),
    serverApi<ItemList<ScheduledAction>>("/api/v1/scheduled-actions"),
  ]);
  const runs = workflows?.items ?? [];
  const scheduled = actions?.items ?? [];

  return (
    <section className="flex animate-in flex-col gap-8 fade-in duration-300">
      <PageHeader
        eyebrow="Workflows"
        title="Automations"
        description="Workflows are the confirmed agent plans. Scheduled rows are reminders, due checks, and overdue notices. Pause only affects a pending schedule."
      />
      <section className="flex flex-col gap-3">
        <h2 className="text-lg font-semibold">Active workflows</h2>
        {runs.length === 0 ? (
          <EmptyState title="No workflows" detail="Confirming an agent plan creates a workflow and its steps." />
        ) : (
          <ul className="flex flex-col gap-3">
            {runs.map((workflow) => (
              <li key={workflow.id} className="rounded-xl border px-4 py-3">
                <div className="flex flex-wrap items-center justify-between gap-2">
                  <p className="text-sm font-medium">Workflow {workflow.id.slice(0, 8)}</p>
                  <StatusBadge status={workflow.status} />
                </div>
                {workflow.agent_run_id ? (
                  <p className="mt-2 text-sm">
                    <Link href="/app/agent" className="underline-offset-4 hover:underline">
                      Open the agent run to retry or cancel
                    </Link>
                  </p>
                ) : (
                  <p className="mt-2 text-sm text-muted-foreground">This workflow has no agent run to cancel.</p>
                )}
                <ol className="mt-3 flex flex-col gap-2">
                  {workflow.steps.map((step) => (
                    <li key={step.sequence} className="text-sm">
                      <span className="font-medium">
                        {step.sequence}. {step.step_type.replaceAll("_", " ")}
                      </span>
                      <span className="text-muted-foreground"> · {step.status}</span>
                      {step.condition ? <span className="text-muted-foreground"> · {step.condition}</span> : null}
                      {step.waiting_for ? <span className="text-muted-foreground"> · waiting for {step.waiting_for}</span> : null}
                      {step.provider_reference ? <span className="text-muted-foreground"> · {step.provider_reference}</span> : null}
                      {step.error ? <span className="block text-destructive">{step.error}</span> : null}
                    </li>
                  ))}
                </ol>
              </li>
            ))}
          </ul>
        )}
      </section>
      <section className="flex flex-col gap-3">
        <h2 className="text-lg font-semibold">Scheduled actions</h2>
        {scheduled.length === 0 ? (
          <EmptyState title="Nothing scheduled" detail="A confirmed reminder, or an invoice with a due date, creates a scheduled action." />
        ) : (
          <ul className="flex flex-col gap-3">
            {scheduled.map((action) => (
              <li key={action.id} className="flex flex-col gap-3 rounded-xl border px-4 py-3 sm:flex-row sm:items-center sm:justify-between">
                <div>
                  <p className="text-sm font-medium">{action.job_type.replaceAll("_", " ")}</p>
                  <p className="text-sm text-muted-foreground">
                    <StatusBadge status={action.status} /> · runs{" "}
                    {new Date(action.run_after).toLocaleString("en-US", { timeZone: "UTC" })} UTC · attempts{" "}
                    {action.attempts}
                  </p>
                  {action.last_error ? <p className="text-sm text-destructive">{action.last_error}</p> : null}
                </div>
                <ScheduleControls action={action} />
              </li>
            ))}
          </ul>
        )}
      </section>
    </section>
  );
}
