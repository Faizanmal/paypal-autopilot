"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useState, useSyncExternalStore } from "react";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { ApiError, api } from "@/lib/api/client";
import type { AuthSession } from "@/lib/api/types";

type Mode = "login" | "register";

function subscribe() {
  return () => undefined;
}

export function AuthForm({ mode }: { mode: Mode }) {
  const router = useRouter();
  const [error, setError] = useState<string | null>(null);
  const [pending, setPending] = useState(false);
  const ready = useSyncExternalStore(subscribe, () => true, () => false);

  async function onSubmit(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setError(null);
    setPending(true);
    const form = new FormData(event.currentTarget);
    const body =
      mode === "login"
        ? { email: String(form.get("email")), password: String(form.get("password")) }
        : {
            email: String(form.get("email")),
            password: String(form.get("password")),
            full_name: String(form.get("full_name")),
            workspace_name: String(form.get("workspace_name")),
          };
    try {
      await api<AuthSession>(mode === "login" ? "/api/v1/auth/login" : "/api/v1/auth/register", {
        method: "POST",
        body,
      });
      router.push("/app");
      router.refresh();
    } catch (caught) {
      setError(caught instanceof ApiError ? caught.message : "Could not sign in.");
    } finally {
      setPending(false);
    }
  }

  return (
    <form method="post" onSubmit={onSubmit} className="flex w-full max-w-md flex-col gap-4">
      {mode === "register" ? (
        <>
          <Field label="Your name" name="full_name" autoComplete="name" />
          <Field label="Workspace name" name="workspace_name" autoComplete="organization" />
        </>
      ) : null}
      <Field label="Email" name="email" type="email" autoComplete="email" />
      <Field
        label="Password"
        name="password"
        type="password"
        autoComplete={mode === "login" ? "current-password" : "new-password"}
        minLength={mode === "register" ? 10 : 1}
      />
      {error ? (
        <p role="alert" className="text-sm text-destructive">
          {error}
        </p>
      ) : null}
      <Button type="submit" disabled={!ready || pending}>
        {pending ? "Working…" : mode === "login" ? "Sign in" : "Create workspace"}
      </Button>
      <p className="text-sm text-muted-foreground">
        {mode === "login" ? (
          <>
            New here? <Link href="/register" className="underline">Create an account</Link>
          </>
        ) : (
          <>
            Already registered? <Link href="/login" className="underline">Sign in</Link>
          </>
        )}
      </p>
    </form>
  );
}

function Field({
  label,
  name,
  type = "text",
  autoComplete,
  minLength,
}: {
  label: string;
  name: string;
  type?: string;
  autoComplete?: string;
  minLength?: number;
}) {
  const id = `field-${name}`;
  return (
    <div className="flex flex-col gap-1.5">
      <Label htmlFor={id}>{label}</Label>
      <Input
        id={id}
        name={name}
        type={type}
        required
        autoComplete={autoComplete}
        minLength={minLength}
      />
    </div>
  );
}
