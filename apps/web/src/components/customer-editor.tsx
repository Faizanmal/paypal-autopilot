"use client";

import { useRouter } from "next/navigation";
import { useState } from "react";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { ApiError, api } from "@/lib/api/client";
import type { Customer } from "@/lib/api/types";

export function CustomerEditor({ customer }: { customer: Customer }) {
  const router = useRouter();
  const [error, setError] = useState<string | null>(null);
  const [pending, setPending] = useState(false);
  const [open, setOpen] = useState(false);

  async function onSubmit(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setError(null);
    setPending(true);
    const data = new FormData(event.currentTarget);
    const optional = (name: string) => {
      const value = String(data.get(name) ?? "").trim();
      return value === "" ? null : value;
    };
    try {
      await api(`/api/v1/customers/${customer.id}`, {
        method: "PATCH",
        body: {
          name: String(data.get("name") ?? "").trim(),
          company_name: optional("company_name"),
          billing_email: optional("billing_email"),
          billing_address: optional("billing_address"),
        },
      });
      setOpen(false);
      router.refresh();
    } catch (caught) {
      setError(caught instanceof ApiError ? caught.message : "Could not update this customer.");
    } finally {
      setPending(false);
    }
  }

  if (!open) {
    return (
      <Button type="button" variant="outline" onClick={() => setOpen(true)}>
        Edit billing
      </Button>
    );
  }

  return (
    <form onSubmit={onSubmit} className="grid gap-3 sm:grid-cols-2">
      <div className="flex flex-col gap-1.5">
        <Label htmlFor={`${customer.id}-name`}>Name</Label>
        <Input id={`${customer.id}-name`} name="name" defaultValue={customer.name} required />
      </div>
      <div className="flex flex-col gap-1.5">
        <Label htmlFor={`${customer.id}-company`}>Company</Label>
        <Input id={`${customer.id}-company`} name="company_name" defaultValue={customer.company_name ?? ""} />
      </div>
      <div className="flex flex-col gap-1.5">
        <Label htmlFor={`${customer.id}-billing-email`}>Billing email</Label>
        <Input
          id={`${customer.id}-billing-email`}
          name="billing_email"
          type="email"
          defaultValue={customer.billing_email ?? ""}
        />
      </div>
      <div className="flex flex-col gap-1.5">
        <Label htmlFor={`${customer.id}-billing-address`}>Billing address</Label>
        <Input
          id={`${customer.id}-billing-address`}
          name="billing_address"
          defaultValue={customer.billing_address ?? ""}
        />
      </div>
      {error ? (
        <p role="alert" className="text-sm text-destructive sm:col-span-2">
          {error}
        </p>
      ) : null}
      <div className="flex gap-2 sm:col-span-2">
        <Button type="submit" disabled={pending}>
          {pending ? "Saving…" : "Save billing"}
        </Button>
        <Button type="button" variant="outline" onClick={() => setOpen(false)}>
          Cancel
        </Button>
      </div>
    </form>
  );
}
