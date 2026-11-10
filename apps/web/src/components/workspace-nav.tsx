"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useSyncExternalStore } from "react";

import { cn } from "cn";

const groups = [
  {
    label: "Work",
    links: [
      { href: "/app", label: "Overview" },
      { href: "/app/agent", label: "AI workspace" },
      { href: "/app/cash-flow", label: "Cash flow" },
      { href: "/app/automations", label: "Automations" },
    ],
  },
  {
    label: "Money",
    links: [
      { href: "/app/invoices", label: "Invoices" },
      { href: "/app/payouts", label: "Payouts" },
      { href: "/app/approvals", label: "Approvals" },
    ],
  },
  {
    label: "Records",
    links: [
      { href: "/app/projects", label: "Projects" },
      { href: "/app/contracts", label: "Contracts" },
      { href: "/app/customers", label: "Customers" },
      { href: "/app/contractors", label: "Contractors" },
    ],
  },
  {
    label: "Account",
    links: [
      { href: "/app/audit", label: "Audit log" },
      { href: "/app/settings", label: "Settings" },
    ],
  },
];

function active(pathname: string, href: string) {
  if (href === "/app") {
    return pathname === "/app";
  }
  return pathname === href || pathname.startsWith(`${href}/`);
}

function subscribe() {
  return () => undefined;
}

export function WorkspaceNav() {
  const pathname = usePathname();
  // Pathname-dependent active styles only after hydration to avoid Cache
  // Components / rewrite mismatches in the nav shell.
  const ready = useSyncExternalStore(subscribe, () => true, () => false);

  return (
    <nav aria-label="Workspace" className="flex gap-6 overflow-x-auto md:flex-col md:gap-6 md:overflow-visible">
      {groups.map((group) => (
        <div key={group.label} className="min-w-max md:min-w-0">
          <p className="mb-2 hidden text-xs font-medium tracking-wide text-muted-foreground uppercase md:block">
            {group.label}
          </p>
          <ul className="flex gap-1 md:flex-col">
            {group.links.map((link) => {
              const current = ready ? active(pathname, link.href) : false;
              return (
                <li key={link.href}>
                  <Link
                    href={link.href}
                    aria-current={current ? "page" : undefined}
                    className={cn(
                      "block rounded-md px-2 py-1.5 text-sm transition-colors hover:bg-muted focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-ring",
                      current ? "bg-muted font-medium text-foreground" : "text-muted-foreground",
                    )}
                  >
                    {link.label}
                  </Link>
                </li>
              );
            })}
          </ul>
        </div>
      ))}
    </nav>
  );
}
