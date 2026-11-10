"use client";

import { useRouter } from "next/navigation";
import { useState } from "react";

import { Button } from "@/components/ui/button";
import { ApiError, api } from "@/lib/api/client";
import type { ScheduledAction } from "@/lib/api/types";

export function ScheduleControls({ action }: { action: ScheduledAction }) {
  const router = useRouter();
  const [error, setError] = useState<string | null>(null);
  const [pending, setPending] = useState(false);

  async function run(decision: "pause" | "resume" | "cancel") {
    setPending(true);
    setError(null);
    try {
      await api(`/api/v1/scheduled-actions/${action.id}/${decision}`, { method: "POST" });
      router.refresh();
    } catch (caught) {
      setError(caught instanceof ApiError ? caught.message : "The schedule was not changed.");
    } finally {
      setPending(false);
    }
  }

  return (
    <div className="flex flex-col items-start gap-2">
      <div className="flex flex-wrap gap-2">
        <Button type="button" variant="outline" size="sm" disabled={pending || action.status !== "pending"} onClick={() => void run("pause")}>
          Pause
        </Button>
        <Button type="button" variant="outline" size="sm" disabled={pending || action.status !== "paused"} onClick={() => void run("resume")}>
          Resume
        </Button>
        <Button
          type="button"
          variant="outline"
          size="sm"
          disabled={pending || !["pending", "paused", "failed"].includes(action.status)}
          onClick={() => void run("cancel")}
        >
          Cancel
        </Button>
      </div>
      {error ? (
        <p className="text-sm text-destructive" role="alert">
          {error}
        </p>
      ) : null}
    </div>
  );
}
