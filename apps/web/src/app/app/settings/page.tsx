import Link from "next/link";

import { PageHeader } from "@/components/page-header";
import { PolicyControls } from "@/components/policy-controls";
import { serverApi } from "@/lib/api/server";
import type {
  AuthSession,
  CapabilityReport,
  FinancialPolicy,
  ItemList,
  WorkspaceMember,
  WorkspaceRuntime,
} from "@/lib/api/types";

export const instant = false;

export default async function SettingsPage() {
  const [session, members, runtime, policy, report] = await Promise.all([
    serverApi<AuthSession>("/api/v1/auth/me"),
    serverApi<ItemList<WorkspaceMember>>("/api/v1/workspace/members"),
    serverApi<WorkspaceRuntime>("/api/v1/workspace/runtime"),
    serverApi<FinancialPolicy>("/api/v1/financial-policy"),
    serverApi<CapabilityReport>("/api/v1/integrations/paypal/diagnostics"),
  ]);

  return (
    <section className="flex animate-in flex-col gap-8 fade-in duration-300">
      <PageHeader
        eyebrow="Workspace"
        title="Settings"
        description="Workspace identity, membership, autonomy, and the sandbox configuration the API is actually using."
      />
      <section className="rounded-xl border bg-card p-4">
        <h2 className="text-lg font-semibold">Workspace</h2>
        <dl className="mt-3 grid gap-3 text-sm sm:grid-cols-2">
          <div>
            <dt className="text-muted-foreground">Name</dt>
            <dd>{session?.workspace.name}</dd>
          </div>
          <div>
            <dt className="text-muted-foreground">Your role</dt>
            <dd>{session?.workspace.role}</dd>
          </div>
        </dl>
        <p className="mt-3 text-sm text-muted-foreground">Renaming the workspace is not available.</p>
      </section>
      <section className="rounded-xl border bg-card p-4">
        <h2 className="text-lg font-semibold">Team</h2>
        <ul className="mt-3 flex flex-col gap-2 text-sm">
          {(members?.items ?? []).map((member) => (
            <li key={member.user_id}>
              {member.full_name} · {member.email} · {member.role}
            </li>
          ))}
        </ul>
        <p className="mt-3 text-sm text-muted-foreground">Inviting another member is not available.</p>
      </section>
      <section className="rounded-xl border bg-card p-4">
        <h2 className="text-lg font-semibold">AI configuration</h2>
        <p className="mt-2 text-sm">
          Provider: {runtime?.ai_provider}. Credentials configured: {runtime?.ai_credentials_configured ? "yes" : "no"}.
        </p>
        <p className="mt-2 text-sm text-muted-foreground">
          The provider is set on the server. This screen cannot change it or reveal a key.
        </p>
      </section>
      {policy ? <PolicyControls policy={policy} canEdit={session?.workspace.role === "owner"} /> : null}
      <section className="rounded-xl border bg-card p-4">
        <h2 className="text-lg font-semibold">PayPal sandbox</h2>
        <p className="mt-2 text-sm">
          Environment: {runtime?.paypal_env}. Credentials configured: {runtime?.paypal_configured ? "yes" : "no"}.
          Payout execution: {runtime?.payouts_execution_enabled ? "enabled" : "disabled"}.
        </p>
        <ul className="mt-3 flex flex-col gap-2 text-sm">
          {(report?.checks ?? []).map((check) => (
            <li key={check.name}>
              <span className="font-medium">{check.name}</span> · {check.status}. {check.detail}
            </li>
          ))}
        </ul>
        <p className="mt-3 text-sm">
          <Link href="/app/paypal" className="underline-offset-4 hover:underline">
            Open sandbox tools
          </Link>
        </p>
      </section>
      <section className="rounded-xl border border-dashed p-4">
        <h2 className="text-lg font-semibold">Notifications</h2>
        <p className="mt-2 text-sm text-muted-foreground">
          Email and in-app notification preferences are not configured. Overdue notices are recorded as scheduled actions
          and audit events.
        </p>
        <button type="button" disabled className="mt-3 h-8 rounded-lg border px-3 text-sm opacity-50">
          Notification settings unavailable
        </button>
      </section>
    </section>
  );
}
