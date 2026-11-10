import Link from "next/link";

import { buttonVariants } from "@/components/ui/button";
import { cn } from "@/lib/utils";

const pillars = [
  {
    name: "PayPal Autopilot",
    detail: "Invoices, payment monitoring, reminders, and contractor payouts.",
  },
  {
    name: "TrustFlow",
    detail: "Projects, milestones, and the payment conditions that bind them.",
  },
  {
    name: "SpendPilot",
    detail: "Spending policy, human approval, and financial exposure.",
  },
];

export default function Home() {
  return (
    <main className="mx-auto flex w-full max-w-3xl flex-1 flex-col justify-center gap-10 px-6 py-16">
      <div className="flex flex-col gap-3">
        <p className="text-sm font-medium text-muted-foreground">
          PayPal AI Hackathon 2026 · Sandbox only
        </p>
        <h1 className="text-4xl font-semibold tracking-tight">PayPal Autopilot</h1>
        <p className="max-w-xl text-base leading-7 text-muted-foreground">
          Describe a project, its milestones, and who gets paid. The platform turns that into a
          validated workflow. The model proposes. The backend checks policy, and a person approves
          every payout.
        </p>
      </div>
      <ul className="grid gap-3 sm:grid-cols-3">
        {pillars.map((pillar) => (
          <li key={pillar.name} className="rounded-xl border bg-card p-4">
            <p className="text-sm font-medium">{pillar.name}</p>
            <p className="mt-2 text-sm leading-6 text-muted-foreground">{pillar.detail}</p>
          </li>
        ))}
      </ul>
      <div className="flex flex-wrap items-center gap-3">
        <Link href="/register" className={cn(buttonVariants())}>
          Create a workspace
        </Link>
        <Link href="/login" className={cn(buttonVariants({ variant: "outline" }))}>
          Sign in
        </Link>
      </div>
    </main>
  );
}
