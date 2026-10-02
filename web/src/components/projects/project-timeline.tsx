"use client";

import { useState } from "react";
import { cn } from "@/lib/utils";
import { Button } from "@/components/ui/button";
import type { Project } from "./project-types";
import type { ProjectActivity } from "./project-activity";

const eventLabels: Record<string, string> = { TASK_CREATED: "创建任务", TASK_STATUS_CHANGED: "任务状态变更", ISSUE_CREATED: "创建问题", ISSUE_STATUS_CHANGED: "问题状态变更", RISK_CREATED: "登记风险", RISK_STATUS_CHANGED: "风险状态变更", PROJECT_CREATED: "创建项目", PROJECT_UPDATED: "项目资料更新", PROJECT_STATUS_CHANGED: "项目状态变更", PROJECT_STAGE_CHANGED: "项目阶段变更", TEST_FAILED: "测试未通过", DECISION_RECORDED: "新增决策", REMINDER_STATE_CHANGED: "提醒状态变更", FMEA_UPDATED: "设计风险资料更新" };
function formatTimestamp(value: string) {
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? "时间未提供" : new Intl.DateTimeFormat("zh-CN", { dateStyle: "medium", timeStyle: "short" }).format(date);
}
export function ProjectTimeline({ activities, activityError, loading, onRetry, highlightedEntityId, highlightedEventId }: { activities: ProjectActivity[]; activityError: boolean; loading: boolean; onRetry: () => void; highlightedEntityId: string | null; highlightedEventId: number | null; project: Project }) {
  const [expanded, setExpanded] = useState(false);
  const focused = activities.find(activity => activity.id === highlightedEventId || activity.entity_id === highlightedEntityId);
  // Reminder scheduling/acknowledgement is bookkeeping. Keep it in history
  // and linked receipts, while the default feed focuses on project changes.
  const recent = activities.filter(activity => activity.event_type !== "REMINDER_STATE_CHANGED").slice(0, 6);
  const shown = expanded ? activities : focused && !recent.includes(focused) ? [...recent.slice(0, 5), focused] : recent;
  return <section aria-label="项目动态" className="space-y-3" data-state={loading ? "loading" : activityError ? "error" : "ready"}>
    <div className="flex items-center justify-between gap-3"><h2 className="text-sm font-semibold">近期动态</h2>{!activityError && !loading && <span className="text-xs text-muted-foreground">{activities.length} 条记录</span>}</div>
    {activityError && <div><p className="text-sm text-destructive" role="alert">项目活动暂不可用；证据不会被显示为不存在。</p><Button className="mt-2" onClick={onRetry} size="sm" variant="outline">重新加载项目活动</Button></div>}
    {loading && <p className="text-sm text-muted-foreground" aria-busy="true">正在加载项目活动…</p>}
    {!loading && !activityError && activities.length === 0 && <p className="py-3 text-sm text-muted-foreground">还没有项目活动。</p>}
    {!loading && !activityError && activities.length > 0 && shown.length === 0 && <p className="py-3 text-sm text-muted-foreground">暂无新的项目进展。</p>}
    {!activityError && shown.length > 0 && <ol className="divide-y" role="list" aria-label="近期活动记录">{shown.map(activity => {
      const highlighted = activity.id === highlightedEventId || activity.entity_id === highlightedEntityId;
      return <li aria-current={highlighted ? "true" : undefined} className={cn("flex flex-wrap items-center justify-between gap-x-4 gap-y-1 rounded-md px-2 py-2.5 text-xs", highlighted && "bg-accent")} id={`event-${activity.id}`} key={activity.id}><span className="flex items-center gap-2"><span className="size-1.5 rounded-full bg-muted-foreground/50" aria-hidden="true"/><span title={`#${activity.id} · ${activity.event_type}`}>{eventLabels[activity.event_type] ?? "项目记录更新"}</span></span><time className="text-muted-foreground" dateTime={activity.timestamp}>{formatTimestamp(activity.timestamp)}</time></li>;
    })}</ol>}
    {!activityError && (expanded || activities.length > shown.length) && <Button size="sm" variant="ghost" onClick={() => setExpanded(!expanded)} aria-expanded={expanded}>{expanded ? "收起活动记录" : `展开全部 ${activities.length} 条记录`}</Button>}
    {!activityError && expanded && <details className="text-xs text-muted-foreground"><summary className="cursor-pointer py-2">查看原始事件类型</summary><ul aria-label="原始事件记录" className="max-h-56 space-y-2 overflow-y-auto">{activities.map(activity => <li key={activity.id}>#{activity.id} · {activity.event_type} · {activity.entity}</li>)}</ul></details>}
  </section>;
}
