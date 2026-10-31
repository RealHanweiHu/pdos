import { FolderDashedIcon } from "@phosphor-icons/react/ssr";

import { cn } from "@/lib/utils";

import type { Project } from "./project-types";

export const projectStatusLabels: Record<Project["status"], string> = {
  draft: "草稿",
  proposed: "待批准",
  approved: "已批准",
  active: "进行中",
  on_hold: "已暂停",
  completed: "已完成",
  cancelled: "已取消",
  archived: "已归档",
};

export function ProjectList({
  onSelect,
  projects,
  selectedId,
}: {
  onSelect: (project: Project) => void;
  projects: Project[];
  selectedId: string | null;
}) {
  if (projects.length === 0) {
    return (
      <section className="flex min-h-64 flex-col items-center justify-center rounded-lg border border-dashed bg-card px-6 text-center">
        <FolderDashedIcon aria-hidden="true" className="size-8 text-muted-foreground" />
        <h2 className="mt-3 font-semibold">还没有项目</h2>
        <p className="mt-1 text-sm text-muted-foreground">从已批准的开发案例创建第一个项目。</p>
      </section>
    );
  }
  return (
    <section aria-label="项目列表" className="overflow-hidden rounded-lg border bg-card">
      <div className="flex items-center justify-between border-b px-3 py-3">
        <h2 className="font-semibold">全部项目</h2>
        <span className="text-xs text-muted-foreground">{projects.length} 条</span>
      </div>
      <div className="hidden grid-cols-[112px_minmax(0,1fr)_120px_80px] gap-3 border-b px-3 py-2 text-[11px] text-muted-foreground md:grid">
        <span>编号</span><span>项目名称</span><span>当前阶段</span><span>状态</span>
      </div>
      <ul role="list">
        {projects.map((project) => (
          <li className="border-b last:border-b-0" key={project.id}>
            <button
              aria-label={`打开项目 ${project.code}`}
              className={cn(
                "grid min-h-14 w-full grid-cols-[92px_minmax(0,1fr)_auto] items-center gap-3 px-3 py-2 text-left text-sm transition-colors hover:bg-muted/60 md:grid-cols-[112px_minmax(0,1fr)_120px_80px]",
                selectedId === project.id && "bg-primary/8",
              )}
              onClick={() => onSelect(project)}
              type="button"
            >
              <span className="font-mono text-xs">{project.code}</span>
              <span className="truncate font-medium">{project.name}</span>
              <span className="hidden text-xs text-muted-foreground md:block">{project.current_stage.name}</span>
              <span className="text-xs text-muted-foreground">{projectStatusLabels[project.status]}</span>
            </button>
          </li>
        ))}
      </ul>
    </section>
  );
}
