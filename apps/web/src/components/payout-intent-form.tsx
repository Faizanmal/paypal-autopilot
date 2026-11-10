"use client";

import { useRouter } from "next/navigation";
import { useState } from "react";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { ApiError, api } from "@/lib/api/client";
import type { Contractor } from "@/lib/api/types";

export function PayoutIntentForm({ contractors }: { contractors: Contractor[] }) {
  const router = useRouter();
  const [error, setError] = useState<string | null>(null);
  const [pending, setPending] = useState(false);

  async function onSubmit(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setError(null);
    setPending(true);
    const form = event.currentTarget;
    const data = new FormData(form);
    try {
      await api("/api/v1/payout-requests", {
        method: "POST",
        body: {
          contractor_id: String(data.get("contractor_id") ?? ""),
          amount: String(data.get("amount") ?? "").trim(),
          currency_code: "USD",
        },
      });
      form.reset();
      router.refresh();
    } catch (caught) {
      setError(caught instanceof ApiError ? caught.message : "The payout intent was not saved.");
    } finally {
      setPending(false);
    }
  }

  return (
    <form onSubmit={onSubmit} className="grid gap-3 rounded-xl border p-4 sm:grid-cols-2">
      <div className="flex flex-col gap-1.5">
        <Label htmlFor="payout-contractor">Contractor</Label>
        <select
          id="payout-contractor"
          name="contractor_id"
          required
          className="h-8 rounded-lg border border-input bg-transparent px-2.5 text-sm"
        >
          {contractors.map((contractor) => (
            <option key={contractor.id} value={contractor.id}>
              {contractor.name}
            </option>
          ))}
        </select>
      </div>
      <div className="flex flex-col gap-1.5">
        <Label htmlFor="payout-amount">Amount</Label>
        <Input id="payout-amount" name="amount" inputMode="decimal" required placeholder="40.00" />
      </div>
      {error ? (
        <p role="alert" className="text-sm text-destructive sm:col-span-2">
          {error}
        </p>
      ) : null}
      <div className="sm:col-span-2">
        <Button type="submit" disabled={pending}>
          Save payout intent
        </Button>
      </div>
    </form>
  );
}
