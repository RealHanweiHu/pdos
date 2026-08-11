import { Button } from "@/components/ui/button";

import type { Project } from "./project-types";

const statusAction: Partial<Record<Project["status"], { label: string; to: Project["status"] }>> = {
  draft: { label: "提交立项", to: "proposed" },
  proposed: { label: "批准项目", to: "approved" },
  approved: { label: "启动项目", to: "active" },
  on_hold: { label: "恢复项目", to: "active" },
  completed: { label: "归档项目", to: "archived" },
};

export function ProjectStatusActions({
  busy,
  onStageTransition,
  onStatusTransition,
  project,
}: {
  busy: boolean;
  onStageTransition: (stageId: string) => void;
  onStatusTransition: (status: Project["status"]) => void;
  project: Project;
}) {
  const action = statusAction[project.status];
  const nextStage = project.workflow.stages.find(
    (stage) => stage.sequence === project.current_stage.sequence + 1,
  );
  return (
    <div className="mt-4 flex flex-wrap justify-end gap-2 border-t pt-4">
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
    </div>
  );
}
