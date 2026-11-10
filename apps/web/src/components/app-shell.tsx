import Link from "next/link";

import { LogoutButton } from "@/components/logout-button";
import { ThemeToggle } from "@/components/theme-toggle";
import { WorkspaceNav } from "@/components/workspace-nav";
import type { AuthSession } from "@/lib/api/types";

export function AppShell({
  session,
  children,
}: {
  session: AuthSession;
  children: React.ReactNode;
}) {
  return (
    <div className="flex min-h-full flex-1 flex-col md:grid md:grid-cols-[15rem_minmax(0,1fr)]">
      <a
        href="#content"
        className="sr-only focus:not-sr-only focus:absolute focus:z-50 focus:m-3 focus:rounded-md focus:bg-background focus:px-3 focus:py-2 focus:shadow"
      >
        Skip to content
      </a>
      <aside className="border-b bg-card md:sticky md:top-0 md:h-svh md:border-r md:border-b-0">
        <div className="flex items-center justify-between gap-3 px-4 py-4 md:block">
          <div>
            <Link href="/app" className="text-sm font-semibold tracking-tight">
              PayPal Autopilot
            </Link>
            <p className="mt-1 text-xs text-muted-foreground">
              {session.workspace.name}
              <span className="sr-only">, role </span>
              <span aria-hidden="true"> · </span>
              {session.workspace.role}
            </p>
          </div>
          <div className="md:mt-4">
            <ThemeToggle />
          </div>
        </div>
        <div className="px-3 pb-4 md:px-3">
          <WorkspaceNav />
        </div>
      </aside>
      <div className="flex min-w-0 flex-1 flex-col">
        <div className="flex items-center justify-end border-b px-4 py-2 md:px-8">
          <p className="mr-auto text-sm text-muted-foreground">{session.user.full_name}</p>
          <LogoutButton />
        </div>
        <main id="content" className="mx-auto flex w-full max-w-6xl flex-1 flex-col px-4 py-6 md:px-8 md:py-8">
          {children}
        </main>
      </div>
    </div>
  );
}
