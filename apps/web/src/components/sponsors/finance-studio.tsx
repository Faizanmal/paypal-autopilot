"use client";

import dynamic from "next/dynamic";
import type { Customer, FinanceSnapshot, Invoice } from "@/lib/api/types";

const Studio = dynamic(() => import("./finance-studio-view"), {
  ssr: false,
  loading: () => <p role="status" className="p-6 text-sm text-muted-foreground">Loading financial reports…</p>,
});

export function FinanceStudio(props: { invoices: Invoice[]; customers: Customer[]; snapshot: FinanceSnapshot }) {
  return <Studio {...props} />;
}
