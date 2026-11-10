"use client";

import { useRouter } from "next/navigation";
import { useState } from "react";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { ApiError, api } from "@/lib/api/client";

type Field = {
  name: string;
  label: string;
  type?: string;
  required?: boolean;
  defaultValue?: string;
  options?: Array<{ value: string; label: string }>;
};

export function CreateRecordForm({
  endpoint,
  submitLabel,
  fields,
}: {
  endpoint: string;
  submitLabel: string;
  fields: Field[];
}) {
  const router = useRouter();
  const [error, setError] = useState<string | null>(null);
  const [pending, setPending] = useState(false);

  async function onSubmit(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setError(null);
    setPending(true);
    const form = event.currentTarget;
    const data = new FormData(form);
    const body: Record<string, string> = {};
    for (const field of fields) {
      const value = String(data.get(field.name) ?? "").trim();
      if (value === "" && field.required === false) {
        continue;
      }
      body[field.name] = value;
    }
    try {
      await api(endpoint, { method: "POST", body });
      form.reset();
      router.refresh();
    } catch (caught) {
      setError(caught instanceof ApiError ? caught.message : "Could not save.");
    } finally {
      setPending(false);
    }
  }

  return (
    <form onSubmit={onSubmit} className="grid gap-3 rounded-xl border p-4 sm:grid-cols-2">
      {fields.map((field) => {
        const id = `${endpoint}-${field.name}`;
        return (
          <div key={field.name} className="flex flex-col gap-1.5">
            <Label htmlFor={id}>{field.label}</Label>
            {field.type === "select" ? (
              <select
                id={id}
                name={field.name}
                required={field.required ?? true}
                defaultValue={field.defaultValue ?? ""}
                className="h-8 rounded-lg border border-input bg-transparent px-2.5 text-sm"
              >
                {field.required === false ? <option value="">None</option> : null}
                {(field.options ?? []).map((option) => (
                  <option key={option.value} value={option.value}>
                    {option.label}
                  </option>
                ))}
              </select>
            ) : (
              <Input
                id={id}
                name={field.name}
                type={field.type ?? "text"}
                required={field.required ?? true}
                defaultValue={field.defaultValue}
              />
            )}
          </div>
        );
      })}
      {error ? (
        <p role="alert" className="text-sm text-destructive sm:col-span-2">
          {error}
        </p>
      ) : null}
      <div className="sm:col-span-2">
        <Button type="submit" disabled={pending}>
          {pending ? "Saving…" : submitLabel}
        </Button>
      </div>
    </form>
  );
}
