import Link from "next/link";

import { EmptyState } from "@/components/empty-state";
import { PageHeader } from "@/components/page-header";
import { PayoutIntentForm } from "@/components/payout-intent-form";
import { StatusBadge } from "@/components/status-badge";
import { serverApi } from "@/lib/api/server";
import type { Contractor, ItemList, PayoutCapability, PayoutRequest } from "@/lib/api/types";
import { money } from "@/lib/money";

export const instant = false;

export default async function PayoutsPage() {
  const [payouts, contractors, capability] = await Promise.all([
    serverApi<ItemList<PayoutRequest>>("/api/v1/payout-requests"),
    serverApi<ItemList<Contractor>>("/api/v1/contractors"),
    serverApi<PayoutCapability>("/api/v1/payouts/capability"),
  ]);
  const items = payouts?.items ?? [];

  return (
    <section className="flex animate-in flex-col gap-8 fade-in duration-300">
      <PageHeader
        eyebrow="Payables"
        title="Payouts"
        description="Preparing a payout creates an approval request. It does not send money."
      />
      <p className="max-w-2xl rounded-xl border bg-card px-4 py-3 text-sm">
        Provider execution is {capability?.execution_enabled ? "enabled" : "disabled"}. {capability?.reason}
      </p>
      <PayoutIntentForm contractors={contractors?.items ?? []} />
      {items.length === 0 ? (
        <EmptyState title="No payout requests" detail="A prepared payout from this form or from a confirmed agent plan appears here." />
      ) : (
        <ul className="flex flex-col gap-3">
          {items.map((payout) => (
            <li key={payout.id} className="flex flex-col gap-2 rounded-xl border px-4 py-3">
              <div className="flex flex-wrap items-center justify-between gap-2">
                <p className="font-medium">{money(payout.currency_code, payout.amount)}</p>
                <StatusBadge status={payout.status} />
              </div>
              <dl className="grid gap-2 text-sm sm:grid-cols-2">
                <div>
                  <dt className="text-muted-foreground">Recipient</dt>
                  <dd>{payout.recipient_email ?? "No recipient email"}</dd>
                </div>
                <div>
                  <dt className="text-muted-foreground">Provider status</dt>
                  <dd>{payout.provider_status ?? "Not submitted"}</dd>
                </div>
                <div>
                  <dt className="text-muted-foreground">PayPal batch</dt>
                  <dd>{payout.paypal_payout_batch_id ?? "None"}</dd>
                </div>
                <div>
                  <dt className="text-muted-foreground">Approval</dt>
                  <dd>
                    <Link href="/app/approvals" className="underline-offset-4 hover:underline">
                      Open approval center
                    </Link>
                  </dd>
                </div>
              </dl>
              {payout.last_provider_error ? (
                <p className="text-sm text-destructive" role="alert">
                  {payout.last_provider_error}
                </p>
              ) : null}
              {payout.decision_reason ? <p className="text-sm text-muted-foreground">{payout.decision_reason}</p> : null}
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}
