export default function Loading() {
  return (
    <div className="flex flex-col gap-3" aria-live="polite">
      <div className="h-8 w-40 animate-pulse rounded-md bg-muted" />
      <div className="h-4 w-full max-w-xl animate-pulse rounded-md bg-muted" />
      <div className="mt-4 grid gap-3 sm:grid-cols-2">
        <div className="h-24 animate-pulse rounded-xl bg-muted" />
        <div className="h-24 animate-pulse rounded-xl bg-muted" />
      </div>
      <p className="text-sm text-muted-foreground">Loading workspace data.</p>
    </div>
  );
}
