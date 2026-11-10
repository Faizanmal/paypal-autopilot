import Link from "next/link";

import { OpeningBalanceForm } from "@/components/opening-balance-form";
import { PageHeader } from "@/components/page-header";
import { FinanceStudio } from "@/components/sponsors/finance-studio";
import { BackgroundReport } from "@/components/sponsors/background-report";
import { serverApi } from "@/lib/api/server";
import type { AuditEntry, AuthSession, Customer, FinanceSnapshot, Invoice, ItemList } from "@/lib/api/types";
import { money } from "@/lib/money";

export const instant = false;

const FINANCIAL_ACTIONS = [
  "finance.",
  "payout.",
  "approval.",
  "invoice.",
  "policy.",
  "payment.",
  "webhook.",
];

export default async function CashFlowPage() {
  const [snapshot, session, logs, invoices, customers] = await Promise.all([
    serverApi<FinanceSnapshot>("/api/v1/finance/snapshot"),
    serverApi<AuthSession>("/api/v1/auth/me"),
    serverApi<ItemList<AuditEntry>>("/api/v1/audit-logs"),
    serverApi<ItemList<Invoice>>("/api/v1/invoices"),
    serverApi<ItemList<Customer>>("/api/v1/customers"),
  ]);
  if (!snapshot) {
    return <p className="text-sm text-muted-foreground">Sign in to see cash figures for this workspace.</p>;
  }
  const currency = snapshot.currency;
  const metrics = [
    ["Total invoiced", snapshot.total_invoiced],
    ["Confirmed paid", snapshot.total_paid],
    ["Outstanding receivables", snapshot.outstanding_receivables],
    ["Overdue receivables", snapshot.overdue_receivables],
    ["Upcoming expected payments", snapshot.upcoming_expected_payments],
    ["Pending contractor obligations", snapshot.pending_contractor_obligations],
    ["Completed payouts", snapshot.completed_payouts],
    ["Net cash-flow estimate", snapshot.net_cash_flow_estimate],
  ];
  const separation = [
    ["Confirmed payments", snapshot.confirmed_payments],
    ["Expected payments with due dates", snapshot.expected_payments],
    ["Expected payments without due dates", snapshot.undated_expected_payments],
    ["Planned expenses", snapshot.planned_expenses],
    ["Submitted, not verified", snapshot.in_flight_expenses],
    ["Executed expenses", snapshot.executed_expenses],
    ["Refunds reversed", snapshot.refunds_reversed],
  ];
  const activity = (logs?.items ?? [])
    .filter((entry) => FINANCIAL_ACTIONS.some((prefix) => entry.action.startsWith(prefix)))
    .slice(0, 12);

  return (
    <section className="flex animate-in flex-col gap-8 fade-in duration-300">
      <PageHeader
        eyebrow="Cash"
        title="Cash flow"
        description="Confirmed figures come from payment records. Expected invoices and milestones are listed apart from cash already received."
      />
      <dl className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
        {metrics.map(([label, value]) => (
          <div key={label} className="rounded-xl border bg-card p-4">
            <dt className="text-sm text-muted-foreground">{label}</dt>
            <dd className="mt-2 text-2xl font-semibold tracking-tight">
              {value === null ? "Not estimated" : money(currency, value)}
            </dd>
          </div>
        ))}
      </dl>

      <FinanceStudio invoices={invoices?.items ?? []} customers={customers?.items ?? []} snapshot={snapshot} />
      <BackgroundReport />

      {session?.workspace.role === "owner" ? (
        <OpeningBalanceForm openingBalance={snapshot.opening_balance} asOf={snapshot.opening_as_of} />
      ) : (
        <p className="text-sm text-muted-foreground">
          Only the workspace owner can change the opening balance
          {snapshot.opening_balance ? ` (currently ${money(currency, snapshot.opening_balance)})` : ""}.
        </p>
      )}

      <section className="flex flex-col gap-3">
        <h2 className="text-lg font-semibold">What each figure means</h2>
        <dl className="grid gap-3 sm:grid-cols-2">
          {separation.map(([label, value]) => (
            <div key={label} className="flex items-baseline justify-between gap-4 rounded-xl border px-4 py-3">
              <dt className="text-sm text-muted-foreground">{label}</dt>
              <dd className="text-sm font-medium">{money(currency, value)}</dd>
            </div>
          ))}
          <div className="flex items-baseline justify-between gap-4 rounded-xl border px-4 py-3 sm:col-span-2">
            <dt className="text-sm text-muted-foreground">PayPal account balance</dt>
            <dd className="text-sm font-medium">
              {snapshot.paypal_balance_available && snapshot.paypal_balance_amount
                ? money(currency, snapshot.paypal_balance_amount)
                : snapshot.paypal_balance_reason}
            </dd>
          </div>
        </dl>
      </section>

      <section className="flex flex-col gap-3">
        <h2 className="text-lg font-semibold">Projection</h2>
        <p className="max-w-2xl text-sm text-muted-foreground">
          {snapshot.projected_available === null
            ? "Projected available funds are omitted until you save an opening balance."
            : `Projected available funds are ${money(currency, snapshot.projected_available)}. Dated expected inflows inside ${snapshot.horizon_days} days are included. Undated amounts are not.`}
        </p>
        {snapshot.projection.length === 0 ? (
          <p className="text-sm text-muted-foreground">No open invoices, milestones, or payouts are in this window.</p>
        ) : (
          <ul className="flex flex-col gap-2">
            {snapshot.projection.map((entry) => (
              <li key={`${entry.label}-${entry.on ?? "undated"}`} className="rounded-xl border px-4 py-3 text-sm">
                <div className="flex flex-wrap items-baseline justify-between gap-2">
                  <p className="font-medium">{entry.label}</p>
                  <p>
                    {entry.direction === "outflow" ? "Out " : "In "}
                    {money(currency, entry.amount)}
                    {entry.included ? "" : " · not in the total"}
                  </p>
                </div>
                <p className="mt-1 text-muted-foreground">
                  {entry.on ?? "No date"} · {entry.reason}
                </p>
              </li>
            ))}
          </ul>
        )}
      </section>

      <section className="flex flex-col gap-3">
        <h2 className="text-lg font-semibold">Insights</h2>
        {snapshot.insights.length === 0 ? (
          <p className="text-sm text-muted-foreground">No insight met the calculated thresholds.</p>
        ) : (
          <ul className="flex flex-col gap-2">
            {snapshot.insights.map((insight) => (
              <li key={`${insight.kind}-${insight.message}`} className="rounded-xl border px-4 py-3 text-sm">
                <p className="text-xs font-medium tracking-wide text-muted-foreground uppercase">
                  {insight.kind.replaceAll("_", " ")}
                </p>
                <p className="mt-1">{insight.message}</p>
                {Object.keys(insight.figures).length > 0 ? (
                  <p className="mt-2 text-xs text-muted-foreground">
                    Figures:{" "}
                    {Object.entries(insight.figures)
                      .map(([key, value]) => `${key.replaceAll("_", " ")}=${value}`)
                      .join(" · ")}
                  </p>
                ) : null}
              </li>
            ))}
          </ul>
        )}
      </section>

      <section className="flex flex-col gap-3">
        <h2 className="text-lg font-semibold">Alerts</h2>
        {snapshot.alerts.length === 0 ? (
          <p className="text-sm text-muted-foreground">No overdue invoices, pending approvals, failures, or shortfalls.</p>
        ) : (
          <ul className="flex flex-col gap-2">
            {snapshot.alerts.map((alert) => (
              <li key={`${alert.kind}-${alert.message}`} className="rounded-xl border px-4 py-3 text-sm">
                <p className="text-xs font-medium tracking-wide text-muted-foreground uppercase">
                  {alert.kind.replaceAll("_", " ")}
                </p>
                <p className="mt-1">{alert.message}</p>
              </li>
            ))}
          </ul>
        )}
      </section>

      <section className="flex flex-col gap-3">
        <div className="flex flex-wrap items-baseline justify-between gap-3">
          <h2 className="text-lg font-semibold">Financial activity</h2>
          <Link href="/app/audit" className="text-sm underline-offset-4 hover:underline">
            Full audit log
          </Link>
        </div>
        <p className="max-w-2xl text-sm text-muted-foreground">
          Append-only records for who initiated an action, whether AI proposed it, who approved it, which policy was
          evaluated, which PayPal operation ran, and the verified result.
        </p>
        {activity.length === 0 ? (
          <p className="text-sm text-muted-foreground">No financial audit events yet.</p>
        ) : (
          <div className="overflow-x-auto rounded-xl border">
            <table className="w-full min-w-[56rem] text-left text-sm">
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
                {activity.map((entry) => (
                  <tr key={entry.id} className="border-b last:border-0">
                    <td className="px-3 py-2 whitespace-nowrap">
                      {new Date(entry.created_at).toLocaleString("en-US", { timeZone: "UTC" })} UTC
                    </td>
                    <td className="px-3 py-2">{entry.actor_name ?? "System"}</td>
                    <td className="px-3 py-2">{entry.action}</td>
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

      <section className="flex max-w-2xl flex-col gap-3 text-sm leading-6">
        <h2 className="text-lg font-semibold">Assumptions</h2>
        <ul className="list-disc pl-5 text-muted-foreground">
          {snapshot.assumptions.map((assumption) => (
            <li key={assumption}>{assumption}</li>
          ))}
          {Object.keys(snapshot.excluded_by_currency).length > 0 ? (
            <li>
              Excluded records:{" "}
              {Object.entries(snapshot.excluded_by_currency)
                .map(([code, count]) => `${count} ${code}`)
                .join(", ")}
              .
            </li>
          ) : null}
        </ul>
      </section>

      <section className="flex max-w-2xl flex-col gap-3 text-sm leading-6">
        <h2 className="text-lg font-semibold">Uncertainty</h2>
        <ul className="list-disc pl-5 text-muted-foreground">
          {snapshot.uncertainty.map((item) => (
            <li key={item}>{item}</li>
          ))}
        </ul>
      </section>
    </section>
  );
}
