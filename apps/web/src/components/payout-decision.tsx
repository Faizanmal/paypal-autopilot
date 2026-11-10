"use client";

import { useRouter } from "next/navigation";
import { useState } from "react";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { ApiError, api } from "@/lib/api/client";
import type { PayoutRequest } from "@/lib/api/types";

export function PayoutDecision({ payout }: { payout: PayoutRequest }) {
  const router = useRouter();
  const [error, setError] = useState<string | null>(null);
  const [pending, setPending] = useState(false);
  const waiting = payout.status === "pending_approval";

  async function run(path: string, body?: { reason: string }) {
    setPending(true);
    setError(null);
    try {
      await api(path, { method: "POST", body });
      router.refresh();
    } catch (caught) {
      setError(caught instanceof ApiError ? caught.message : "The payout was not changed.");
    } finally {
      setPending(false);
    }
  }

  return (
    <div className="flex flex-col gap-3">
      <div>
        <p className="font-medium">
          {payout.currency_code} {payout.amount} · {payout.status}
        </p>
        <p className="text-sm text-muted-foreground">{payout.recipient_email}</p>
        {payout.decision_reason ? (
          <p className="text-sm text-muted-foreground">Reason: {payout.decision_reason}</p>
        ) : null}
        <p className="text-sm text-muted-foreground">Approval does not send money.</p>
      </div>
      {waiting ? (
        <div className="flex flex-col gap-3 sm:flex-row sm:items-end">
          <Button type="button" disabled={pending} onClick={() => run(`/api/v1/payout-requests/${payout.id}/approve`)}>
            Approve
          </Button>
          <form
            className="flex flex-1 flex-col gap-2 sm:flex-row sm:items-end"
            onSubmit={(event) => {
              event.preventDefault();
              const form = event.currentTarget;
              const reason = String(new FormData(form).get("reason") ?? "").trim();
              void run(`/api/v1/payout-requests/${payout.id}/reject`, { reason });
            }}
          >
            <div className="flex flex-1 flex-col gap-1.5">
              <Label htmlFor={`reason-${payout.id}`}>Rejection reason</Label>
              <Input id={`reason-${payout.id}`} name="reason" required minLength={3} maxLength={500} />
            </div>
            <Button type="submit" variant="outline" disabled={pending}>
              Reject
            </Button>
          </form>
        </div>
      ) : null}
      {error ? (
        <p role="alert" className="text-sm text-destructive">
          {error}
        </p>
      ) : null}
    </div>
  );
}
