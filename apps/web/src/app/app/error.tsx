"use client";

import { Button } from "@/components/ui/button";

export default function WorkspaceError({
  error,
  reset,
}: {
  error: Error & { digest?: string };
  reset: () => void;
}) {
  return (
    <section className="flex max-w-lg flex-col gap-4" role="alert">
      <h1 className="text-2xl font-semibold tracking-tight">This page could not be loaded</h1>
      <p className="text-sm text-muted-foreground">{error.message}</p>
      <div>
        <Button type="button" onClick={reset}>
          Try again
        </Button>
      </div>
    </section>
  );
}
