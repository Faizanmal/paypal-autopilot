"use client";

import { useMemo, useRef, useState } from "react";
import { AgStudio, AgStudioProvider } from "ag-studio-react";
import { AgStudioAiModule, AgStudioModuleRegistry, createAiHarness, studioTheme, type AgAiHarnessSetup, type AgDataSourcesDefinition, type AgReportState, type AgStudioApi } from "ag-studio";
import { Button } from "@/components/ui/button";
import type { Customer, FinanceSnapshot, Invoice } from "@/lib/api/types";
import { chartAmount, invoiceAnalytics } from "@/lib/sponsor-data";
import { studioAdapter } from "@/lib/studio-ai";

AgStudioModuleRegistry.registerModules([AgStudioAiModule]);

const theme = studioTheme.withParams({
  fontFamily: "system-ui, sans-serif",
  accentColor: "#0e7490",
  studioWidgetBorderRadius: 12,
  studioWidgetTitleFontSize: 16,
  studioCanvasMinWidth: 600,
});

const initialState: AgReportState = {
  selectedPageId: "invoices",
  pages: [{
    id: "invoices",
    widgets: {
      status: { type: "list-filter", dataMapping: { value: [{ id: "invoices.status" }] }, format: { title: { enabled: true, text: "Invoice status" } } },
      customers: { type: "bar-chart-grouped", dataMapping: { categoryKey: [{ id: "invoices.customer" }], valueKey: [{ id: "invoices.faceValue", aggregation: "sum" }] }, format: { title: { enabled: true, text: "Invoice face value by customer" } } },
      states: { type: "bar-chart-grouped", dataMapping: { categoryKey: [{ id: "invoices.status" }], valueKey: [{ id: "invoices.faceValue", aggregation: "sum" }] }, format: { title: { enabled: true, text: "Invoice face value by status" } } },
      ledger: { type: "grid", dataMapping: { cols: [{ id: "invoices.customer" }, { id: "invoices.exactAmount" }, { id: "invoices.status" }, { id: "invoices.dueDate" }, { id: "invoices.paymentEvidence" }] }, format: { title: { enabled: true, text: "Invoice ledger" } } },
    },
    widgetLayout: {
      status: { xTrack: 0, yTrack: 0, xSpan: 5, ySpan: 18 },
      customers: { xTrack: 5, yTrack: 0, xSpan: 10, ySpan: 18 },
      states: { xTrack: 15, yTrack: 0, xSpan: 9, ySpan: 18 },
      ledger: { xTrack: 0, yTrack: 18, xSpan: 24, ySpan: 20 },
    },
  }, {
    id: "cash",
    widgets: {
      categories: { type: "bar-chart-grouped", dataMapping: { categoryKey: [{ id: "cash.category" }], valueKey: [{ id: "cash.amount", aggregation: "sum" }] }, format: { title: { enabled: true, text: "Confirmed, expected, and planned amounts" } } },
      projection: { type: "grid", dataMapping: { cols: [{ id: "projection.date" }, { id: "projection.label" }, { id: "projection.direction" }, { id: "projection.exactAmount" }, { id: "projection.inclusion" }, { id: "projection.reason" }] }, format: { title: { enabled: true, text: "Projection evidence" } } },
    },
    widgetLayout: { categories: { xTrack: 0, yTrack: 0, xSpan: 24, ySpan: 18 }, projection: { xTrack: 0, yTrack: 18, xSpan: 24, ySpan: 20 } },
  }],
};

