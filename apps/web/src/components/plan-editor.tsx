"use client";

import { useState } from "react";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import type { AgentRun } from "@/lib/api/types";

export function PlanEditor({ run, pending, onSave, onCancel }: {
  run: AgentRun;
  pending: boolean;
  onSave: (body: { instruction: string; arguments: Record<number, Record<string, unknown>> }) => void;
  onCancel: () => void;
}) {
  const [instruction, setInstruction] = useState(run.instruction);
  const [argumentsByStep, setArguments] = useState<Record<number, Record<string, unknown>>>(
    Object.fromEntries(run.steps.map((step) => [step.sequence, { ...step.arguments }])),
  );

  function update(sequence: number, key: string, value: unknown) {
    setArguments((existing) => ({ ...existing, [sequence]: { ...existing[sequence], [key]: value } }));
  }

  return (
    <form className="flex flex-col gap-4 rounded-lg border p-4" onSubmit={(event) => {
      event.preventDefault();
      onSave({ instruction, arguments: argumentsByStep });
    }}>
      <p className="text-sm text-muted-foreground">
        Update the instruction to match any changed amounts. Saving validates a new preview;
        you must confirm it separately before it runs.
      </p>
      <label className="flex flex-col gap-1 text-sm">
        Revised instruction
        <textarea className="min-h-24 rounded-lg border p-2" value={instruction} required maxLength={4000}
          disabled={pending} onChange={(event) => setInstruction(event.target.value)} />
      </label>
      {run.steps.filter((step) => Object.keys(step.arguments).length > 0).map((step) => (
        <fieldset key={step.sequence} disabled={pending} className="flex min-w-0 flex-col gap-2">
          <legend className="mb-2 text-sm font-medium">{step.sequence}. {step.summary}</legend>
          {Object.entries(step.arguments).map(([key, original]) => (
            <label key={key} className="flex flex-col gap-1 text-sm">
              {`Step ${step.sequence} ${key.replaceAll("_", " ")}`}
              {typeof original === "boolean" ? (
                <input type="checkbox" checked={Boolean(argumentsByStep[step.sequence][key])}
                  onChange={(event) => update(step.sequence, key, event.target.checked)} />
              ) : (
                <Input value={String(argumentsByStep[step.sequence][key] ?? "")}
                  type={typeof original === "number" ? "number" : "text"}
                  onChange={(event) => update(step.sequence, key,
                    typeof original === "number" ? Number(event.target.value) : event.target.value)} />
              )}
            </label>
          ))}
        </fieldset>
      ))}
      <div className="flex flex-wrap gap-2">
        <Button type="submit" disabled={pending || !instruction.trim()}>Save revised preview</Button>
        <Button type="button" variant="outline" disabled={pending} onClick={onCancel}>Discard edits</Button>
      </div>
    </form>
  );
}
