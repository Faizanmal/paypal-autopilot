import { PayoutDecision } from "@/components/payout-decision";
import { PayoutIntentForm } from "@/components/payout-intent-form";
import { serverApi } from "@/lib/api/server";
import type {
  CapabilityReport,
  Contractor,
  Invoice,
  ItemList,
  PayoutCapability,
  PayoutRequest,
} from "@/lib/api/types";

export const instant = false;

export default async function PayPalPage() {
  const [report, capability, payouts, contractors, invoices] = await Promise.all([
    serverApi<CapabilityReport>("/api/v1/integrations/paypal/diagnostics"),
    serverApi<PayoutCapability>("/api/v1/payouts/capability"),
    serverApi<ItemList<PayoutRequest>>("/api/v1/payout-requests"),
    serverApi<ItemList<Contractor>>("/api/v1/contractors"),
    serverApi<ItemList<Invoice>>("/api/v1/invoices"),
  ]);

  const limitation =
    capability?.reason ??
    report?.limitation ??
    "PayPal sandbox credentials are not configured. No live PayPal call has been made.";

  return (
    <section className="flex flex-col gap-8">
      <div>
        <h1 className="text-2xl font-semibold tracking-tight">PayPal sandbox</h1>
        <p className="mt-2 max-w-2xl text-sm text-muted-foreground">{limitation}</p>
      </div>

      <div className="rounded-xl border p-4">
        <h2 className="text-lg font-semibold">Capability</h2>
        <p className="mt-2 text-sm">
          Payout execution: {capability?.execution_enabled ? "enabled" : "disabled"}
        </p>
        <ul className="mt-4 flex flex-col gap-2">
          {(report?.checks ?? []).map((check) => (
            <li key={check.name} className="rounded-lg border px-3 py-2 text-sm">
              <span className="font-medium">{check.name}</span>
              <span className="text-muted-foreground"> · {check.status}</span>
              <p className="mt-1 text-muted-foreground">{check.detail}</p>
            </li>
          ))}
        </ul>
      </div>

      <div className="flex flex-col gap-3">
        <h2 className="text-lg font-semibold">Payout intents</h2>
        <p className="max-w-2xl text-sm text-muted-foreground">
          You can record and approve a payout intent. Execution stays off until sandbox
          Payouts access is confirmed, and this screen does not send money.
        </p>
        {(contractors?.items.length ?? 0) > 0 ? (
          <PayoutIntentForm contractors={contractors?.items ?? []} />
        ) : (
          <p className="text-sm text-muted-foreground">Add a contractor before creating a payout intent.</p>
        )}
        <ul className="flex flex-col gap-2">
          {(payouts?.items ?? []).map((payout) => (
            <li key={payout.id} className="rounded-xl border px-4 py-3 text-sm">
              <PayoutDecision payout={payout} />
            </li>
          ))}
        </ul>
      </div>

      <div className="flex flex-col gap-3">
        <h2 className="text-lg font-semibold">Invoices and checkout</h2>
        <p className="max-w-2xl text-sm text-muted-foreground">
          Draft invoices and orders call PayPal. Those actions stay unavailable until sandbox
          credentials are configured. Buyer approval is required before any capture.
        </p>
        {(invoices?.items ?? []).length === 0 ? (
          <p className="text-sm text-muted-foreground">No PayPal invoices yet.</p>
        ) : (
          <ul className="flex flex-col gap-2">
            {invoices?.items.map((invoice) => (
              <li key={invoice.id} className="rounded-xl border px-4 py-3 text-sm">
                <p className="font-medium">
                  {invoice.currency_code} {invoice.amount} · {invoice.status}
                </p>
                <p className="text-muted-foreground">
                  PayPal status {invoice.provider_status ?? "not created"}
                  {invoice.paypal_invoice_id ? ` · ${invoice.paypal_invoice_id}` : ""}
                </p>
              </li>
            ))}
          </ul>
        )}
      </div>
    </section>
  );
}
