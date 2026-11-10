"use client";

import { useEffect, useState } from "react";

import { PlanEditor } from "@/components/plan-editor";
import { Button } from "@/components/ui/button";
import { ApiError, api } from "@/lib/api/client";
import type { AgentRun } from "@/lib/api/types";

export function AgentConsole({ initialRuns }: { initialRuns: AgentRun[] }) {
  const [instruction, setInstruction] = useState("Invoice Acme $1,200 for October development.");
  const [current, setCurrent] = useState<AgentRun | null>(initialRuns[0] ?? null);
  const [runs, setRuns] = useState(initialRuns);
  const [error, setError] = useState<string | null>(null);
  const [pending, setPending] = useState(false);
  const [editing, setEditing] = useState(false);
  const [refreshError, setRefreshError] = useState<string | null>(null);
  const runId = current?.id;
  const runStatus = current?.status;

  useEffect(() => {
    if (!runId || !["waiting", "executing"].includes(runStatus ?? "") || pending) return;
    let active = true;
    let timer: ReturnType<typeof setTimeout>;
    async function refresh() {
      try {
        const updated = await api<AgentRun>(`/api/v1/agent/runs/${runId}`);
        if (!active) return;
        setCurrent((existing) => existing?.id === updated.id ? updated : existing);
        setRuns((existing) => existing.map((item) => item.id === updated.id ? updated : item));
        setRefreshError(null);
      } catch {
        if (active) setRefreshError("Status refresh failed. Retrying automatically.");
      } finally {
        if (active) timer = setTimeout(refresh, 5000);
      }
    }
    timer = setTimeout(refresh, 5000);
    return () => { active = false; clearTimeout(timer); };
  }, [runId, runStatus, pending]);

  function remember(run: AgentRun, supersededId?: string) {
    setEditing(false);
    setCurrent(run);
    setRuns((existing) => [run, ...existing.filter((item) => item.id !== run.id).map((item) =>
      item.id === supersededId ? { ...item, status: "cancelled", steps: item.steps.map((step) => ({ ...step, status: "cancelled" })) } : item)]);
  }

  async function submit(path: string, body?: unknown) {
    setPending(true);
    setError(null);
    try {
      const run = await api<AgentRun>(path, body === undefined ? { method: "POST" } : { body });
      remember(run, path.endsWith("/revise") ? current?.id : undefined);
    } catch (caught) {
      setError(caught instanceof ApiError ? caught.message : "The agent request failed.");
    } finally {
      setPending(false);
    }
  }

  const suggestions = [
    "Invoice Acme $100 for October.",
    "Remind Acme in seven days.",
    "Pay my designer $40 after the client payment clears.",
    "Show invoices overdue by more than 14 days.",
  ];
  const run = current;
  const explanation = [...new Set((run?.explanation ?? "").split("\n"))]
    .filter((line) => line !== run?.provider_label).join("\n");
  const clarifications = [...new Set(run?.clarifications ?? [])].filter(
    (item) => !explanation.includes(item),
  );
  const canConfirm = run?.status === "pending_confirmation";
  const canRetry = run?.status === "failed" || run?.status === "blocked" || run?.status === "executing";
  const canCancel = ["pending_confirmation", "failed", "blocked", "executing", "waiting"].includes(run?.status ?? "");

  return (
    <div className="flex flex-col gap-8">
      <form
        className="flex flex-col gap-3"
        onSubmit={(event) => {
          event.preventDefault();
          void submit("/api/v1/agent/plans", { instruction });
        }}
      >
        <label className="text-sm font-medium" htmlFor="instruction">
          Instruction
        </label>
        <textarea
          id="instruction"
          className="min-h-28 w-full rounded-lg border px-3 py-2 text-sm"
          value={instruction}
          onChange={(event) => setInstruction(event.target.value)}
          required
        />
        <div className="flex flex-wrap gap-2">
          {suggestions.map((suggestion) => (
            <Button key={suggestion} type="button" variant="outline" onClick={() => setInstruction(suggestion)}>
              {suggestion}
            </Button>
          ))}
        </div>
        <div>
          <Button type="submit" disabled={pending || instruction.trim().length === 0}>
            Preview plan
          </Button>
        </div>
      </form>

      {error ? <p role="alert" className="text-sm text-destructive">{error}</p> : null}

      {run ? (
        <section className="flex flex-col gap-4 rounded-xl border p-4">
          <div>
            <p className="text-sm font-medium">{run.provider_label}</p>
            <p aria-live="polite" className="mt-1 text-sm text-muted-foreground">Status: {run.status}</p>
            {refreshError ? <p role="status" className="text-sm text-muted-foreground">{refreshError}</p> : null}
          </div>
          {explanation ? (
            <pre className="whitespace-pre-wrap text-sm">{explanation}</pre>
          ) : null}
          {clarifications.length > 0 ? (
            <ul className="list-disc pl-5 text-sm">
              {clarifications.map((item) => (
                <li key={item}>{item}</li>
              ))}
            </ul>
          ) : null}
          <ol className="flex flex-col gap-3">
            {run.steps.map((step) => (
              <li key={step.sequence} className="rounded-lg border px-3 py-2 text-sm">
                <p className="font-medium">
                  {step.sequence}. {step.summary}
                </p>
                <p className="text-muted-foreground">
                  {step.status}
                  {step.requires_approval ? " · approval required" : ""}
                  {step.attempts > 0 ? ` · attempts ${step.attempts}` : ""}
                </p>
                {step.preconditions.length > 0 ? (
                  <p className="text-muted-foreground">Preconditions: {step.preconditions.join(", ")}</p>
                ) : null}
                {step.provider_reference ? (
                  <p className="text-muted-foreground">PayPal reference: {step.provider_reference}</p>
                ) : null}
                {step.error ? <p>{step.error}</p> : null}
                {Object.keys(step.arguments).length > 0 ? (
                  <dl className="mt-2 grid grid-cols-[auto_1fr] gap-x-3 gap-y-1">
                    {Object.entries(step.arguments).map(([key, value]) => (
                      <div key={key} className="contents">
                        <dt className="text-muted-foreground">{key.replaceAll("_", " ")}</dt>
                        <dd className="break-words">{String(value)}</dd>
                      </div>
                    ))}
                  </dl>
                ) : null}
                {step.result ? (
                  <details className="mt-2">
                    <summary className="cursor-pointer">Step result</summary>
                    <pre className="mt-2 max-h-80 overflow-auto whitespace-pre-wrap break-all">{JSON.stringify(step.result, null, 2)}</pre>
                  </details>
                ) : null}
              </li>
            ))}
          </ol>
          {editing && canConfirm ? (
            <PlanEditor key={run.id} run={run} pending={pending} onCancel={() => setEditing(false)}
              onSave={(body) => void submit(`/api/v1/agent/runs/${run.id}/revise`, body)} />
          ) : null}
          <div className="flex gap-2">
            {canConfirm && !editing ? (
              <>
                <Button type="button" disabled={pending} onClick={() => void submit(`/api/v1/agent/runs/${run.id}/confirm`)}>
                  Confirm plan
                </Button>
                <Button type="button" variant="outline" disabled={pending} onClick={() => setEditing(true)}>
                  Edit plan
                </Button>
              </>
            ) : null}
            {canRetry ? (
              <Button type="button" variant="outline" disabled={pending} onClick={() => void submit(`/api/v1/agent/runs/${run.id}/retry`)}>
                Retry failed steps
              </Button>
            ) : null}
            {canCancel ? (
              <Button type="button" variant="outline" disabled={pending} onClick={() => void submit(`/api/v1/agent/runs/${run.id}/cancel`)}>
                Cancel workflow
              </Button>
            ) : null}
          </div>
        </section>
      ) : null}

      {runs.length > 0 ? (
        <section className="flex flex-col gap-2">
          <h2 className="text-lg font-semibold">Recent plans</h2>
          <ul className="flex flex-col gap-2">
            {runs.map((item) => (
              <li key={item.id}>
                <button
                  type="button"
                  className="w-full rounded-lg border px-3 py-2 text-left text-sm hover:bg-muted"
                  disabled={pending}
                  onClick={() => { setEditing(false); setCurrent(item); }}
                >
                  <span className="font-medium">{item.status}</span>
                  <span className="text-muted-foreground"> · {item.instruction}</span>
                </button>
              </li>
            ))}
          </ul>
        </section>
      ) : null}
    </div>
  );
}
