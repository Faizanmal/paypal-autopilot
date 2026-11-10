import { PayoutDecision } from "@/components/payout-decision";
import { PolicyControls } from "@/components/policy-controls";
import { serverApi } from "@/lib/api/server";
import type { AuthSession, FinancialPolicy, ItemList, PayoutCapability, PayoutRequest } from "@/lib/api/types";

export const instant = false;

export default async function ApprovalsPage() {
  const [session, policy, payouts, capability] = await Promise.all([
    serverApi<AuthSession>("/api/v1/auth/me"),
    serverApi<FinancialPolicy>("/api/v1/financial-policy"),
    serverApi<ItemList<PayoutRequest>>("/api/v1/payout-requests"),
    serverApi<PayoutCapability>("/api/v1/payouts/capability"),
  ]);
  const items = payouts?.items ?? [];
  const waiting = items.filter((item) => item.status === "pending_approval");

  return (
    <section className="flex flex-col gap-8">
      <div>
        <h1 className="text-2xl font-semibold tracking-tight">Approvals</h1>
        <p className="mt-2 max-w-2xl text-sm text-muted-foreground">
          Approving records your identity against this recipient, amount, and currency. It does not
          call PayPal. Execution is {capability?.execution_enabled ? "enabled" : "disabled"}
          {capability?.reason ? `: ${capability.reason}` : ""}.
        </p>
        {policy?.paused_at ? (
          <p className="mt-3 text-sm text-destructive" role="alert">
            The workspace is paused, so new financial actions are blocked.
          </p>
        ) : null}
      </div>
      {policy ? <PolicyControls policy={policy} canEdit={session?.workspace.role === "owner"} /> : null}
      <div className="flex flex-col gap-3">
        <h2 className="text-lg font-semibold">Waiting for a decision</h2>
        {waiting.length === 0 ? (
          <p className="text-sm text-muted-foreground">No payout is waiting for approval.</p>
        ) : (
          <ul className="flex flex-col gap-3">
            {waiting.map((payout) => (
              <li key={payout.id} className="rounded-xl border px-4 py-3">
                <PayoutDecision payout={payout} />
              </li>
            ))}
          </ul>
        )}
      </div>
      <div className="flex flex-col gap-3">
        <h2 className="text-lg font-semibold">Decided</h2>
        {items.filter((item) => item.status !== "pending_approval").length === 0 ? (
          <p className="text-sm text-muted-foreground">No decided payouts yet.</p>
        ) : (
          <ul className="flex flex-col gap-2">
            {items
              .filter((item) => item.status !== "pending_approval")
              .map((payout) => (
                <li key={payout.id} className="rounded-xl border px-4 py-3 text-sm">
                  <p className="font-medium">
                    {payout.currency_code} {payout.amount} · {payout.status}
                  </p>
                  <p className="text-muted-foreground">{payout.recipient_email}</p>
                  {payout.decision_reason ? (
                    <p className="text-muted-foreground">Reason: {payout.decision_reason}</p>
                  ) : null}
                </li>
              ))}
          </ul>
        )}
      </div>
    </section>
  );
}
