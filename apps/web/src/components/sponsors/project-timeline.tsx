"use client";

import dynamic from "next/dynamic";
import type { Invoice, ProjectDetail } from "@/lib/api/types";

const Timeline = dynamic(() => import("./project-timeline-view"), {
  ssr: false,
  loading: () => <p role="status" className="p-6 text-sm text-muted-foreground">Loading milestone timeline…</p>,
});

export function ProjectTimeline(props: { project: ProjectDetail; invoices: Invoice[] }) {
  return <Timeline {...props} />;
}