export default function FinanceStudioView({ invoices, customers, snapshot }: {
  invoices: Invoice[]; customers: Customer[]; snapshot: FinanceSnapshot;
}) {
  const studio = useRef<AgStudioApi | null>(null);
  const [mode, setMode] = useState<"view" | "edit">("view");
  const [page, setPage] = useState("invoices");
  const [reset, setReset] = useState(0);
  const [aiEnabled, setAiEnabled] = useState(false);
  const ai = useMemo<AgAiHarnessSetup>(() => ({ api }) => createAiHarness(api as AgStudioApi, {
    adapter: studioAdapter,
    promptStarters: [
      { label: "Explain report data", prompt: "Explain the tables and fields in this report, distinguishing expected amounts from confirmed cash." },
      { label: "Chart invoice status", prompt: "Add a bar chart showing invoice face value by invoice status." },
    ],
  }), []);
  const mapped = useMemo(() => invoiceAnalytics(invoices, customers, snapshot.currency), [invoices, customers, snapshot.currency]);
  const data = useMemo<AgDataSourcesDefinition>(() => ({ sources: [
    { id: "invoices", name: "Workspace invoices", data: mapped.rows, fields: [
      { id: "customer", name: "Customer", format: "textFormat" },
      { id: "status", name: "Invoice status", format: "textFormat" },
      { id: "faceValue", name: `Invoice face value (${snapshot.currency})`, format: "currencyFormat" },
      { id: "exactAmount", name: `Exact amount (${snapshot.currency})`, format: "textFormat" },
      { id: "dueDate", name: "Due date", format: "textFormat" },
      { id: "paymentEvidence", name: "Payment evidence", format: "textFormat" },
    ] },
    { id: "cash", name: "Server-calculated financial categories", data: [
      { category: "Confirmed payments", amount: chartAmount(snapshot.confirmed_payments) },
      { category: "Expected payments", amount: chartAmount(snapshot.expected_payments) },
      { category: "Planned expenses", amount: chartAmount(snapshot.planned_expenses) },
      { category: "Executed expenses", amount: chartAmount(snapshot.executed_expenses) },
    ], fields: [{ id: "category", name: "Financial category", format: "textFormat" }, { id: "amount", name: `Amount (${snapshot.currency})`, format: "currencyFormat" }] },
    { id: "projection", name: "Projection evidence", fields: [
      { id: "date", name: "Date", format: "textFormat" },
      { id: "label", name: "Item", format: "textFormat" },
      { id: "direction", name: "Direction", format: "textFormat" },
      { id: "exactAmount", name: `Exact amount (${snapshot.currency})`, format: "textFormat" },
      { id: "inclusion", name: "Projection inclusion", format: "textFormat" },
      { id: "reason", name: "Reason", format: "textFormat" },
    ], data: snapshot.projection.map((row) => ({
      date: row.on ?? "Undated", label: row.label, direction: row.direction,
      exactAmount: row.amount, inclusion: row.included ? "Included in projection" : "Excluded from projection", reason: row.reason,
    })) },
  ] }), [mapped.rows, snapshot]);

  function selectPage(id: string) {
    if (!studio.current) return;
    const state = studio.current.getState();
    studio.current.setState({ ...state, selectedPageId: id });
    setPage(id);
  }

  return (
    <section aria-labelledby="finance-studio-title" className="flex min-w-0 flex-col gap-4 rounded-xl border bg-card p-4">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h2 id="finance-studio-title" className="text-lg font-semibold">Financial reports</h2>
          <p className="mt-1 max-w-2xl text-sm text-muted-foreground">Filter and explore your workspace with AG Studio. Invoice face values are not cash received. All amounts are {snapshot.currency}.</p>
        </div>
        <div className="flex flex-wrap gap-2">
          <Button variant="outline" size="sm" aria-pressed={page === "invoices"} onClick={() => selectPage("invoices")}>Invoice reports</Button>
          <Button variant="outline" size="sm" aria-pressed={page === "cash"} onClick={() => selectPage("cash")}>Cash evidence</Button>
          <Button variant="outline" size="sm" onClick={() => setMode(mode === "view" ? "edit" : "view")}>{mode === "view" ? "Customize report" : "Finish editing"}</Button>
          <Button variant="outline" size="sm" aria-pressed={aiEnabled} onClick={() => { setAiEnabled(!aiEnabled); setMode("edit"); studio.current = null; setReset((value) => value + 1); setPage("invoices"); }}>{aiEnabled ? "Disable report AI" : "Enable report AI"}</Button>
          <Button variant="ghost" size="sm" onClick={() => { studio.current = null; setReset((value) => value + 1); setPage("invoices"); }}>Reset report</Button>
        </div>
      </div>
      <p className="text-xs text-muted-foreground">Enable report AI to chat in the AI side panel. Prompts, report context, and requested query results go to OpenAI through your authenticated server. Chat changes only this temporary report. Enabling or disabling AI resets the local layout.</p>
      {mapped.excludedCount > 0 && <p className="text-sm text-muted-foreground">{mapped.excludedCount} invoices are excluded from these charts because their currency or amount cannot be combined with this report.</p>}
      {mapped.rows.length === 0 && <p className="text-sm text-muted-foreground">Create an invoice to populate invoice reports. Cash evidence remains available.</p>}
      <div className="overflow-x-auto rounded-lg border bg-white text-slate-900" data-testid="finance-studio">
        <div style={{ height: 760, minWidth: 650 }}>
          <AgStudioProvider licenseKey={process.env.NEXT_PUBLIC_AG_STUDIO_LICENSE_KEY || undefined}>
            <AgStudio key={reset} ai={aiEnabled ? ai : undefined} panels={{ edit: { right: aiEnabled ? ["ai", "edit", "data", "filters"] : ["edit", "data", "filters"] } }} onApiReady={({ api }) => { studio.current = api; }} data={data} initialState={initialState} mode={mode} theme={theme} loadThemeGoogleFonts={false} style={{ height: "100%", width: "100%" }} />
          </AgStudioProvider>
        </div>
      </div>
      <p className="text-xs text-muted-foreground">Report customization lasts for this page session. Editing a report does not change invoices, approvals, or payments. The figures above remain the financial source of truth.</p>
    </section>
  );
}
