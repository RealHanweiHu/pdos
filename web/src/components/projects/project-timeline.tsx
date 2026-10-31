"use client";

import { CheckIcon } from "@phosphor-icons/react/ssr";
import { type FormEvent, useState } from "react";

import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";

import { localIsoDate, stageSchedule } from "./project-task-planning";
import type { Project } from "./project-types";
import type { ProjectActivity } from "./project-activity";
import type { StagePlanInput } from "./use-project-actions";

const dateInputClass =
  "mt-1 min-h-11 w-full min-w-0 rounded-lg border border-input bg-background px-2 py-2 text-sm outline-none focus-visible:border-ring focus-visible:ring-3 focus-visible:ring-ring/20 disabled:opacity-60";

function shortDate(value: string | null | undefined) {
  return value ? value.slice(5) : "—";
}

function StagePlanForm({
  busy,
  onCancel,
  onSave,
  project,
}: {
  busy: boolean;
  onCancel: () => void;
  onSave: (stages: StagePlanInput[]) => Promise<boolean>;
  project: Project;
}) {
  const [plans, setPlans] = useState<StagePlanInput[]>(() =>
    project.workflow.stages.map((stage) => ({
      stage_id: stage.id,
      planned_start_date: stage.planned_start_date ?? null,
      planned_end_date: stage.planned_end_date ?? null,
    })),
  );
  const [error, setError] = useState<string | null>(null);

  function set(index: number, key: "planned_start_date" | "planned_end_date", value: string) {
    setPlans((current) => current.map((plan, position) => (position === index ? { ...plan, [key]: value || null } : plan)));
  }

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const invalid = plans.findIndex(
      (plan) => plan.planned_start_date && plan.planned_end_date && plan.planned_end_date < plan.planned_start_date,
    );
    if (invalid >= 0) {
      setError(`${project.workflow.stages[invalid].name}的结束日期早于开始日期。`);
      return;
    }
    setError(null);
    if (await onSave(plans)) onCancel();
  }

  return (
    <form aria-label="编辑阶段计划" className="mt-4 space-y-3 rounded-lg border bg-muted/25 p-3" onSubmit={submit}>
      {project.workflow.stages.map((stage, index) => (
        <fieldset className="grid gap-2 sm:grid-cols-[minmax(0,1fr)_160px_160px] sm:items-end" key={stage.id}>
          <legend className="sr-only">{stage.name}</legend>
          <p className="text-sm font-medium sm:pb-3"><span className="font-mono text-[11px] text-muted-foreground">P{stage.sequence}</span> {stage.name}</p>
          <label className="text-xs font-medium">
            计划开始
            <input aria-label={`${stage.name}计划开始`} className={dateInputClass} disabled={busy} onChange={(event) => set(index, "planned_start_date", event.target.value)} type="date" value={plans[index].planned_start_date ?? ""} />
          </label>
          <label className="text-xs font-medium">
            计划结束
            <input aria-label={`${stage.name}计划结束`} className={dateInputClass} disabled={busy} onChange={(event) => set(index, "planned_end_date", event.target.value)} type="date" value={plans[index].planned_end_date ?? ""} />
          </label>
        </fieldset>
      ))}
      {error ? <p className="text-xs text-destructive" role="alert">{error}</p> : null}
      <div className="flex flex-wrap justify-end gap-2">
        <Button className="h-11 sm:h-8" disabled={busy} onClick={onCancel} type="button" variant="outline">取消</Button>
        <Button className="h-11 sm:h-8" disabled={busy} type="submit">保存阶段计划</Button>
      </div>
    </form>
  );
}

function formatTimestamp(value: string) {
  return new Intl.DateTimeFormat("zh-CN", { dateStyle: "medium", timeStyle: "short" }).format(new Date(value));
}

