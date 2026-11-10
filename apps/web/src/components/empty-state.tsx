export function EmptyState({ title, detail }: { title: string; detail: string }) {
  return (
    <div className="rounded-xl border border-dashed px-4 py-8">
      <p className="text-sm font-medium">{title}</p>
      <p className="mt-1 max-w-xl text-sm text-muted-foreground">{detail}</p>
    </div>
  );
}
