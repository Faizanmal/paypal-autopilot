import { EmptyState } from "@/components/empty-state";
import { PageHeader } from "@/components/page-header";
import { serverApi } from "@/lib/api/server";
import type { AuditEntry, ItemList } from "@/lib/api/types";

export const instant = false;

export default async function AuditPage() {
  const logs = await serverApi<ItemList<AuditEntry>>("/api/v1/audit-logs");
  const items = logs?.items ?? [];

  return (
    <section className="flex animate-in flex-col gap-6 fade-in duration-300">
      <PageHeader
        eyebrow="Record"
        title="Audit log"
        description="Each row is append-only. AI proposed, approval, policy, and PayPal are shown only when that fact was stored with the event."
      />
      {items.length === 0 ? (
        <EmptyState title="No audit events" detail="Creating customers, invoices, payouts, and plans writes the first entries." />
      ) : (
        <div className="overflow-x-auto rounded-xl border">
          <table className="w-full min-w-[64rem] text-left text-sm">
            <thead className="border-b bg-muted/60 text-muted-foreground">
              <tr>
                <th className="px-3 py-2 font-medium">Time</th>
                <th className="px-3 py-2 font-medium">Initiated by</th>
                <th className="px-3 py-2 font-medium">Action</th>
                <th className="px-3 py-2 font-medium">AI proposed</th>
                <th className="px-3 py-2 font-medium">Approval</th>
                <th className="px-3 py-2 font-medium">Policy</th>
                <th className="px-3 py-2 font-medium">PayPal</th>
                <th className="px-3 py-2 font-medium">Result</th>
              </tr>
            </thead>
            <tbody>
              {items.map((entry) => (
                <tr key={entry.id} className="border-b last:border-0">
                  <td className="px-3 py-2 whitespace-nowrap">
                    {new Date(entry.created_at).toLocaleString("en-US", { timeZone: "UTC" })} UTC
                  </td>
                  <td className="px-3 py-2">{entry.actor_name ?? "System"}</td>
                  <td className="px-3 py-2">
                    {entry.action}
                    <span className="block text-xs text-muted-foreground">
                      {entry.entity_type}
                      {entry.entity_id ? ` ${entry.entity_id.slice(0, 8)}` : ""}
                    </span>
                  </td>
                  <td className="px-3 py-2">{entry.proposed_by_ai ? "Yes" : "No"}</td>
                  <td className="px-3 py-2">{entry.approval_id ?? "Not recorded"}</td>
                  <td className="px-3 py-2">{entry.policy_evaluated ?? "Not recorded"}</td>
                  <td className="px-3 py-2">{entry.paypal_operation ?? "Not recorded"}</td>
                  <td className="px-3 py-2">{entry.result}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </section>
  );
}
