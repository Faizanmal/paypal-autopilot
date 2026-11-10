"use client";

import { useRouter } from "next/navigation";
import { useState } from "react";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { ApiError, api } from "@/lib/api/client";

export function MilestoneForm({ projectId, currencyCode }: { projectId: string; currencyCode: string }) {
  const router = useRouter();
  const [error, setError] = useState<string | null>(null);
  const [pending, setPending] = useState(false);

  async function onSubmit(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setError(null);
    setPending(true);
    const form = event.currentTarget;
    const data = new FormData(form);
    const due = String(data.get("due_on") ?? "").trim();
    const acceptance = String(data.get("acceptance_condition") ?? "").trim();
    try {
      await api(`/api/v1/projects/${projectId}/milestones`, {
        method: "POST",
        body: {
          name: String(data.get("name") ?? "").trim(),
          amount: String(data.get("amount") ?? "").trim(),
          currency_code: currencyCode,
          trigger_kind: String(data.get("trigger_kind") ?? "on_event"),
          ...(due ? { due_on: due } : {}),
          ...(acceptance ? { acceptance_condition: acceptance } : {}),
        },
      });
      form.reset();
      router.refresh();
    } catch (caught) {
      setError(caught instanceof ApiError ? caught.message : "Could not add this milestone.");
    } finally {
      setPending(false);
    }
  }

  return (
    <form onSubmit={onSubmit} className="grid gap-3 rounded-xl border p-4 sm:grid-cols-2">
      <div className="flex flex-col gap-1.5">
        <Label htmlFor="milestone-name">Milestone</Label>
        <Input id="milestone-name" name="name" required />
      </div>
      <div className="flex flex-col gap-1.5">
        <Label htmlFor="milestone-amount">Amount ({currencyCode})</Label>
        <Input id="milestone-amount" name="amount" required />
      </div>
      <div className="flex flex-col gap-1.5">
        <Label htmlFor="milestone-trigger">Trigger</Label>
        <select
          id="milestone-trigger"
          name="trigger_kind"
          className="h-8 rounded-lg border border-input bg-transparent px-2.5 text-sm"
          defaultValue="on_event"
        >
          <option value="upfront">Upfront</option>
          <option value="on_event">On event</option>
          <option value="on_delivery">On delivery</option>
        </select>
      </div>
      <div className="flex flex-col gap-1.5">
        <Label htmlFor="milestone-due">Due date</Label>
        <Input id="milestone-due" name="due_on" type="date" />
      </div>
      <div className="flex flex-col gap-1.5 sm:col-span-2">
        <Label htmlFor="milestone-acceptance">Acceptance condition</Label>
        <Input id="milestone-acceptance" name="acceptance_condition" />
      </div>
      {error ? (
        <p role="alert" className="text-sm text-destructive sm:col-span-2">
          {error}
        </p>
      ) : null}
      <div className="sm:col-span-2">
        <Button type="submit" disabled={pending}>
          {pending ? "Saving…" : "Add milestone"}
        </Button>
      </div>
    </form>
  );
}
