import { cn } from "cn";

const tones: Record<string, string> = {
  paid: "bg-emerald-500/10 text-emerald-800 dark:text-emerald-200",
  marked_as_paid: "bg-emerald-500/10 text-emerald-800 dark:text-emerald-200",
  succeeded: "bg-emerald-500/10 text-emerald-800 dark:text-emerald-200",
  completed: "bg-emerald-500/10 text-emerald-800 dark:text-emerald-200",
  approved: "bg-emerald-500/10 text-emerald-800 dark:text-emerald-200",
  sent: "bg-sky-500/10 text-sky-900 dark:text-sky-100",
  pending: "bg-amber-500/15 text-amber-950 dark:text-amber-100",
  pending_approval: "bg-amber-500/15 text-amber-950 dark:text-amber-100",
  pending_confirmation: "bg-amber-500/15 text-amber-950 dark:text-amber-100",
  waiting: "bg-amber-500/15 text-amber-950 dark:text-amber-100",
  paused: "bg-amber-500/15 text-amber-950 dark:text-amber-100",
  draft: "bg-muted text-muted-foreground",
  failed: "bg-destructive/10 text-destructive",
  blocked: "bg-destructive/10 text-destructive",
  cancelled: "bg-muted text-muted-foreground",
  canceled: "bg-muted text-muted-foreground",
  rejected: "bg-destructive/10 text-destructive",
  expired: "bg-destructive/10 text-destructive",
  refunded: "bg-muted text-muted-foreground",
};

export function StatusBadge({ status }: { status: string }) {
  return (
    <span
      className={cn(
        "inline-flex items-center rounded-md px-1.5 py-0.5 text-xs font-medium capitalize",
        tones[status] ?? "bg-muted text-foreground",
      )}
    >
      {status.replaceAll("_", " ")}
    </span>
  );
}
