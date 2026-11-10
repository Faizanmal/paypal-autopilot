"use client";

import { useRouter } from "next/navigation";
import { useState } from "react";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { ApiError, api } from "@/lib/api/client";
import type { FinancialPolicy } from "@/lib/api/types";

const LEVELS = [
  { value: "0", label: "Observer" },
  { value: "1", label: "Assistant" },
  { value: "2", label: "Operator" },
  { value: "3", label: "Autopilot" },
];

const LIMITS = [
  { name: "per_transaction_limit", label: "Per transaction" },
  { name: "daily_limit", label: "Daily" },
  { name: "monthly_limit", label: "Monthly" },
  { name: "workspace_spending_limit", label: "Workspace total" },
] as const;

export function PolicyControls({ policy, canEdit }: { policy: FinancialPolicy; canEdit: boolean }) {
  const router = useRouter();
  const [error, setError] = useState<string | null>(null);
  const [pending, setPending] = useState(false);
  const level = LEVELS.find((item) => item.value === String(policy.autonomy_level));

  async function save(body: Record<string, unknown>) {
    setPending(true);
    setError(null);
    try {
      await api("/api/v1/financial-policy", { method: "PATCH", body });
      router.refresh();
    } catch (caught) {
      setError(caught instanceof ApiError ? caught.message : "The policy was not changed.");
    } finally {
      setPending(false);
    }
  }

  return (
    <div className="flex flex-col gap-4 rounded-xl border p-4">
      <div>
        <h2 className="text-lg font-semibold">Financial policy</h2>
        <p className="mt-1 text-sm text-muted-foreground">
          {level?.label ?? "Assistant"} mode. Payouts still need an exact owner approval.
          {policy.paused_at ? " This workspace is paused." : ""}
        </p>
      </div>
      {canEdit ? (
        <>
          <form
            className="flex flex-col gap-3 sm:flex-row sm:items-end"
            onSubmit={(event) => {
              event.preventDefault();
              const autonomy = String(new FormData(event.currentTarget).get("autonomy_level") ?? "1");
              void save({ autonomy_level: Number(autonomy) });
            }}
          >
            <div className="flex flex-col gap-1.5">
              <Label htmlFor="autonomy-level">Autonomy</Label>
              <select
                id="autonomy-level"
                name="autonomy_level"
                defaultValue={String(policy.autonomy_level)}
                className="h-8 rounded-lg border border-input bg-transparent px-2.5 text-sm"
              >
                {LEVELS.map((item) => (
                  <option key={item.value} value={item.value}>
                    {item.label}
                  </option>
                ))}
              </select>
            </div>
            <Button type="submit" variant="outline" disabled={pending}>
              Save autonomy
            </Button>
            <Button
              type="button"
              variant="outline"
              disabled={pending}
              onClick={() => save({ paused: policy.paused_at === null })}
            >
              {policy.paused_at ? "End pause" : "Emergency pause"}
            </Button>
          </form>
          <form
            className="grid gap-3 sm:grid-cols-2"
            onSubmit={(event) => {
              event.preventDefault();
              const data = new FormData(event.currentTarget);
              const body: Record<string, string | null> = {};
              for (const field of LIMITS) {
                const value = String(data.get(field.name) ?? "").trim();
                body[field.name] = value === "" ? null : value;
              }
              void save(body);
            }}
          >
            {LIMITS.map((field) => (
              <div key={field.name} className="flex flex-col gap-1.5">
                <Label htmlFor={field.name}>{field.label}</Label>
                <Input
                  id={field.name}
                  name={field.name}
                  inputMode="decimal"
                  defaultValue={policy[field.name] ?? ""}
                  placeholder="No limit"
                />
              </div>
            ))}
            <div className="sm:col-span-2">
              <Button type="submit" disabled={pending}>
                Save limits
              </Button>
            </div>
          </form>
        </>
      ) : (
        <p className="text-sm text-muted-foreground">Only the workspace owner can change these limits.</p>
      )}
      {error ? (
        <p role="alert" className="text-sm text-destructive">
          {error}
        </p>
      ) : null}
    </div>
  );
}