export function ProjectTimeline({
  activities,
  activityError,
  canEditPlan = false,
  highlightedEntityId,
  highlightedEventId,
  onSavePlan,
  project,
  saving = false,
}: {
  activities: ProjectActivity[];
  activityError: boolean;
  canEditPlan?: boolean;
  highlightedEntityId: string | null;
  highlightedEventId: number | null;
  onSavePlan?: (stages: StagePlanInput[]) => Promise<boolean>;
  project: Project;
  saving?: boolean;
}) {
  const [editingPlan, setEditingPlan] = useState(false);
  const today = localIsoDate();
  const planLocked = project.status === "cancelled" || project.status === "archived";
  return (
    <section aria-label="项目阶段 Timeline" className="rounded-lg border bg-card p-4">
      <div className="flex items-end justify-between gap-4">
        <div>
          <p className="font-mono text-[11px] uppercase tracking-[0.14em] text-primary">Workflow v{project.workflow.version}</p>
          <h2 className="mt-1 font-semibold">项目阶段 Timeline</h2>
        </div>
        <div className="flex flex-wrap items-center justify-end gap-2">
          <span className="text-xs text-muted-foreground">当前 · {project.current_stage.name}</span>
          {canEditPlan && onSavePlan && !planLocked && !editingPlan ? (
            <Button className="h-11 sm:h-8" disabled={saving} onClick={() => setEditingPlan(true)} variant="outline">编辑阶段计划</Button>
          ) : null}
        </div>
      </div>
      {editingPlan && onSavePlan ? (
        <StagePlanForm busy={saving} onCancel={() => setEditingPlan(false)} onSave={onSavePlan} project={project} />
      ) : null}
      <ol className="mt-4 grid gap-2 sm:grid-cols-2 xl:grid-cols-7">
        {project.workflow.stages.map((stage) => {
          const completed = stage.sequence < project.current_stage.sequence;
          const current = stage.id === project.current_stage.id;
          const schedule = stageSchedule(stage, project.current_stage.sequence, today);
          return (
            <li className={cn("rounded-lg border p-3", current && "border-primary bg-primary/8", completed && "bg-muted/50")} key={stage.id}>
              <div className="flex items-center justify-between gap-2">
                <span className="font-mono text-[11px] text-muted-foreground">P{stage.sequence}</span>
                {completed ? <CheckIcon aria-label="已完成阶段" className="text-success" weight="bold" /> : null}
              </div>
              <p className="mt-2 text-sm font-medium">{stage.name}</p>
              <p className="mt-1 line-clamp-2 text-xs text-muted-foreground">{stage.description}</p>
              <dl className="mt-2 space-y-0.5 font-mono text-[10px] text-muted-foreground" data-testid={`stage-dates-${stage.code}`}>
                <div className="flex justify-between gap-2"><dt>计划</dt><dd>{shortDate(stage.planned_start_date)} → {shortDate(stage.planned_end_date)}</dd></div>
                <div className="flex justify-between gap-2"><dt>实际</dt><dd>{shortDate(stage.entered_at ? localIsoDate(new Date(stage.entered_at)) : null)} → {shortDate(stage.exited_at ? localIsoDate(new Date(stage.exited_at)) : null)}</dd></div>
              </dl>
              <span
                className={cn(
                  "mt-2 inline-flex rounded-full border px-2 py-0.5 text-[10px] font-medium",
                  schedule.tone === "late" && "border-destructive/25 bg-destructive/10 text-destructive",
                  schedule.tone === "ok" && "border-success/25 bg-success/10 text-success",
                  schedule.tone === "pending" && "border-pending/25 bg-pending/10 text-pending",
                  schedule.tone === "none" && "bg-muted text-muted-foreground",
                )}
                data-testid={`stage-schedule-${stage.code}`}
              >
                {schedule.label}
              </span>
            </li>
          );
        })}
      </ol>
      <div className="mt-5 border-t pt-4">
        <div className="flex items-center justify-between gap-3"><h3 className="font-semibold">近期项目活动</h3><span className="font-mono text-[10px] text-muted-foreground">最新 {activities.length} 条</span></div>
        {activityError ? <p className="mt-3 rounded-lg border border-destructive/30 bg-destructive/8 px-3 py-3 text-sm text-destructive" role="alert">项目活动暂不可用；证据不会被显示为不存在。</p> : null}
        {!activityError && activities.length === 0 ? <p className="mt-3 rounded-lg border border-dashed px-3 py-8 text-center text-sm text-muted-foreground">还没有项目活动。</p> : null}
        {!activityError && activities.length > 0 ? (
          <ol className="mt-3 divide-y overflow-hidden rounded-lg border" role="list">
            {activities.map((activity) => {
              const highlighted = activity.id === highlightedEventId || activity.entity_id === highlightedEntityId;
              return (
                <li
                  aria-current={highlighted ? "true" : undefined}
                  className={cn("grid gap-1 px-3 py-3 sm:grid-cols-[84px_minmax(0,1fr)_160px] sm:items-center", highlighted && "bg-primary/8 shadow-[inset_3px_0_0_var(--primary)]")}
                  id={`event-${activity.id}`}
                  key={activity.id}
                >
                  <span className="font-mono text-[11px] text-muted-foreground">#{activity.id}</span>
                  <span className="font-mono text-xs font-semibold text-primary">{activity.event_type}</span>
                  <span className="text-[11px] text-muted-foreground sm:text-right">{formatTimestamp(activity.timestamp)}</span>
                </li>
              );
            })}
          </ol>
        ) : null}
      </div>
    </section>
  );
}
