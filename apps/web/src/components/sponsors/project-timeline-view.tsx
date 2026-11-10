"use client";

import { useMemo, useRef } from "react";
import { BryntumGantt } from "@bryntum/gantt-react";
import type { GridColumnConfig } from "@bryntum/gantt";
import "@bryntum/gantt/stockholm-light.css";
import type { Invoice, ProjectDetail } from "@/lib/api/types";
import { projectTimeline } from "@/lib/sponsor-data";

export default function ProjectTimelineView({ project, invoices }: { project: ProjectDetail; invoices: Invoice[] }) {
  const { tasks, undated } = useMemo(() => projectTimeline(project, invoices), [project, invoices]);
  const gantt = useRef<BryntumGantt>(null);
  const columns = useMemo<GridColumnConfig[]>(() => [
    { type: "name", text: "Milestone", field: "name", width: 240, htmlEncode: true },
    { text: "Amount", field: "amountLabel", width: 140, htmlEncode: true },
    { text: "Work status", field: "workStatus", width: 120, htmlEncode: true },
    { text: "Invoice status", field: "paymentStatus", width: 150, htmlEncode: true },
    { text: "Attention", field: "attention", width: 150, htmlEncode: true },
  ], []);
  return (
    <section aria-labelledby="project-timeline-title" className="flex min-w-0 flex-col gap-4 rounded-xl border bg-card p-4">
      <div>
        <h2 id="project-timeline-title" className="text-lg font-semibold">Milestone timeline</h2>
        <p className="mt-1 text-sm text-muted-foreground">Your milestone due dates and invoice status, powered by Bryntum. Red markers flag overdue invoices. Work acceptance and payment status are shown separately.</p>
      </div>
      {tasks.length > 0 ? (
        <div className="overflow-x-auto rounded-lg border bg-white text-slate-900" data-testid="project-timeline">
          <BryntumGantt
            ref={gantt}
            key={tasks.map((task) => `${task.id}:${task.startDate}:${task.paymentStatus}`).join("|")}
            height={420}
            readOnly
            tasks={tasks}
            columns={columns}
            startDate={project.starts_on ? new Date(`${project.starts_on}T00:00:00`) : undefined}
            endDate={project.ends_on ? new Date(`${project.ends_on}T00:00:00`) : undefined}
            viewPreset="weekAndDayLetter"
            cellEditFeature={false}
            taskEditFeature={false}
            taskDragFeature={false}
            taskResizeFeature={false}
            taskTooltipFeature={false}
            taskMenuFeature={false}
            cellMenuFeature={false}
            onPaint={({ firstPaint }) => { if (firstPaint) void gantt.current?.instance?.zoomToFit(); }}
          />
        </div>
      ) : <p className="text-sm text-muted-foreground">No dated milestones yet. Add a due date to display a milestone on the timeline.</p>}
      {undated.length > 0 && (
        <div>
          <h3 className="text-sm font-medium">Milestones without due dates</h3>
          <ul className="mt-2 space-y-1 text-sm text-muted-foreground">
            {undated.map((row) => <li key={row.id}>{row.name} · {row.amountLabel} · {row.paymentStatus}</li>)}
          </ul>
        </div>
      )}
      <p className="text-xs text-muted-foreground">The timeline is read-only. It does not reschedule work or infer payment dependencies from milestone order. Manually marked paid invoices are labeled as such.</p>
    </section>
  );
}
