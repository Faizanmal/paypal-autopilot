"use client";

import { useRouter } from "next/navigation";
import { useState } from "react";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { ApiError } from "@/lib/api/client";
import { env } from "@/lib/env";
import type { Customer } from "@/lib/api/types";

export function ContractUpload({ customers }: { customers: Customer[] }) {
  const router = useRouter();
  const [error, setError] = useState<string | null>(null);
  const [pending, setPending] = useState(false);

  async function onSubmit(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setError(null);
    setPending(true);
    const form = event.currentTarget;
    const data = new FormData(form);
    if (!String(data.get("customer_id") ?? "")) {
      data.delete("customer_id");
    }
    try {
      const response = await fetch(`${env.apiBaseUrl}/api/v1/contracts`, {
        method: "POST",
        body: data,
        credentials: "include",
      });
      const payload = (await response.json().catch(() => null)) as { error?: { message?: string } } | null;
      if (!response.ok) {
        throw new ApiError(response.status, "request_failed", payload?.error?.message ?? "Could not read this contract.");
      }
      form.reset();
      router.refresh();
    } catch (caught) {
      setError(caught instanceof ApiError ? caught.message : "Could not read this contract.");
    } finally {
      setPending(false);
    }
  }

  return (
    <form onSubmit={onSubmit} className="grid gap-3 rounded-xl border p-4">
      <div className="flex flex-col gap-1.5">
        <Label htmlFor="contract-file">PDF or DOCX</Label>
        <Input id="contract-file" name="file" type="file" accept=".pdf,.docx,application/pdf" required />
      </div>
      <div className="flex flex-col gap-1.5">
        <Label htmlFor="contract-customer">Customer</Label>
        <select id="contract-customer" name="customer_id" className="h-9 rounded-md border bg-transparent px-3 text-sm">
          <option value="">Choose later</option>
          {customers
            .filter((customer) => customer.archived_at === null)
            .map((customer) => (
              <option key={customer.id} value={customer.id}>
                {customer.name}
              </option>
            ))}
        </select>
      </div>
      {error ? (
        <p role="alert" className="text-sm text-destructive">
          {error}
        </p>
      ) : null}
      <div>
        <Button type="submit" disabled={pending}>
          Upload for review
        </Button>
      </div>
    </form>
  );
}
