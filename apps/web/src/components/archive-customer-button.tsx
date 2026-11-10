"use client";

import { useRouter } from "next/navigation";
import { useState } from "react";

import { Button } from "@/components/ui/button";
import { ApiError, api } from "@/lib/api/client";

export function ArchiveCustomerButton({ customerId, archived }: { customerId: string; archived: boolean }) {
  const router = useRouter();
  const [error, setError] = useState<string | null>(null);
  const [pending, setPending] = useState(false);

  async function archive() {
    setPending(true);
    setError(null);
    try {
      await api(`/api/v1/customers/${customerId}/archive`, { method: "POST" });
      router.refresh();
    } catch (caught) {
      setError(caught instanceof ApiError ? caught.message : "Could not archive this customer.");
    } finally {
      setPending(false);
    }
  }

  if (archived) {
    return <p className="text-sm text-muted-foreground">Archived</p>;
  }

  return (
    <div className="flex flex-col items-start gap-1">
      <Button type="button" variant="outline" disabled={pending} onClick={archive}>
        Archive
      </Button>
      {error ? (
        <p role="alert" className="text-sm text-destructive">
          {error}
        </p>
      ) : null}
    </div>
  );
}
