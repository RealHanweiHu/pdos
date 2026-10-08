"use client";

import { FolderDashedIcon, MagnifyingGlassIcon } from "@phosphor-icons/react";
import { useId, useRef, useState } from "react";

import { Button } from "@/components/ui/button";

import { cn } from "@/lib/utils";

import type { Project } from "./project-types";

export const projectStatusLabels: Record<Project["status"], string> = {
  draft: "草稿",
  proposed: "待批准",
  approved: "已批准",
  active: "进行中",
  on_hold: "已暂停",
  completed: "已完成",
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
  const controlsId = useId();
  const searchInput = useRef<HTMLInputElement>(null);
  const [query, setQuery] = useState("");
  const [status, setStatus] = useState<Project["status"] | "all">("all");
  const search = query.trim().toLocaleLowerCase();
  const filteredProjects = projects.filter((project) =>
    (status === "all" || project.status === status)
    && `${project.code} ${project.name} ${project.current_stage.name} ${project.current_stage.code}`
      .toLocaleLowerCase().includes(search),
  );
  const hasFilters = query.length > 0 || status !== "all";

  function resetFilters() {
    setQuery("");
    setStatus("all");
    searchInput.current?.focus();
  }

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
      <div className="flex flex-wrap items-center justify-between gap-2 border-b px-3 py-3">
        <h2 className="font-semibold">全部项目</h2>
        <p aria-live="polite" aria-atomic="true" className="text-xs text-muted-foreground">
          {hasFilters ? `${filteredProjects.length} / ${projects.length} 条` : `${projects.length} 条`}
        </p>
      </div>
      <div aria-label="查找项目" className="grid min-w-0 gap-3 border-b p-3 sm:grid-cols-[minmax(0,1fr)_160px_auto] sm:items-end" role="search">
        <div className="min-w-0">
          <label className="text-xs font-medium" htmlFor={`${controlsId}-search`}>搜索项目</label>
          <div className="relative mt-1">
            <MagnifyingGlassIcon aria-hidden="true" className="pointer-events-none absolute left-3 top-1/2 size-4 -translate-y-1/2 text-muted-foreground" />
            <input
              autoComplete="off"
              className="min-h-11 w-full min-w-0 rounded-md border bg-background py-2 pl-9 pr-3 text-sm font-normal placeholder:text-muted-foreground focus-visible:outline-none focus-visible:ring-3 focus-visible:ring-ring/30"
              id={`${controlsId}-search`}
              onChange={(event) => setQuery(event.target.value)}
              placeholder="名称、编号或阶段"
              ref={searchInput}
              spellCheck={false}
              type="search"
              value={query}
            />
          </div>
        </div>
        <label className="min-w-0 text-xs font-medium" htmlFor={`${controlsId}-status`}>
          项目状态
          <select
            className="mt-1 min-h-11 w-full min-w-0 rounded-md border bg-background px-3 py-2 text-sm font-normal focus-visible:outline-none focus-visible:ring-3 focus-visible:ring-ring/30"
            id={`${controlsId}-status`}
            onChange={(event) => setStatus(event.target.value as Project["status"] | "all")}
            value={status}
          >
            <option value="all">全部状态</option>
            {Object.entries(projectStatusLabels).map(([value, label]) => (
              <option key={value} value={value}>{label}</option>
            ))}
          </select>
        </label>
        {hasFilters && <Button className="min-h-11 justify-self-start" onClick={resetFilters} type="button" variant="ghost">重置筛选</Button>}
      </div>
      {filteredProjects.length === 0 ? (
        <div className="flex min-h-52 flex-col items-center justify-center gap-2 px-5 py-8 text-center">
          <MagnifyingGlassIcon aria-hidden="true" className="size-6 text-muted-foreground" />
          <h3 className="font-medium">没有符合条件的项目</h3>
          <p className="text-sm text-muted-foreground">调整名称、编号或阶段，或清除筛选查看全部项目。</p>
          <Button className="mt-2 min-h-11" onClick={resetFilters} type="button" variant="outline">清除筛选</Button>
        </div>
      ) : <>
      <div className="hidden grid-cols-[112px_minmax(0,1fr)_120px_80px] gap-3 border-b px-3 py-2 text-[11px] text-muted-foreground md:grid">
        <span>编号</span><span>项目名称</span><span>当前阶段</span><span>状态</span>
      </div>
      <ul role="list">
        {filteredProjects.map((project) => (
          <li className="border-b last:border-b-0" key={project.id}>
            <button
              aria-label={`打开项目 ${project.code}`}
              className={cn(
                "grid min-h-14 w-full grid-cols-[minmax(0,1fr)_auto] items-center gap-x-3 gap-y-1 px-3 py-3 text-left text-sm transition-colors hover:bg-muted/60 focus-visible:outline-none focus-visible:ring-3 focus-visible:ring-inset focus-visible:ring-ring/30 md:grid-cols-[112px_minmax(0,1fr)_120px_80px] md:py-2",
                selectedId === project.id && "bg-primary/8",
              )}
              onClick={() => onSelect(project)}
              type="button"
            >
              <span className="col-start-1 row-start-2 min-w-0 break-all font-mono text-xs text-muted-foreground md:col-auto md:row-auto">{project.code}</span>
              <span className="col-start-1 row-start-1 min-w-0 break-words font-medium md:col-auto md:row-auto md:truncate">{project.name}</span>
              <span className="col-start-1 row-start-3 min-w-0 break-words text-xs text-muted-foreground md:col-auto md:row-auto">{project.current_stage.name}</span>
              <span className="col-start-2 row-start-1 self-start text-xs text-muted-foreground md:col-auto md:row-auto md:self-auto">{projectStatusLabels[project.status]}</span>
            </button>
          </li>
        ))}
      </ul>
      </>}
    </section>
  );
}
