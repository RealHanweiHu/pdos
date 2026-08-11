import { CheckIcon } from "@phosphor-icons/react/ssr";

import { cn } from "@/lib/utils";

import type { Project } from "./project-types";

export function ProjectTimeline({ project }: { project: Project }) {
  return (
    <section aria-label="项目阶段 Timeline" className="rounded-lg border bg-card p-4">
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
    </section>
  );
}
