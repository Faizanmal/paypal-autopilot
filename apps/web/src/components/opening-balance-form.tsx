"use client";

import { useRouter } from "next/navigation";
import { useState } from "react";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { ApiError, api } from "@/lib/api/client";

export function OpeningBalanceForm({
  openingBalance,
  asOf,
}: {
  openingBalance: string | null;
  asOf: string | null;
}) {
  const router = useRouter();
  const [error, setError] = useState<string | null>(null);
  const [pending, setPending] = useState(false);

  async function onSubmit(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setPending(true);
    setError(null);
    const form = new FormData(event.currentTarget);
    const amount = String(form.get("opening_balance") ?? "").trim();
    const asOfValue = String(form.get("as_of") ?? "").trim();
    try {
      await api("/api/v1/finance/assumptions", {
        method: "PUT",
        body: {
          opening_balance: amount.length > 0 ? amount : null,
          as_of: asOfValue.length > 0 ? asOfValue : null,
        },
      });
      router.refresh();
    } catch (caught) {
      setError(caught instanceof ApiError ? caught.message : "The opening balance was not saved.");
    } finally {
      setPending(false);
    }
  }

  return (
    <form onSubmit={onSubmit} className="grid gap-3 rounded-xl border p-4 sm:grid-cols-[1fr_1fr_auto] sm:items-end">
      <div className="flex flex-col gap-1.5">
        <Label htmlFor="opening-balance">Opening balance (USD)</Label>
        <Input
          id="opening-balance"
          name="opening_balance"
          inputMode="decimal"
          defaultValue={openingBalance ?? ""}
          placeholder="0.00"
          aria-describedby="opening-balance-help"
        />
      </div>
      <div className="flex flex-col gap-1.5">
        <Label htmlFor="opening-as-of">Balance date</Label>
        <Input id="opening-as-of" name="as_of" type="date" defaultValue={asOf ?? ""} />
      </div>
      <Button type="submit" disabled={pending}>
        {pending ? "Saving…" : "Save balance"}
      </Button>
      <p id="opening-balance-help" className="text-sm text-muted-foreground sm:col-span-3">
        Leave the amount blank to clear it. This is cash you supply. It is not read from PayPal.
      </p>
      {error ? (
        <p role="alert" className="text-sm text-destructive sm:col-span-3">
          {error}
        </p>
      ) : null}
    </form>
  );
}
