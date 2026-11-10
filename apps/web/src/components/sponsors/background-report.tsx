"use client";

import { useState } from "react";
import { Button } from "@/components/ui/button";
import { api } from "@/lib/api/client";

type Report = {
  run_id: string;
  report: { currency: string; horizon_days: number; overdue_receivables: string; total_receivables: string;
    overdue_percent: string; planned_expenses: string; projected_available: string | null;
    alert_count: number; excluded_projection_count: number; warnings: string[] };
};

export function BackgroundReport() {
  const [result, setResult] = useState<Report | null>(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  async function run() {
    setBusy(true); setError(""); setResult(null);
    try { setResult(await api<Report>("/api/v1/finance/background-report", { method: "POST" })); }
    catch (error) { setError(error instanceof Error ? error.message : "The background report could not finish."); }
    finally { setBusy(false); }
  }
  return <section aria-labelledby="background-report-title" className="flex flex-col gap-3 rounded-xl border bg-card p-4">
    <h2 id="background-report-title" className="text-lg font-semibold">Background cash-risk report</h2>
    <p className="text-sm text-muted-foreground">Run a read-only snapshot analysis with Render Workflows. It calculates the overdue share of receivables and flags excluded projection entries. Figures reflect the snapshot taken when you run it.</p>
    <Button variant="outline" disabled={busy} onClick={() => void run()} className="self-start">{busy ? "Running report…" : "Run background report"}</Button>
    <div aria-live="polite">
      {error && <p role="alert" className="text-sm text-destructive">{error}</p>}
      {result && <div className="space-y-2 text-sm" data-testid="background-report-result">
        <p>Overdue: {result.report.currency} {result.report.overdue_receivables} ({result.report.overdue_percent}% of outstanding receivables).</p>
        <p>Planned expenses: {result.report.currency} {result.report.planned_expenses}. Projected available: {result.report.projected_available === null ? "Unknown — opening balance required" : `${result.report.currency} ${result.report.projected_available}`}.</p>
        <p>{result.report.alert_count} alerts; {result.report.excluded_projection_count} projection entries excluded. Horizon: {result.report.horizon_days} days.</p>
        <ul className="list-inside list-disc">{result.report.warnings.map((warning, index) => <li key={index}>{warning}</li>)}</ul>
        <p className="text-xs text-muted-foreground">Render run: {result.run_id}</p>
      </div>}
    </div>
  </section>;
}
