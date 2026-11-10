"use client";

import { useRouter } from "next/navigation";
import { useState } from "react";

import { Button } from "@/components/ui/button";
import { ApiError, api } from "@/lib/api/client";
import type { Customer } from "@/lib/api/types";

const BLOCKING = [
  "prompt_injection",
  "ambiguous_parties",
  "ambiguous_total",
  "missing_total",
  "missing_milestones",
  "total_mismatch",
  "unsupported_currency",
  "invalid_amount",
];

export function ApplyContractButton({
  contractId,
  findings,
  projectId,
  customers,
}: {
  contractId: string;
  findings: string[];
  projectId: string | null;
  customers: Customer[];
}) {
  const router = useRouter();
  const [error, setError] = useState<string | null>(null);
  const [pending, setPending] = useState(false);
  const blocked = findings.some((finding) => BLOCKING.some((code) => finding.startsWith(code)));
  const active = customers.filter((customer) => customer.archived_at === null);

  async function apply(form: HTMLFormElement) {
    setPending(true);
    setError(null);
    const data = new FormData(form);
    try {
      await api(`/api/v1/contracts/${contractId}/apply`, {
        method: "POST",
        body: { customer_id: String(data.get("customer_id") ?? "") },
      });
      router.refresh();
    } catch (caught) {
      setError(caught instanceof ApiError ? caught.message : "The contract was not applied.");
    } finally {
      setPending(false);
    }
  }

  if (projectId) {
    return <p className="text-sm text-muted-foreground">Applied to a project. The extraction remains unverified.</p>;
  }
  if (blocked || active.length === 0) {
    return <p className="text-sm text-muted-foreground">Review the findings before creating a project.</p>;
  }

  return (
    <form
      className="flex flex-wrap items-center gap-2"
      onSubmit={(event) => {
        event.preventDefault();
        void apply(event.currentTarget);
      }}
    >
      <select name="customer_id" className="h-9 rounded-md border bg-transparent px-3 text-sm" required>
        {active.map((customer) => (
          <option key={customer.id} value={customer.id}>
            {customer.name}
          </option>
        ))}
      </select>
      <Button type="submit" disabled={pending}>
        Create project from review
      </Button>
      {error ? (
        <p role="alert" className="text-sm text-destructive">
          {error}
        </p>
      ) : null}
    </form>
  );
}
