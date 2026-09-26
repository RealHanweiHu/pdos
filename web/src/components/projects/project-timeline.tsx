import { CheckIcon } from "@phosphor-icons/react/ssr";

import { cn } from "@/lib/utils";
import { Button } from "@/components/ui/button";

import type { Project } from "./project-types";
import type { ProjectActivity } from "./project-activity";

function formatTimestamp(value: string) {
  return new Intl.DateTimeFormat("zh-CN", { dateStyle: "medium", timeStyle: "short" }).format(new Date(value));
}

export function ProjectTimeline({
  activities,
  activityError,
  loading,
  onRetry,
  highlightedEntityId,
  highlightedEventId,
  project,
}: {
  activities: ProjectActivity[];
  activityError: boolean;
  loading: boolean;
  onRetry: () => void;
  highlightedEntityId: string | null;
  highlightedEventId: number | null;
  project: Project;
}) {
  return (
    <section aria-label="项目阶段 Timeline" className="rounded-lg border bg-card p-4" data-state={loading ? "loading" : activityError ? "error" : "ready"}>
      <div className="flex items-end justify-between gap-4">
        <div>
          <p className="font-mono text-[11px] uppercase tracking-[0.14em] text-primary">Workflow v{project.workflow.version}</p>
          <h2 className="mt-1 font-semibold">项目阶段 Timeline</h2>
        </div>
        <span className="text-xs text-muted-foreground">当前 · {project.current_stage.name}</span>
      </div>
      <ol className="mt-4 grid gap-2 sm:grid-cols-2 xl:grid-cols-7">
        {project.workflow.stages.map((stage) => {
          const completed = stage.sequence < project.current_stage.sequence;
          const current = stage.id === project.current_stage.id;
          return (
            <li className={cn("rounded-lg border p-3", current && "border-primary bg-primary/8", completed && "bg-muted/50")} key={stage.id}>
              <div className="flex items-center justify-between gap-2">
                <span className="font-mono text-[11px] text-muted-foreground">P{stage.sequence}</span>
                {completed ? <CheckIcon aria-label="已完成阶段" className="text-success" weight="bold" /> : null}
              </div>
              <p className="mt-2 text-sm font-medium">{stage.name}</p>
              <p className="mt-1 line-clamp-2 text-xs text-muted-foreground">{stage.description}</p>
            </li>
          );
        })}
      </ol>
      <div className="mt-5 border-t pt-4">
        <div className="flex items-center justify-between gap-3"><h3 className="font-semibold">近期项目活动</h3><span className="font-mono text-[10px] text-muted-foreground">最新 {activities.length} 条</span></div>
        {activityError ? <p className="mt-3 rounded-lg border border-destructive/30 bg-destructive/8 px-3 py-3 text-sm text-destructive" role="alert">项目活动暂不可用；证据不会被显示为不存在。</p> : null}
        {activityError ? <Button className="mt-2" onClick={onRetry} variant="outline">重新加载项目活动</Button> : null}
        {loading ? <p className="mt-3 text-sm text-muted-foreground" aria-busy="true">正在加载项目活动…</p> : null}
        {!loading && !activityError && activities.length === 0 ? <p className="mt-3 rounded-lg border border-dashed px-3 py-8 text-center text-sm text-muted-foreground">还没有项目活动。</p> : null}
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
