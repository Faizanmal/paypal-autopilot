import { AgentConsole } from "@/components/agent-console";
import { serverApi } from "@/lib/api/server";
import type { AgentRun, ItemList } from "@/lib/api/types";

export const instant = false;

export default async function AgentPage() {
  const runs = await serverApi<ItemList<AgentRun>>("/api/v1/agent/runs");

  return (
    <section className="flex flex-col gap-6">
      <div>
        <h1 className="text-2xl font-semibold tracking-tight">AI workspace</h1>
        <p className="mt-2 max-w-2xl text-sm text-muted-foreground">
          Natural-language instructions become a plan you can review. Invoices, projects, and
          reminders run only after confirmation, through the workspace services. A payout step
          prepares an approval and does not send money.
        </p>
      </div>
      <AgentConsole initialRuns={runs?.items ?? []} />
    </section>
  );
}
