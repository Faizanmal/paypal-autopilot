"use client";

import { useRouter } from "next/navigation";
import { useState } from "react";

import { Button } from "@/components/ui/button";
import { ApiError, api } from "@/lib/api/client";

const NEXT: Record<string, string> = {
  draft: "active",
  active: "submitted",
  submitted: "accepted",
};

export function MilestoneActions({
  milestoneId,
  status,
}: {
  milestoneId: string;
  status: string;
}) {
  const router = useRouter();
  const [error, setError] = useState<string | null>(null);
  const [pending, setPending] = useState(false);
  const next = NEXT[status];

  async function run(path: string, body?: Record<string, string>) {
    setPending(true);
    setError(null);
    try {
      await api(path, { method: "POST", body });
      router.refresh();
    } catch (caught) {
      setError(caught instanceof ApiError ? caught.message : "The milestone was not changed.");
    } finally {
      setPending(false);
    }
  }

  return (
    <div className="flex flex-col items-start gap-2">
      <div className="flex flex-wrap gap-2">
        {next ? (
          <Button type="button" variant="outline" disabled={pending} onClick={() => run(`/api/v1/milestones/${milestoneId}/transition`, { status: next })}>
            Mark {next}
          </Button>
        ) : null}
        {status !== "cancelled" && status !== "paid" && status !== "invoiced" ? (
          <Button type="button" variant="outline" disabled={pending} onClick={() => run(`/api/v1/milestones/${milestoneId}/transition`, { status: "cancelled" })}>
            Cancel
          </Button>
        ) : null}
        <Button type="button" disabled={pending || status !== "accepted"} onClick={() => run(`/api/v1/milestones/${milestoneId}/invoice`)}>
          Create draft invoice
        </Button>
      </div>
      {error ? (
        <p role="alert" className="text-sm text-destructive">
          {error}
        </p>
      ) : null}
    </div>
  );
}
