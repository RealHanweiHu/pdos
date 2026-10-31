"use client";

import { type FormEvent, useState } from "react";

import { Button } from "@/components/ui/button";

import type { Project } from "./project-types";

const statusAction: Partial<Record<Project["status"], { label: string; to: Project["status"] }>> = {
  draft: { label: "提交立项", to: "proposed" },
  proposed: { label: "批准项目", to: "approved" },
  approved: { label: "启动项目", to: "active" },
  on_hold: { label: "恢复项目", to: "active" },
  completed: { label: "归档项目", to: "archived" },
  cancelled: { label: "归档项目", to: "archived" },
};

const cancellableStatuses = new Set<Project["status"]>(["draft", "proposed", "approved", "active", "on_hold"]);

export function ProjectStatusActions({
  busy,
  onStageTransition,
  onStatusTransition,
  project,
}: {
  busy: boolean;
  onStageTransition: (stageId: string) => void;
  onStatusTransition: (status: Project["status"], reason?: string) => void;
  project: Project;
}) {
  const [cancelling, setCancelling] = useState(false);
  const [reason, setReason] = useState("");
  const action = statusAction[project.status];
  const nextStage = project.workflow.stages.find(
    (stage) => stage.sequence === project.current_stage.sequence + 1,
  );

  function confirmCancel(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const trimmed = reason.trim();
    if (!trimmed) return;
    onStatusTransition("cancelled", trimmed);
    setCancelling(false);
    setReason("");
  }

  return (
    <div className="mt-4 border-t pt-4">
      <div className="flex flex-wrap justify-end gap-2">
        {project.status === "active" ? (
          <>
            <Button className="h-11 sm:h-8" disabled={busy} onClick={() => onStatusTransition("on_hold")} variant="outline">暂停项目</Button>
            <Button className="h-11 sm:h-8" disabled={busy} onClick={() => onStatusTransition("completed")} variant="outline">完成项目</Button>
            {nextStage ? <Button className="h-11 sm:h-8" disabled={busy} onClick={() => onStageTransition(nextStage.id)}>推进到{nextStage.name}</Button> : null}
          </>
        ) : action ? (
          <Button className="h-11 sm:h-8" disabled={busy} onClick={() => onStatusTransition(action.to)}>{action.label}</Button>
        ) : (
          <p className="text-xs text-muted-foreground">项目已归档，内容、状态与阶段均已锁定。</p>
        )}
        {cancellableStatuses.has(project.status) && !cancelling ? (
          <Button className="h-11 text-destructive sm:h-8" disabled={busy} onClick={() => setCancelling(true)} variant="ghost">取消项目</Button>
        ) : null}
      </div>
      {project.status === "cancelled" ? (
        <p className="mt-2 text-right text-xs text-muted-foreground">项目已取消，阶段计划已锁定；可归档留存。</p>
      ) : null}
      {cancelling ? (
        <form aria-label="取消项目" className="mt-3 space-y-2 rounded-lg border border-destructive/25 bg-destructive/5 p-3" onSubmit={confirmCancel}>
          <label className="block text-xs font-medium" htmlFor={`cancel-reason-${project.id}`}>
            取消原因
            <textarea
              className="mt-1 min-h-16 w-full rounded-lg border border-input bg-background px-3 py-2 text-sm outline-none focus-visible:border-ring focus-visible:ring-3 focus-visible:ring-ring/20"
              disabled={busy}
              id={`cancel-reason-${project.id}`}
              maxLength={2_000}
              onChange={(event) => setReason(event.target.value)}
              placeholder="例如：客户撤回需求、立项评审未通过"
              required
              value={reason}
            />
          </label>
          <p className="text-xs text-muted-foreground">取消后不能恢复，只能归档；原因会写入审计记录。</p>
          <div className="flex flex-wrap justify-end gap-2">
            <Button className="h-11 sm:h-8" disabled={busy} onClick={() => { setCancelling(false); setReason(""); }} type="button" variant="outline">返回</Button>
            <Button className="h-11 sm:h-8" disabled={busy || !reason.trim()} type="submit" variant="destructive">确认取消项目</Button>
          </div>
        </form>
      ) : null}
    </div>
  );
}
