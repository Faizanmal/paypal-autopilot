import { redirect } from "next/navigation";
import { Suspense } from "react";

import { AppShell } from "@/components/app-shell";
import { serverApi } from "@/lib/api/server";
import type { AuthSession } from "@/lib/api/types";

// Authenticated pages read the session cookie and the API on every request.
export const instant = false;

export default function WorkspaceLayout({ children }: { children: React.ReactNode }) {
  return (
    <Suspense fallback={<main role="status" className="flex min-h-screen items-center justify-center p-6">
      Loading your workspace…
    </main>}>
      <AuthenticatedWorkspace>{children}</AuthenticatedWorkspace>
    </Suspense>
  );
}

async function AuthenticatedWorkspace({ children }: { children: React.ReactNode }) {
  const session = await serverApi<AuthSession>("/api/v1/auth/me");
  if (!session) {
    redirect("/login");
  }
  return <AppShell session={session}>{children}</AppShell>;
}
